"""Historical bar downloading for supported symbols and timeframes."""

from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from forex_daytrade.data.exceptions import UnsupportedSymbolError
from forex_daytrade.data.mt5_client import MT5Client
from forex_daytrade.data.types import IngestionTimeframe

logger = logging.getLogger(__name__)

SUPPORTED_SYMBOLS: frozenset[str] = frozenset({"EURUSD"})


def load_historical_bars(
    client: MT5Client,
    symbol: str,
    timeframe: IngestionTimeframe,
    date_from: datetime,
    date_to: datetime,
) -> pd.DataFrame:
    """Download raw historical bars for `symbol` over `[date_from, date_to]`.

    `client` must already be initialized (see `MT5Client.initialize`). The
    returned DataFrame contains raw MT5 columns and has not been normalized
    or validated yet.
    """
    if symbol not in SUPPORTED_SYMBOLS:
        raise UnsupportedSymbolError(
            f"Symbol {symbol!r} is not supported. Supported symbols: {sorted(SUPPORTED_SYMBOLS)}"
        )
    if date_from >= date_to:
        raise ValueError(f"date_from ({date_from}) must be before date_to ({date_to})")

    logger.info(
        "Downloading historical bars",
        extra={
            "symbol": symbol,
            "timeframe": timeframe.value,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
    )
    return client.copy_rates_range(symbol, timeframe, date_from, date_to)
