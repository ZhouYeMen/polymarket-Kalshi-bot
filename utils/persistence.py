"""Simple JSON file-based persistence for known IDs."""
import json
import os
from typing import Set, Dict, Tuple
from datetime import datetime


class StatePersistence:
    """Persists known market and trade IDs to a JSON file."""

    def __init__(self, state_file: str = ""):
        """Initialize persistence.

        Args:
            state_file: Path to state file. Empty string uses default path.
        """
        if not state_file:
            state_dir = os.path.expanduser("~/.polymarket_monitor")
            os.makedirs(state_dir, exist_ok=True)
            state_file = os.path.join(state_dir, "state.json")

        self.state_file = state_file

    def load_sets(self) -> Tuple[Set[str], Dict[str, datetime]]:
        """Load state from file and return as sets.

        Returns:
            Tuple of (known_market_ids: Set[str], known_trade_ids: Dict[str, datetime])
        """
        if not os.path.exists(self.state_file):
            return set(), {}

        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[WARN] Failed to load state file: {e}")
            return set(), {}

        market_ids = set(data.get("known_market_ids", []))

        raw_trades = data.get("known_trade_ids", {})
        if isinstance(raw_trades, list):
            # Backward compat: old format was a list
            trade_ids = {tid: datetime.utcnow() for tid in raw_trades}
        elif isinstance(raw_trades, dict):
            trade_ids = {}
            for tid, ts_str in raw_trades.items():
                try:
                    trade_ids[tid] = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    trade_ids[tid] = datetime.utcnow()
        else:
            trade_ids = {}

        return market_ids, trade_ids

    def save(
        self,
        known_market_ids: Set[str],
        known_trade_ids: Dict[str, datetime],
    ) -> None:
        """Save state to file.

        Args:
            known_market_ids: Set of known market unique IDs
            known_trade_ids: Dict of trade_id -> first_seen_time
        """
        data = {
            "known_market_ids": list(known_market_ids),
            "known_trade_ids": {
                tid: ts.isoformat() for tid, ts in known_trade_ids.items()
            },
            "last_saved": datetime.utcnow().isoformat(),
        }

        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            tmp_file = self.state_file + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_file, self.state_file)
        except IOError as e:
            print(f"[ERROR] Failed to save state file: {e}")
