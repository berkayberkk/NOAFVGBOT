"""
Backtest motoru.

signal_engine'den gelen sinyalleri geçmiş veri üzerinde simüle edip
performans metrikleri üretir.

Take-profit kuralı: eğer sinyal KENDİ take_profit'ini bildirdiyse (bkz.
`strategy/signal_engine.py` -- FVG/iFVG/OB/Trendline artık kendi resmi
R-katı hedeflerini burada hesaplayıp `Signal.take_profit`'e yazıyor)
DOĞRUDAN o kullanılır. Bildirmediyse (eski/harici bir sinyal kaynağı,
`take_profit=None`), eski davranışa (en yakın karşı yöndeki güçlü
Destek/Direnç seviyesi) düşülür -- sadece sinyal anına kadar
(lookahead bias olmasın diye) oluşmuş seviyeler dikkate alınır, uygun
bir S/R seviyesi bulunamazsa o sinyal backtest'e dahil edilmez.

Breakeven-stop: sinyal `breakeven_trigger_pct` bildirdiyse (bkz.
`strategy/config.py:BREAKEVEN_TRIGGER_PCT`/`BREAKEVEN_ENABLED_MODULES`),
işlem TP mesafesinin bu oranını kat ettiğinde SL girişe çekilir --
nedensellik korunuyor: bir barın SL/TP kontrolü hep ÖNCEKİ bardan kalma
efektif SL ile yapılır, "yeni bar bu barin kendi hareketiyle arm oldu"
hiçbir zaman AYNI barda SL/TP sonucunu etkilemez (bkz. bu oturumun
scratch script'lerindeki aynı desen, örn. scratch_trade_archive.py).

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

# 2026-09-04 GECESİ BULUNAN HATA -- sinyaller süresiz beklediği için (bkz. bu
# oturumun web paneli/mql5 EA tasarımı), bazen fiyat tarihi bir şokla (ör.
# CHFJPY: 2015-01-15 SNB EUR/CHF sabitlemesinin kaldırılması, ~13 puanlık TEK
# BARLIK sıçrama) sinyalin `entry`'sini fersah fersah aşarak dolduruyordu.
# `executed_entry` bu sıçramaya göre güncelleniyordu ama `risk` (=|signal.entry
# - stop_loss|) HÂLÂ sinyalin ESKİ, hiç gerçekleşmemiş entry'sine göre
# hesaplanıyordu -- bu da r_multiple'ı yüzlerce kata şişiriyordu (CHFJPY'de
# +413R, BTCUSD'de +85R'ye kadar görüldü) VE aynı-bar SL kontrolü artık
# executed_entry'den anlamsız derecede uzak kalan eski stop_loss'a göre
# yanlış tetiklenip gerçekte kârlı olan hareketi "kayıp" (won=False) sayıyordu.
# Düzeltme: dolum fiyatı, sinyalin kendi (küçük, dar) riskine göre asırı
# sapmışsa (bu esik degerin ustundeyse), o dolum GECERSIZ sayilir -- sahte bir
# R uydurmak yerine (ki bu projenin "causal correctness, no fake numbers"
# disipliniyle celisir), sinyal o barda hic dolmamis gibi davranilir ve
# taramaya sonraki bardan devam edilir (fiyat sok sonrasi eski seviyeye
# donmediyse, sinyal dogal olarak "unfilled" kalir -- gercekci sonuc).
MAX_GAP_FILL_RISK_MULTIPLE = 3.0


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
    is_breakeven: bool = False             # SL, TP'ye giderken girişe çekilip sonra vuruldu mu (won=False ama gerçek zarar değil)


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

        # Breakeven-stop durumu (bkz. modul docstring'i) -- effective_sl,
        # armed OLANA kadar trade.stop_loss ile ayni; arm oldugunda
        # trade.entry_price'e cekilir. arm_level, TP mesafesinin
        # breakeven_trigger_pct'i kat edildiginde asilan seviye.
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

                # ASIRI SICRAMA KONTROLÜ (2026-09-04 bulgusu -- bkz. MAX_GAP_FILL_RISK_MULTIPLE
                # yorumu): dolum fiyatı sinyalin kendi riskine göre saçma derecede uzaksa
                # (tarihi bir gap/şok sinyali süresiz beklerken vurmuş demektir), bu dolum
                # GEÇERSİZ sayılır -- risk/stop_loss artık executed_entry'ye göre anlamsız
                # kaldığından sağlıklı bir R hesaplanamaz. Sinyal bu barda hiç dolmamış gibi
                # davranılır, taramaya sonraki bardan devam edilir.
                if risk > 0 and abs(trade.executed_entry - signal.entry) > risk * MAX_GAP_FILL_RISK_MULTIPLE:
                    is_filled = False
                    trade.filled = False
                    trade.entry_fill_index = None
                    trade.executed_entry = 0.0
                    continue

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
            # NOT: hit_sl/hit_tp bu barin ONCEKI bardan kalma effective_sl'iyle
            # kontrol ediliyor -- bu barin kendi arm-kontrolu asagida, ancak
            # bu iki kontrolden SONRA yapiliyor (bir sonraki bar icin).
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

            # 3. BREAKEVEN ARM KONTROLÜ -- ne SL ne TP vurulduysa, bu barin
            # KENDI lehte hareketi arm seviyesini gectiyse effective_sl bir
            # SONRAKI bardan itibaren girise cekilir (bu barin SL/TP kontrolu
            # zaten YUKARIDA, eski effective_sl ile yapildi -- geriye donuk
            # etkisi yok).
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
