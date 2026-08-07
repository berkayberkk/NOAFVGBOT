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

from strategy.config import DEFAULT_CONFIG, StrategyConfig

# --- Kalibre edilecek parametreler ---
MIN_LEVEL_TOUCH_COUNT = DEFAULT_CONFIG.min_level_touch_count


@dataclass
class Trade:
    signal: Signal
    entry_index: int
    exit_index: int | None = None
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    filled: bool = False
    entry_fill_index: int | None = None
    executed_entry: float = 0.0
    executed_exit: float | None = None
    exit_price: float | None = None
    won: bool | None = None
    gross_r_multiple: float | None = None
    net_r_multiple: float | None = None
    r_multiple: float | None = None       # net_r_multiple ile özdeş (geriye dönük uyumluluk)


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    win_rate: float = 0.0
    total_r: float = 0.0
    avg_r: float = 0.0
    max_drawdown_r: float = 0.0
    skipped_no_tp: int = 0     # uygun S/R hedefi bulunamadığı için atlanan sinyal sayısı
    unfilled_orders: int = 0   # limit seviyesine ulaşılamadığı için dolmayan emir sayısı


def _find_take_profit(entry: float, direction: SignalType, levels, signal_index: int, min_level_touch_count: int = 2) -> float | None:
    """Sinyal anına kadar oluşmuş, yeterince güçlü, doğru taraftaki en yakın seviyeyi bulur."""
    candidates = [
        lvl for lvl in levels
        if lvl.touch_count >= min_level_touch_count and lvl.last_index <= signal_index
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


def run_backtest(candles: list[dict], signals: list[Signal], config: StrategyConfig = DEFAULT_CONFIG) -> BacktestResult:
    """
    Sinyalleri geçmiş veri üzerinde limit-emir dolum gerçekçiliği ve işlem maliyetleri ile simüle eder.
    """
    trades: list[Trade] = []
    skipped = 0
    unfilled = 0

    half_spread = config.spread / 2.0
    slippage = config.slippage
    commission = config.commission

    for signal in signals:
        historical_candles = candles[: signal.index + 1]
        historical_levels = build_levels(historical_candles, config=config)
        take_profit = _find_take_profit(signal.entry, signal.type, historical_levels, signal.index, min_level_touch_count=config.min_level_touch_count)
        if take_profit is None:
            skipped += 1
            continue

        trade = Trade(signal=signal, entry_index=signal.index, entry_price=signal.entry,
                      stop_loss=signal.stop_loss, take_profit=take_profit)

        risk = abs(trade.entry_price - trade.stop_loss)
        if risk == 0:
            skipped += 1
            continue

        is_filled = False

        for j in range(signal.index + 1, len(candles)):
            candle = candles[j]

            # 1. EMİR DOLUM KONTROLÜ (Henüz dolmadıysa)
            if not is_filled:
                if signal.type == SignalType.BUY:
                    candle_ask_low = candle["low"] + half_spread
                    candle_ask_open = candle["open"] + half_spread
                    if candle_ask_low <= signal.entry:
                        is_filled = True
                        trade.filled = True
                        trade.entry_fill_index = j
                        better_price = min(signal.entry, candle_ask_open)
                        trade.executed_entry = min(signal.entry, better_price + slippage)
                else:
                    candle_bid_high = candle["high"] - half_spread
                    candle_bid_open = candle["open"] - half_spread
                    if candle_bid_high >= signal.entry:
                        is_filled = True
                        trade.filled = True
                        trade.entry_fill_index = j
                        better_price = max(signal.entry, candle_bid_open)
                        trade.executed_entry = max(signal.entry, better_price - slippage)

                if not is_filled:
                    continue  # Bu mumda emir dolmadı, sonraki muma geç

                # Giriş mumundaki (j) çıkış kontrolü (Aynı mumda dolum + çıkış karmaşası)
                if signal.type == SignalType.BUY:
                    bid_low = candle["low"] - half_spread
                    hit_sl = bid_low <= trade.stop_loss
                else:
                    ask_high = candle["high"] + half_spread
                    hit_sl = ask_high >= trade.stop_loss

                if hit_sl:
                    # Giriş mumunda SL vuruldusa kötümser kabul et ve kapat
                    trade.exit_index, trade.exit_price, trade.won = j, trade.stop_loss, False
                    if signal.type == SignalType.BUY:
                        trade.executed_exit = trade.stop_loss - half_spread - slippage
                        gross_pnl = trade.executed_exit - trade.executed_entry
                    else:
                        trade.executed_exit = trade.stop_loss + half_spread + slippage
                        gross_pnl = trade.executed_entry - trade.executed_exit

                    net_pnl = gross_pnl - commission
                    trade.gross_r_multiple = gross_pnl / risk
                    trade.net_r_multiple = net_pnl / risk
                    trade.r_multiple = trade.net_r_multiple
                    break
                else:
                    # Giriş mumunda TP vurulmuş olsa dahi yol sırası belirsiz olduğu için
                    # aynı mumda iyimser TP kabul etme, sonraki mumlara bırak.
                    continue

            # 2. POZİSYON ÇIKIŞ KONTROLÜ (Daha önceki bir mumda dolmuşsa)
            if signal.type == SignalType.BUY:
                bid_low = candle["low"] - half_spread
                bid_high = candle["high"] - half_spread
                hit_sl = bid_low <= trade.stop_loss
                hit_tp = bid_high >= trade.take_profit
            else:
                ask_high = candle["high"] + half_spread
                ask_low = candle["low"] + half_spread
                hit_sl = ask_high >= trade.stop_loss
                hit_tp = ask_low <= trade.take_profit

            if hit_sl:
                trade.exit_index, trade.exit_price, trade.won = j, trade.stop_loss, False
                if signal.type == SignalType.BUY:
                    trade.executed_exit = trade.stop_loss - half_spread - slippage
                    gross_pnl = trade.executed_exit - trade.executed_entry
                else:
                    trade.executed_exit = trade.stop_loss + half_spread + slippage
                    gross_pnl = trade.executed_entry - trade.executed_exit

                net_pnl = gross_pnl - commission
                trade.gross_r_multiple = gross_pnl / risk
                trade.net_r_multiple = net_pnl / risk
                trade.r_multiple = trade.net_r_multiple
                break

            if hit_tp:
                trade.exit_index, trade.exit_price, trade.won = j, trade.take_profit, True
                if signal.type == SignalType.BUY:
                    trade.executed_exit = trade.take_profit - half_spread - slippage
                    gross_pnl = trade.executed_exit - trade.executed_entry
                else:
                    trade.executed_exit = trade.take_profit + half_spread + slippage
                    gross_pnl = trade.executed_entry - trade.executed_exit

                net_pnl = gross_pnl - commission
                trade.gross_r_multiple = gross_pnl / risk
                trade.net_r_multiple = net_pnl / risk
                trade.r_multiple = trade.net_r_multiple
                break

        if trade.r_multiple is not None:
            trades.append(trade)
        else:
            if not is_filled:
                unfilled += 1
            else:
                skipped += 1  # Doldu fakat veri bittiği için kapanamadı

    return _summarize(trades, skipped, unfilled)


def _summarize(trades: list[Trade], skipped: int, unfilled: int = 0) -> BacktestResult:
    if not trades:
        return BacktestResult(trades=trades, skipped_no_tp=skipped, unfilled_orders=unfilled)

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
                          avg_r=avg_r, max_drawdown_r=max_dd, skipped_no_tp=skipped,
                          unfilled_orders=unfilled)


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
