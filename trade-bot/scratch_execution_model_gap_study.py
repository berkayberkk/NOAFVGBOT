"""
Audit takip maddesi (Bulgu #1): backtest'in resmi dolum modeli, giris fiyatini
`executed_entry = min(signal.entry, better_price + slippage)` ile HER ZAMAN
signal.entry'den daha kotu olamayacak sekilde sinirliyor -- bu, GERCEK bir
bekleyen LIMIT emrinin davranisi. Ama canli EA (TradeBot_NOA_Recal.mq5)
pending limit emri KULLANMIYOR, tetiklenince market emriyle aciliyor --
market emri, tetiklenen tick'te mevcut olan fiyati alir, signal.entry'den
DAHA KOTU de olabilir (normal/gap-siz dokunuslarda bile).

Bu script, ayni backtest mantigini (ayni sinyaller, ayni SL/TP/breakeven)
SADECE giris tarafindaki bu "asla kotu olamaz" sinirlamasini KALDIRARAK
(market-emri gibi, slippage'i giriste de exit'teki gibi simetrik uygulayarak)
yeniden kosar ve resmi motorla karsilastirir. MEVCUT resmi motor
(backtest/engine.py) DEGISTIRILMEDI -- bu sadece bir olcum/karsilastirma.

GUNCELLEME (2026-09-07): bu scriptin olcup raporladigi market-emri modeli
artik resmi motora (backtest/engine.py) benimsendi -- `run_backtest_market_
order_variant` burada artik SADECE tarihsel/referans amacli duruyor, resmi
`run_backtest` ile ayni sonucu uretir (bkz. backtest/engine.py giris dolum
blogundaki 2026-09-07 notu, tests/test_backtest_engine.py'deki guncellenmis
beklenen degerler).
"""
import copy

from scratch_module_diagnostic_full_scan import load_symbol_m30
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals, SignalType
from backtest.engine import run_backtest, Trade, MAX_GAP_FILL_RISK_MULTIPLE

SPREAD = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}
# Temsili market-emri kaymasi (slippage) -- proje'nin spread icin yaptigi gibi
# ("temsili, henuz kalibre edilmedi") kucuk ama sifir-olmayan bir deger.
# GOLD/BTCUSD/EURGBP icin kendi spread'lerinin ~%20'si kadar secildi.
SLIPPAGE = {"GOLD": 0.05, "BTCUSD": 4.0, "EURGBP": 0.00004}


def run_backtest_market_order_variant(candles, signals, config):
    """run_backtest ile AYNI mantik, TEK fark: executed_entry'nin
    signal.entry'den daha kotu OLAMAYACAGI sinirlamasi (min/max cap)
    KALDIRILDI -- market emri gercekci simetrik slippage."""
    trades = []
    skipped = 0
    unfilled = 0
    half_spread = config.spread / 2.0
    slippage = config.slippage
    commission = config.commission

    from strategy.support_resistance import build_levels
    from backtest.engine import _find_take_profit

    for signal in signals:
        if signal.take_profit is not None:
            take_profit = signal.take_profit
        else:
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

        use_breakeven = signal.breakeven_trigger_pct is not None
        effective_sl = trade.stop_loss
        armed = False
        if use_breakeven:
            trigger_pct = signal.breakeven_trigger_pct
            if signal.type == SignalType.BUY:
                arm_level = trade.entry_price + trigger_pct * (trade.take_profit - trade.entry_price)
            else:
                arm_level = trade.entry_price - trigger_pct * (trade.entry_price - trade.take_profit)

        is_filled = False
        for j in range(signal.index + 1, len(candles)):
            candle = candles[j]
            if not is_filled:
                if signal.invalid_after_index is not None and j > signal.invalid_after_index:
                    break
                if signal.type == SignalType.BUY:
                    candle_ask_low = candle["low"] + half_spread
                    candle_ask_open = candle["open"] + half_spread
                    if candle_ask_low <= signal.entry:
                        is_filled = True
                        trade.filled = True
                        trade.entry_fill_index = j
                        # MARKET EMRI VARYANTI: cap YOK -- gap varsa open'dan,
                        # yoksa entry seviyesinden, HER IKI durumda da slippage
                        # UYGULANIR (exit'teki gibi simetrik).
                        market_price = min(signal.entry, candle_ask_open)
                        trade.executed_entry = market_price + slippage
                else:
                    candle_bid_high = candle["high"] - half_spread
                    candle_bid_open = candle["open"] - half_spread
                    if candle_bid_high >= signal.entry:
                        is_filled = True
                        trade.filled = True
                        trade.entry_fill_index = j
                        market_price = max(signal.entry, candle_bid_open)
                        trade.executed_entry = market_price - slippage

                if not is_filled:
                    continue

                if risk > 0 and abs(trade.executed_entry - signal.entry) > risk * MAX_GAP_FILL_RISK_MULTIPLE:
                    is_filled = False
                    trade.filled = False
                    trade.entry_fill_index = None
                    trade.executed_entry = 0.0
                    continue

                if signal.type == SignalType.BUY:
                    bid_low = candle["low"] - half_spread
                    hit_sl = bid_low <= trade.stop_loss
                else:
                    ask_high = candle["high"] + half_spread
                    hit_sl = ask_high >= trade.stop_loss

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
                else:
                    continue

            if signal.type == SignalType.BUY:
                bid_low = candle["low"] - half_spread
                bid_high = candle["high"] - half_spread
                hit_sl = bid_low <= effective_sl
                hit_tp = bid_high >= trade.take_profit
            else:
                ask_high = candle["high"] + half_spread
                ask_low = candle["low"] + half_spread
                hit_sl = ask_high >= effective_sl
                hit_tp = ask_low <= trade.take_profit

            if hit_sl:
                trade.exit_index, trade.exit_price, trade.won = j, effective_sl, False
                trade.is_breakeven = armed
                if signal.type == SignalType.BUY:
                    trade.executed_exit = effective_sl - half_spread - slippage
                    gross_pnl = trade.executed_exit - trade.executed_entry
                else:
                    trade.executed_exit = effective_sl + half_spread + slippage
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

            if use_breakeven and not armed:
                reached_arm = (bid_high >= arm_level) if signal.type == SignalType.BUY else (ask_low <= arm_level)
                if reached_arm:
                    armed = True
                    effective_sl = trade.entry_price

        if trade.r_multiple is not None:
            trades.append(trade)
        else:
            if not is_filled:
                unfilled += 1
            else:
                skipped += 1

    return trades, skipped, unfilled


for sym in ["GOLD", "BTCUSD", "EURGBP"]:
    candles = load_symbol_m30(sym)
    config = StrategyConfig(spread=SPREAD[sym], slippage=SLIPPAGE[sym])
    all_signals = generate_signals(candles, config=config)

    official = run_backtest(candles, all_signals, config=config)
    off_trades = official.trades
    off_n = len(off_trades)
    off_total = sum(t.r_multiple for t in off_trades) if off_trades else 0.0
    off_exp = off_total / off_n if off_n else 0.0

    variant_trades, _, _ = run_backtest_market_order_variant(candles, all_signals, config)
    var_n = len(variant_trades)
    var_total = sum(t.r_multiple for t in variant_trades) if variant_trades else 0.0
    var_exp = var_total / var_n if var_n else 0.0

    print(f"=== {sym} (slippage={SLIPPAGE[sym]}) ===")
    print(f"  RESMI (limit-emri gibi, cap'li):   n={off_n:>5} total_R={off_total:+9.2f} exp_R={off_exp:+.4f}")
    print(f"  MARKET-EMRI VARYANTI (cap'siz):     n={var_n:>5} total_R={var_total:+9.2f} exp_R={var_exp:+.4f}")
    if off_n:
        print(f"  FARK: total_R {var_total-off_total:+.2f}  ({(var_total-off_total)/abs(off_total)*100 if off_total else float('nan'):+.1f}%% resmi sonuca gore)")
    print(flush=True)

print("TAMAMLANDI")
