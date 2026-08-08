"""
NOAFVGBOT V2.1 — As-Of Multi-Timeframe Candle Aligner.

Provides a strict zero-lookahead as-of view across multiple timeframes.
A candle becomes visible if and only if candle.timestamp_close_utc <= as_of_utc.
"""

from typing import Dict, List, Optional
from research.v2.data.models import CandleV2, Timeframe


class AsOfAligner:
    """As-Of Multi-Timeframe Alignment Manager."""

    def __init__(self, datasets: Optional[Dict[Timeframe, List[CandleV2]]] = None):
        self.datasets: Dict[Timeframe, List[CandleV2]] = {}
        if datasets:
            for tf, candles in datasets.items():
                # Sort datasets by timestamp_close_utc for fast, safe binary/linear search
                self.datasets[tf] = sorted(candles, key=lambda c: c.timestamp_close_utc)

    def load_dataset(self, timeframe: Timeframe, candles: List[CandleV2]) -> None:
        self.datasets[timeframe] = sorted(candles, key=lambda c: c.timestamp_close_utc)

    def view_at(self, as_of_utc: str) -> Dict[Timeframe, List[CandleV2]]:
        """Returns all completed closed candles across all timeframes visible at as_of_utc."""
        res = {}
        for tf, candles in self.datasets.items():
            res[tf] = [c for c in candles if c.timestamp_close_utc <= as_of_utc]
        return res

    def latest_closed(self, timeframe: Timeframe, as_of_utc: str) -> Optional[CandleV2]:
        """Returns the single most recently closed candle for timeframe as of as_of_utc."""
        candles = self.datasets.get(timeframe, [])
        visible = [c for c in candles if c.timestamp_close_utc <= as_of_utc]
        return visible[-1] if visible else None

    def history(self, timeframe: Timeframe, as_of_utc: str, count: int) -> List[CandleV2]:
        """Returns up to `count` recent closed candles for timeframe as of as_of_utc."""
        if count <= 0:
            return []
        candles = self.datasets.get(timeframe, [])
        visible = [c for c in candles if c.timestamp_close_utc <= as_of_utc]
        return visible[-count:]
