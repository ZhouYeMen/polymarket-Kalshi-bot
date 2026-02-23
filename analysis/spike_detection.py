"""Spike detection using Z-score and rolling statistics."""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from models.market_event import MarketEvent
import config


class SpikeDetector:
    """Detects probability spikes and volume surges using statistical methods."""
    
    def __init__(
        self,
        z_threshold: float = None,
        spike_window_minutes: int = None,
        spike_percentage: float = None,
        volume_surge_multiplier: float = None,
        retention_hours: int = None
    ):
        """Initialize spike detector.
        
        Args:
            z_threshold: Z-score threshold for spike detection (default from config)
            spike_window_minutes: Window in minutes for percentage change check (default from config)
            spike_percentage: Percentage change threshold (default from config)
            volume_surge_multiplier: Multiplier for volume surge detection (default from config)
            retention_hours: Hours of data to retain (default from config)
        """
        self.z_threshold = z_threshold or config.ODDS_SPIKE_Z_THRESHOLD
        self.spike_window_minutes = spike_window_minutes or config.ODDS_SPIKE_WINDOW_MINUTES
        self.spike_percentage = spike_percentage or config.ODDS_SPIKE_PERCENTAGE
        self.volume_surge_multiplier = volume_surge_multiplier or config.VOLUME_SURGE_MULTIPLIER
        self.retention_hours = retention_hours or config.DATA_RETENTION_HOURS
        
        # DataFrame to store historical data
        # Columns: market_id, timestamp, probability, volume, liquidity, source
        self.df: Optional[pd.DataFrame] = None
    
    def update(self, market: MarketEvent) -> None:
        """Update historical data with new market event.
        
        Args:
            market: MarketEvent to add to history
        """
        new_row = {
            "market_id": market.get_unique_id(),
            "timestamp": market.last_updated,
            "probability": market.probability,
            "volume": market.volume if market.volume is not None else 0.0,
            "liquidity": market.liquidity if market.liquidity is not None else 0.0,
            "source": market.source,
            "title": market.title,
            "url": market.url,
        }
        
        if self.df is None:
            self.df = pd.DataFrame([new_row])
        else:
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)
        
        # Clean up old data
        self._cleanup_old_data()
    
    def _cleanup_old_data(self) -> None:
        """Remove data older than retention period."""
        if self.df is None or self.df.empty:
            return
        
        cutoff_time = datetime.utcnow() - timedelta(hours=self.retention_hours)
        self.df = self.df[self.df["timestamp"] >= cutoff_time].copy()
    
    def detect_spikes(self, market: MarketEvent) -> Optional[Dict]:
        """Detect if a market has a probability spike.
        
        Args:
            market: MarketEvent to check for spikes
        
        Returns:
            Dictionary with spike information if detected, None otherwise
        """
        if self.df is None or self.df.empty:
            return None
        
        market_id = market.get_unique_id()
        market_data = self.df[self.df["market_id"] == market_id].copy()
        
        if len(market_data) < 2:
            return None  # Need at least 2 data points
        
        # Sort by timestamp
        market_data = market_data.sort_values("timestamp")
        
        current_prob = market.probability
        current_time = market.last_updated
        
        # Calculate rolling statistics (1 hour window)
        window = timedelta(hours=1)
        window_start = current_time - window
        
        historical_data = market_data[
            (market_data["timestamp"] >= window_start) &
            (market_data["timestamp"] < current_time)
        ]
        
        if len(historical_data) < 2:
            return None  # Need historical data for comparison
        
        # Calculate mean and standard deviation
        mean_prob = historical_data["probability"].mean()
        std_prob = historical_data["probability"].std()
        
        if std_prob == 0 or np.isnan(std_prob):
            # No variation, check absolute percentage change instead
            if mean_prob > 0:
                pct_change = abs((current_prob - mean_prob) / mean_prob) * 100
                if pct_change >= self.spike_percentage:
                    return {
                        "type": "spike",
                        "market": market,
                        "current_probability": current_prob,
                        "previous_mean": mean_prob,
                        "change_percentage": pct_change,
                        "z_score": None,
                        "method": "percentage",
                    }
            return None
        
        # Calculate Z-score
        z_score = (current_prob - mean_prob) / std_prob
        
        # Check Z-score threshold
        if abs(z_score) >= self.z_threshold:
            return {
                "type": "spike",
                "market": market,
                "current_probability": current_prob,
                "previous_mean": mean_prob,
                "previous_std": std_prob,
                "z_score": z_score,
                "change_percentage": abs((current_prob - mean_prob) / mean_prob) * 100 if mean_prob > 0 else 0,
                "method": "z_score",
            }
        
        # Also check for percentage change within time window
        window_minutes = timedelta(minutes=self.spike_window_minutes)
        window_start_minutes = current_time - window_minutes
        
        recent_data = market_data[
            (market_data["timestamp"] >= window_start_minutes) &
            (market_data["timestamp"] < current_time)
        ]
        
        if len(recent_data) > 0:
            oldest_prob = recent_data["probability"].iloc[0]
            if oldest_prob > 0:
                pct_change = abs((current_prob - oldest_prob) / oldest_prob) * 100
                if pct_change >= self.spike_percentage:
                    return {
                        "type": "spike",
                        "market": market,
                        "current_probability": current_prob,
                        "previous_probability": oldest_prob,
                        "change_percentage": pct_change,
                        "z_score": z_score,
                        "method": "percentage_window",
                    }
        
        return None
    
    def detect_volume_surge(self, market: MarketEvent) -> Optional[Dict]:
        """Detect if a market has a volume surge.
        
        Args:
            market: MarketEvent to check for volume surge
        
        Returns:
            Dictionary with volume surge information if detected, None otherwise
        """
        if self.df is None or self.df.empty or market.volume is None:
            return None
        
        market_id = market.get_unique_id()
        market_data = self.df[self.df["market_id"] == market_id].copy()
        
        if len(market_data) < 2:
            return None  # Need historical data
        
        # Sort by timestamp
        market_data = market_data.sort_values("timestamp")
        
        current_volume = market.volume
        current_time = market.last_updated
        
        # Calculate rolling average volume (1 hour window, excluding current)
        window = timedelta(hours=1)
        window_start = current_time - window
        
        historical_data = market_data[
            (market_data["timestamp"] >= window_start) &
            (market_data["timestamp"] < current_time) &
            (market_data["volume"] > 0)
        ]
        
        if len(historical_data) == 0:
            return None
        
        avg_volume = historical_data["volume"].mean()
        
        if avg_volume > 0 and current_volume >= avg_volume * self.volume_surge_multiplier:
            return {
                "type": "volume_surge",
                "market": market,
                "current_volume": current_volume,
                "average_volume": avg_volume,
                "multiplier": current_volume / avg_volume if avg_volume > 0 else 0,
            }
        
        return None
    
    def detect_anomalies(self, market: MarketEvent) -> List[Dict]:
        """Detect all types of anomalies for a market.
        
        Args:
            market: MarketEvent to check
        
        Returns:
            List of anomaly dictionaries (spikes, volume surges, etc.)
        """
        anomalies = []
        
        # Check for probability spike
        spike = self.detect_spikes(market)
        if spike:
            anomalies.append(spike)
        
        # Check for volume surge
        volume_surge = self.detect_volume_surge(market)
        if volume_surge:
            anomalies.append(volume_surge)
        
        return anomalies
