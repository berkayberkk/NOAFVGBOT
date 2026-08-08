"""
NOAFVGBOT V2.1 — Multi-Timeframe Event Clock.

Constructs a canonical, deterministic, chronological MarketEvent stream from
multi-timeframe candle datasets.

SAME-TIMESTAMP ORDERING CONVENTION:
When multiple timeframes close at the exact same timestamp T, events are emitted in order:
M30 -> M15 -> M5 -> M3 -> M1
This guarantees higher-timeframe state is fully closed and updated before lower-timeframe
triggers execute.
"""

from typing import Dict, List
from research.v2.data.models import CandleV2, MarketEvent, Timeframe

# Same-timestamp priority mapping (M30=1, M15=2, M5=3, M3=4, M1=5)
TIMEFRAME_PRIORITY = {
    Timeframe.M30: 1,
    Timeframe.M15: 2,
    Timeframe.M5: 3,
    Timeframe.M3: 4,
    Timeframe.M1: 5,
}


class MultiTimeframeClock:
    """Deterministic Multi-Timeframe Event Clock Generator."""

    def __init__(self, datasets: Dict[Timeframe, List[CandleV2]]):
        self.datasets = datasets

    def build_event_stream(self) -> List[MarketEvent]:
        """Builds a deterministically sorted chronological MarketEvent stream."""
        raw_events: List[MarketEvent] = []

        for tf, candles in self.datasets.items():
            for c in candles:
                event = MarketEvent(
                    timestamp_utc=c.timestamp_close_utc,
                    timeframe=tf,
                    candle=c,
                )
                raw_events.append(event)

        # Sort key: (timestamp_utc, TIMEFRAME_PRIORITY)
        sorted_events = sorted(
            raw_events,
            key=lambda e: (e.timestamp_utc, TIMEFRAME_PRIORITY.get(e.timeframe, 99))
        )
        return sorted_events
