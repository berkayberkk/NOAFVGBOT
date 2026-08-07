"""
Tarihsel Veri Kalitesi ve Denetim Katmanı (Historical Data Quality & Audit Layer).

Bu modül backtest öncesinde OHLC verilerinin sayısal geçerliliğini, kronolojik
sıralamasını, mükerrer/çelişkili kayıtları, zaman dilimi tutarlılığını ve aşırı
fiyat sapmalarını katı ve deterministik kurallarla denetler.
"""

from dataclasses import dataclass, field
from enum import Enum
import math

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional


class QualityCheckStatus(Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class IntervalType(Enum):
    NORMAL = "NORMAL_INTERVAL"
    IRREGULAR = "IRREGULAR_INTERVAL"
    LARGE_GAP = "LARGE_GAP_REQUIRING_REVIEW"


@dataclass
class CandleAnomaly:
    index: int
    timestamp: str
    anomaly_type: str
    message: str
    severity: QualityCheckStatus


@dataclass
class GapInfo:
    previous_index: int
    previous_timestamp: str
    next_index: int
    next_timestamp: str
    observed_delta_seconds: float
    expected_delta_seconds: float
    estimated_missing_bars: int
    category: IntervalType


@dataclass
class DataQualityReport:
    candle_count: int = 0
    start_timestamp: str = ""
    end_timestamp: str = ""
    status: QualityCheckStatus = QualityCheckStatus.PASS
    
    # İnceleme Sayacı ve Detayları
    missing_fields: int = 0
    invalid_numeric_values: int = 0
    ohlc_violations: int = 0
    duplicate_timestamps: int = 0
    conflicting_duplicates: int = 0
    out_of_order_timestamps: int = 0
    
    # Zaman ve Aralık Detayları
    expected_timeframe_seconds: Optional[float] = None
    normal_intervals: int = 0
    irregular_intervals: int = 0
    large_gaps: int = 0
    total_estimated_missing_bars: int = 0
    
    # Anomaliler ve Uarılar
    anomalies: List[CandleAnomaly] = field(default_factory=list)
    gaps: List[GapInfo] = field(default_factory=list)


def infer_timeframe_seconds(candles: List[Dict[str, Any]]) -> Optional[float]:
    """
    Veri kümesinden baskın zaman dilimini (saniye cinsinden median delta) türetir.
    """
    if len(candles) < 2:
        return None

    deltas = []
    for i in range(1, len(candles)):
        t_prev = candles[i - 1].get("time")
        t_curr = candles[i].get("time")
        if isinstance(t_prev, (datetime, str)) and isinstance(t_curr, (datetime, str)):
            dt_prev = t_prev if isinstance(t_prev, datetime) else datetime.fromisoformat(str(t_prev))
            dt_curr = t_curr if isinstance(t_curr, datetime) else datetime.fromisoformat(str(t_curr))
            diff = (dt_curr - dt_prev).total_seconds()
            if diff > 0:
                deltas.append(diff)

    if not deltas:
        return None

    deltas.sort()
    mid = len(deltas) // 2
    if len(deltas) % 2 == 1:
        return deltas[mid]
    else:
        return (deltas[mid - 1] + deltas[mid]) / 2.0


def audit_dataset(
    candles: List[Dict[str, Any]],
    expected_timeframe_seconds: Optional[float] = None,
    allow_warning: bool = True,
    extreme_range_factor: float = 5.0,
    extreme_jump_factor: float = 5.0,
) -> DataQualityReport:
    """
    OHLC mum verilerini sıfır sızıntı ve katı kurallarla denetler.
    Asla veriyi sessizce sıralamaz, silmez veya sentetik mum türetmez.
    """
    report = DataQualityReport()
    report.candle_count = len(candles)

    if not candles:
        report.status = QualityCheckStatus.FAIL
        report.anomalies.append(CandleAnomaly(0, "", "EMPTY_DATASET", "Veri kümesi boş", QualityCheckStatus.FAIL))
        return report

    report.start_timestamp = str(candles[0].get("time", ""))
    report.end_timestamp = str(candles[-1].get("time", ""))

    # Zaman dilimi tespiti
    if expected_timeframe_seconds is not None:
        report.expected_timeframe_seconds = expected_timeframe_seconds
    else:
        report.expected_timeframe_seconds = infer_timeframe_seconds(candles)

    ranges = []
    jumps = []
    parsed_timestamps = []

    for i, c in enumerate(candles):
        ts = str(c.get("time", ""))

        # 1. Eksik alan kontrolü
        required_fields = ["time", "open", "high", "low", "close"]
        missing = [f for f in required_fields if f not in c or c[f] is None]
        if missing:
            report.missing_fields += 1
            report.anomalies.append(
                CandleAnomaly(i, ts, "MISSING_FIELD", f"Eksik alanlar: {missing}", QualityCheckStatus.FAIL)
            )
            continue

        # 2. Sayısal ve Sonlu Değer Kontrolü
        try:
            o = float(c["open"])
            h = float(c["high"])
            l = float(c["low"])
            close_price = float(c["close"])
        except (ValueError, TypeError):
            report.invalid_numeric_values += 1
            report.anomalies.append(
                CandleAnomaly(i, ts, "INVALID_NUMERIC", "OHLC değerleri sayısal değil", QualityCheckStatus.FAIL)
            )
            continue

        if any(math.isnan(v) or math.isinf(v) for v in (o, h, l, close_price)):
            report.invalid_numeric_values += 1
            report.anomalies.append(
                CandleAnomaly(i, ts, "NON_FINITE_VALUE", "OHLC değerlerinde NaN/Inf var", QualityCheckStatus.FAIL)
            )
            continue

        if any(v <= 0 for v in (o, h, l, close_price)):
            report.invalid_numeric_values += 1
            report.anomalies.append(
                CandleAnomaly(i, ts, "NON_POSITIVE_PRICE", "OHLC değerleri sıfır veya negatif", QualityCheckStatus.FAIL)
            )
            continue

        # 3. Yapısal Invariant Kontrolü
        if not (h >= max(o, close_price) and l <= min(o, close_price) and h >= l):
            report.ohlc_violations += 1
            report.anomalies.append(
                CandleAnomaly(
                    i, ts, "OHLC_VIOLATION",
                    f"Mantıksız OHLC yapısı: H={h}, L={l}, O={o}, C={close_price}",
                    QualityCheckStatus.FAIL
                )
            )

        ranges.append(h - l)
        if i > 0 and len(parsed_timestamps) > 0:
            prev_c = candles[i - 1]
            try:
                prev_close = float(prev_c.get("close", 0))
                if prev_close > 0:
                    jumps.append(abs(close_price - prev_close))
            except (ValueError, TypeError):
                pass

        # Zaman Damgası Ayrıştırma
        t_val = c.get("time")
        dt_val = t_val if isinstance(t_val, datetime) else datetime.fromisoformat(str(t_val)) if t_val else None
        parsed_timestamps.append((i, dt_val, c))

    # 4. Zaman Damgası Sıralama & Mükerrer Kayıt Kontrolü
    for k in range(1, len(parsed_timestamps)):
        idx_prev, dt_prev, c_prev = parsed_timestamps[k - 1]
        idx_curr, dt_curr, c_curr = parsed_timestamps[k]

        if dt_prev is None or dt_curr is None:
            continue

        diff = (dt_curr - dt_prev).total_seconds()

        # Sıra dışı / Azalan Zaman Damgası
        if diff < 0:
            report.out_of_order_timestamps += 1
            report.anomalies.append(
                CandleAnomaly(
                    idx_curr, str(dt_curr), "OUT_OF_ORDER_TIMESTAMP",
                    f"Ters zaman sıralaması: {dt_curr} < {dt_prev}", QualityCheckStatus.FAIL
                )
            )
        # Mükerrer Zaman Damgası
        elif diff == 0:
            report.duplicate_timestamps += 1
            ohlc_prev = (c_prev.get("open"), c_prev.get("high"), c_prev.get("low"), c_prev.get("close"))
            ohlc_curr = (c_curr.get("open"), c_curr.get("high"), c_curr.get("low"), c_curr.get("close"))
            if ohlc_prev != ohlc_curr:
                report.conflicting_duplicates += 1
                report.anomalies.append(
                    CandleAnomaly(
                        idx_curr, str(dt_curr), "CONFLICTING_DUPLICATE",
                        f"Aynı zaman damgasında çelişkili OHLC: {ohlc_curr} vs {ohlc_prev}", QualityCheckStatus.FAIL
                    )
                )
            else:
                report.anomalies.append(
                    CandleAnomaly(
                        idx_curr, str(dt_curr), "EXACT_DUPLICATE",
                        "Birebir mükerrer mum", QualityCheckStatus.WARNING
                    )
                )
        # Gecikme / Zaman Dilimi Kontrolü
        elif report.expected_timeframe_seconds and report.expected_timeframe_seconds > 0:
            tf = report.expected_timeframe_seconds
            if abs(diff - tf) < 1.0:
                report.normal_intervals += 1
            else:
                missing_bars = int(round(diff / tf)) - 1
                if missing_bars < 0:
                    missing_bars = 0
                
                # Hafta sonu / Seans tatili ayrımı (Örn. > 48 saat)
                if diff > 48 * 3600:
                    cat = IntervalType.LARGE_GAP
                    report.large_gaps += 1
                else:
                    cat = IntervalType.IRREGULAR
                    report.irregular_intervals += 1

                report.total_estimated_missing_bars += missing_bars
                report.gaps.append(
                    GapInfo(
                        previous_index=idx_prev,
                        previous_timestamp=str(dt_prev),
                        next_index=idx_curr,
                        next_timestamp=str(dt_curr),
                        observed_delta_seconds=diff,
                        expected_delta_seconds=tf,
                        estimated_missing_bars=missing_bars,
                        category=cat,
                    )
                )
                if cat == IntervalType.IRREGULAR and missing_bars > 0:
                    report.anomalies.append(
                        CandleAnomaly(
                            idx_curr, str(dt_curr), "SUSPICIOUS_GAP",
                            f"Şüpheli intra-session boşluğu: {missing_bars} mum eksik", QualityCheckStatus.WARNING
                        )
                    )

    # 5. Aşırı Fiyat Sapmaları Teşhisi (Aşırı Genişlik / Sıçrama Uarıları)
    if len(ranges) >= 10:
        sorted_ranges = sorted(ranges)
        median_range = sorted_ranges[len(sorted_ranges) // 2]
        if median_range > 0:
            for idx, r in enumerate(ranges):
                if r > extreme_range_factor * median_range:
                    report.anomalies.append(
                        CandleAnomaly(
                            idx, str(candles[idx].get("time", "")), "EXTREME_RANGE_WARNING",
                            f"Aşırı mum aralığı: {r:.4f} (medyan {median_range:.4f} x {extreme_range_factor})",
                            QualityCheckStatus.WARNING
                        )
                    )

    if len(jumps) >= 10:
        sorted_jumps = sorted(jumps)
        median_jump = sorted_jumps[len(sorted_jumps) // 2]
        if median_jump > 0:
            for idx, j_val in enumerate(jumps):
                if j_val > extreme_jump_factor * median_jump:
                    report.anomalies.append(
                        CandleAnomaly(
                            idx + 1, str(candles[idx + 1].get("time", "")), "EXTREME_JUMP_WARNING",
                            f"Aşırı kapanış sıçraması: {j_val:.4f} (medyan {median_jump:.4f} x {extreme_jump_factor})",
                            QualityCheckStatus.WARNING
                        )
                    )

    # Genel Durum Değerlendirmesi
    has_fails = (
        report.missing_fields > 0 or
        report.invalid_numeric_values > 0 or
        report.ohlc_violations > 0 or
        report.conflicting_duplicates > 0 or
        report.out_of_order_timestamps > 0 or
        any(a.severity == QualityCheckStatus.FAIL for a in report.anomalies)
    )

    has_warnings = (
        any(a.severity == QualityCheckStatus.WARNING for a in report.anomalies) or
        report.irregular_intervals > 0 or
        report.duplicate_timestamps > 0
    )

    if has_fails:
        report.status = QualityCheckStatus.FAIL
    elif has_warnings:
        report.status = QualityCheckStatus.WARNING if allow_warning else QualityCheckStatus.FAIL
    else:
        report.status = QualityCheckStatus.PASS

    return report
