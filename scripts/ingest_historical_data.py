#!/usr/bin/env python
"""CLI entry point: download, normalize, validate, and store historical bars.

Usage:
    python scripts/ingest_historical_data.py --from 2024-01-01 --to 2024-06-01

Downloads EURUSD bars (M5/M15/H1 by default) from an already-running,
logged-in MT5 terminal, normalizes timestamps to UTC, classifies trading
sessions, validates data quality, stores the normalized Parquet dataset plus
metadata, and writes a JSON validation report under reports/data_quality/.

Requires the MetaTrader5 package (Windows only) and a running MT5 terminal;
this script is not covered by unit tests, which mock the data layer instead.
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

from forex_daytrade.data.config import DataConfig
from forex_daytrade.data.historical_loader import SUPPORTED_SYMBOLS, load_historical_bars
from forex_daytrade.data.metadata import build_metadata, save_metadata
from forex_daytrade.data.mt5_client import MT5Client
from forex_daytrade.data.normalizer import normalize_bars
from forex_daytrade.data.sessions import add_session_column
from forex_daytrade.data.storage import save_normalized_dataset
from forex_daytrade.data.types import IngestionTimeframe
from forex_daytrade.data.validator import save_validation_report, validate_dataset

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "data_quality"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="EURUSD", choices=sorted(SUPPORTED_SYMBOLS))
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=[tf.value for tf in IngestionTimeframe],
        choices=[tf.value for tf in IngestionTimeframe],
    )
    parser.add_argument("--from", dest="date_from", required=True, type=_parse_date)
    parser.add_argument("--to", dest="date_to", required=True, type=_parse_date)
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)
    config = DataConfig.from_env()

    with MT5Client(terminal_path=config.mt5_terminal_path) as client:
        for timeframe_value in args.timeframes:
            timeframe = IngestionTimeframe(timeframe_value)
            raw = load_historical_bars(
                client, args.symbol, timeframe, args.date_from, args.date_to
            )
            normalized = normalize_bars(raw, args.symbol, config.broker_timezone)
            normalized = add_session_column(normalized)

            report = validate_dataset(normalized, args.symbol, timeframe)
            save_validation_report(report, REPORTS_DIR)
            if not report.is_valid:
                logger.error(
                    "Validation failed for %s %s: %s",
                    args.symbol,
                    timeframe.value,
                    [issue.check for issue in report.errors],
                )
                continue

            save_normalized_dataset(normalized, config.normalized_dir, args.symbol, timeframe)
            metadata = build_metadata(normalized, args.symbol, timeframe, source="MT5")
            save_metadata(metadata, config.metadata_dir)
            logger.info("Ingested %s %s: %d rows", args.symbol, timeframe.value, len(normalized))

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
