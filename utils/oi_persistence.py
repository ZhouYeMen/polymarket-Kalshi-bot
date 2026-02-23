"""Open Interest snapshot persistence for computing 1D/7D OI deltas."""
import json
import os
from typing import Dict, List, Optional
from datetime import datetime, timedelta


class OIPersistence:
    """Persists OI snapshots to a JSON file for delta computation across runs."""

    def __init__(self, file_path: str = ""):
        if not file_path:
            state_dir = os.path.expanduser("~/.polymarket_monitor")
            os.makedirs(state_dir, exist_ok=True)
            file_path = os.path.join(state_dir, "oi_history.json")

        self.file_path = file_path
        self._snapshots: Optional[List[Dict]] = None

    def _load(self) -> List[Dict]:
        """Load snapshots from disk (cached after first read)."""
        if self._snapshots is not None:
            return self._snapshots

        if not os.path.exists(self.file_path):
            self._snapshots = []
            return self._snapshots

        try:
            with open(self.file_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            self._snapshots = []
            return self._snapshots

        self._snapshots = data.get("snapshots", [])
        return self._snapshots

    def save_snapshot(self, oi_data: Dict[str, float]) -> None:
        """Append a new OI snapshot and prune old entries (>8 days).

        Args:
            oi_data: {slug: oi_value} mapping for current run
        """
        if not oi_data:
            return

        snapshots = self._load()

        now = datetime.utcnow()
        snapshots.append({
            "timestamp": now.isoformat(),
            "data": oi_data,
        })

        # Prune snapshots older than 8 days
        cutoff = now - timedelta(days=8)
        snapshots = [
            s for s in snapshots
            if _parse_ts(s.get("timestamp", "")) >= cutoff
        ]
        self._snapshots = snapshots

        payload = {
            "snapshots": snapshots,
            "last_saved": now.isoformat(),
        }

        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            tmp_file = self.file_path + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_file, self.file_path)
        except IOError as e:
            print(f"[ERROR] Failed to save OI history: {e}")

    def compute_deltas(
        self, current_oi: Dict[str, float]
    ) -> Dict[str, Dict]:
        """Compute 1D and 7D OI deltas for each slug.

        Args:
            current_oi: {slug: current_oi_value}

        Returns:
            {slug: {"oi": current, "oi_1d": delta, "oi_7d": delta,
                     "oi_1d_pct": pct_change, "oi_7d_pct": pct_change}}
            Deltas are None when no historical snapshot is available.
        """
        snapshots = self._load()
        if not snapshots:
            return {}

        now = datetime.utcnow()
        target_1d = now - timedelta(days=1)
        target_7d = now - timedelta(days=7)

        snap_1d = _closest_snapshot(snapshots, target_1d)
        snap_7d = _closest_snapshot(snapshots, target_7d)

        result: Dict[str, Dict] = {}
        for slug, current in current_oi.items():
            entry: Dict = {"oi": current, "oi_1d": None, "oi_7d": None,
                           "oi_1d_pct": None, "oi_7d_pct": None}

            if snap_1d is not None:
                old_val = snap_1d.get("data", {}).get(slug)
                if old_val is not None:
                    delta = current - old_val
                    entry["oi_1d"] = delta
                    entry["oi_1d_pct"] = (delta / old_val * 100) if old_val != 0 else 0.0

            if snap_7d is not None:
                old_val = snap_7d.get("data", {}).get(slug)
                if old_val is not None:
                    delta = current - old_val
                    entry["oi_7d"] = delta
                    entry["oi_7d_pct"] = (delta / old_val * 100) if old_val != 0 else 0.0

            result[slug] = entry

        return result


def _parse_ts(ts_str: str) -> datetime:
    """Parse an ISO timestamp string, returning epoch on failure."""
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return datetime.min


def _closest_snapshot(
    snapshots: List[Dict], target: datetime
) -> Optional[Dict]:
    """Find the snapshot closest to the target time.

    Only considers snapshots that are at least 30 minutes before now
    (to avoid matching the snapshot we just saved).
    Returns None if no snapshots are within 12 hours of the target.
    """
    best = None
    best_diff = timedelta(hours=12)  # max acceptable distance

    for s in snapshots:
        ts = _parse_ts(s.get("timestamp", ""))
        diff = abs(ts - target)
        if diff < best_diff:
            best_diff = diff
            best = s

    return best
