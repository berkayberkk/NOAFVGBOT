"""
Backtest motoru.

signal_engine'den gelen sinyalleri geçmiş veri üzerinde simüle edip
performans metrikleri üretir.

Take-profit kuralı: en yakın karşı yöndeki güçlü Destek/Direnç seviyesi.
- BUY sinyali için: entry'nin üstündeki en yakın RESISTANCE seviyesi.
- SELL sinyali için: entry'nin altındaki en yakın SUPPORT seviyesi.
Sadece sinyal anına kadar (lookahead bias olmasın diye) oluşmuş
seviyeler dikkate alınır. Uygun bir S/R seviyesi bulunamazsa o sinyal
backtest'e dahil edilmez (TP'siz işlem açılmaz).

Sonuç R-multiple (risk biriminin katları) cinsinden ölçülür: her
işlemin kazancı/kaybı, o işlemin riskine (entry-stop_loss mesafesine)
oranlanır. Böylece farklı büyüklükteki TP'ler (S/R'ye göre değiştiği
için) adil şekilde karşılaştırılabilir.
"""

from dataclasses import dataclass, field

from strategy.signal_engine import Signal, SignalType, generate_signals
from strategy.support_resistance import build_levels, LevelType


# --- Kalibre edilecek parametreler ---
MIN_LEVEL_TOUCH_COUNT = 2   # TP hedefi olarak kullanılacak S/R seviyesinin en az kaç kez dokunulmuş olması gerektiği


@dataclass
class Trade:
    signal: Signal
    entry_index: int
    exit_index: int | None = None
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_price: float | None = None
    won: bool | None = None
    r_multiple: float | None = None       # kazanç/kayıp, risk biriminin katı olarak


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    win_rate: float = 0.0
    total_r: float = 0.0
    avg_r: float = 0.0
    max_drawdown_r: float = 0.0
    skipped_no_tp: int = 0     # uygun S/R hedefi bulunamadığı için atlanan sinyal sayısı


def _find_take_profit(entry: float, direction: SignalType, levels, signal_index: int) -> float | None:
    """Sinyal anına kadar oluşmuş, yeterince güçlü, doğru taraftaki en yakın seviyeyi bulur."""
    candidates = [
        lvl for lvl in levels
        if lvl.touch_count >= MIN_LEVEL_TOUCH_COUNT and lvl.last_index <= signal_index
    ]

    if direction == SignalType.BUY:
        above = [lvl for lvl in candidates if lvl.type == LevelType.RESISTANCE and lvl.price > entry]
        if not above:
            return None
        return min(above, key=lambda lvl: lvl.price - entry).price
    else:
        below = [lvl for lvl in candidates if lvl.type == LevelType.SUPPORT and lvl.price < entry]
        if not below:
            return None
        return min(below, key=lambda lvl: entry - lvl.price).price


def run_backtest(candles: list[dict], signals: list[Signal]) -> BacktestResult:
    """
    Sinyalleri geçmiş veri üzerinde simüle eder.

    Emir yönetimi kuralı: her mumda önce stop-loss kontrol edilir
    (aynı mumda hem SL hem TP'ye değinildiyse kötümser/muhafazakâr
    varsayımla önce SL'in vurulduğu kabul edilir), sonra take-profit.
    """
    levels = build_levels(candles)
    trades: list[Trade] = []
    skipped = 0

    for signal in signals:
        take_profit = _find_take_profit(signal.entry, signal.type, levels, signal.index)
        if take_profit is None:
            skipped += 1
            continue

        trade = Trade(signal=signal, entry_index=signal.index, entry_price=signal.entry,
                      stop_loss=signal.stop_loss, take_profit=take_profit)

        risk = abs(trade.entry_price - trade.stop_loss)
        if risk == 0:
            skipped += 1
            continue

        for j in range(signal.index + 1, len(candles)):
            candle = candles[j]

            if signal.type == SignalType.BUY:
                hit_sl = candle["low"] <= trade.stop_loss
                hit_tp = candle["high"] >= trade.take_profit
            else:
                hit_sl = candle["high"] >= trade.stop_loss
                hit_tp = candle["low"] <= trade.take_profit

            if hit_sl:
                trade.exit_index, trade.exit_price, trade.won = j, trade.stop_loss, False
                trade.r_multiple = -1.0
                break
            if hit_tp:
                trade.exit_index, trade.exit_price, trade.won = j, trade.take_profit, True
                reward = abs(trade.take_profit - trade.entry_price)
                trade.r_multiple = reward / risk
                break

        if trade.r_multiple is not None:
            trades.append(trade)
        else:
            skipped += 1  # islem hicbir zaman kapanmadi (veri bitti)

    return _summarize(trades, skipped)


def _summarize(trades: list[Trade], skipped: int) -> BacktestResult:
    if not trades:
        return BacktestResult(trades=trades, skipped_no_tp=skipped)

    wins = [t for t in trades if t.won]
    win_rate = len(wins) / len(trades)
    total_r = sum(t.r_multiple for t in trades)
    avg_r = total_r / len(trades)

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        equity += t.r_multiple
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return BacktestResult(trades=trades, win_rate=win_rate, total_r=total_r,
                           avg_r=avg_r, max_drawdown_r=max_dd, skipped_no_tp=skipped)


def print_report(result: BacktestResult) -> None:
    """Backtest sonuçlarını okunaklı şekilde ekrana basar."""
    print(f"Toplam işlem: {len(result.trades)}  (atlanan: {result.skipped_no_tp})")
    if not result.trades:
        print("Hiç işlem tamamlanmadı.")
        return
    print(f"Win rate: {result.win_rate * 100:.1f}%")
    print(f"Toplam R: {result.total_r:.2f}")
    print(f"Ortalama R/işlem: {result.avg_r:.2f}")
    print(f"Maksimum drawdown: {result.max_drawdown_r:.2f}R")

    from collections import Counter
    by_setup = Counter(t.signal.setup_type.value for t in result.trades)
    print(f"Setup dağılımı: {dict(by_setup)}")
