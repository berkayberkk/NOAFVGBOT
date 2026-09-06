"""
Audit takip maddesi: Order Block modulunun R-multiple dagiliminda "fat tail"
(birkac asiri islemin toplam R'yi surukleyip suruklemedigi) kontrolu.
Duzeltilmis motorla (2026-09-04 sonrasi) KEPT_SYMBOLS icin kosulur.
"""
import time
import statistics

from scratch_module_diagnostic_full_scan import load_symbol_m30
from strategy.config import StrategyConfig
from strategy.signal_engine import generate_signals, SetupType
from backtest.engine import run_backtest

SPREAD = {"GOLD": 0.25, "BTCUSD": 20.0, "EURGBP": 0.00020}

for sym in ["GOLD", "BTCUSD", "EURGBP"]:
    t0 = time.time()
    candles = load_symbol_m30(sym)
    print(f"{sym}: {len(candles)} mum yuklendi ({time.time()-t0:.1f}s)", flush=True)

    t1 = time.time()
    config = StrategyConfig(spread=SPREAD[sym])
    all_signals = generate_signals(candles, config=config)
    ob_signals = [s for s in all_signals if s.setup_type == SetupType.OB_ONLY]
    print(f"{sym}: {len(ob_signals)} OB sinyali ({time.time()-t1:.1f}s)", flush=True)

    t2 = time.time()
    result = run_backtest(candles, ob_signals, config=config)
    print(f"{sym}: backtest tamam ({time.time()-t2:.1f}s)", flush=True)

    rs = sorted(t.r_multiple for t in result.trades if t.r_multiple is not None)
    n = len(rs)
    total = sum(rs)
    if n == 0 or total == 0:
        print(f"{sym}: islem yok veya total_R=0, atlaniyor")
        continue
    top5 = rs[-5:]
    top10 = rs[-10:]
    top5sum = sum(top5)
    top10sum = sum(top10)
    print(f"{sym}: n={n} total_R={total:.2f} win%={result.win_rate*100:.1f}")
    print(f"  en yuksek 5 R: {[round(x,2) for x in top5]}")
    print(f"  top5/total_R = {top5sum/total*100:.1f}%%   top10/total_R = {top10sum/total*100:.1f}%%")
    print(f"  medyan R={statistics.median(rs):.3f}  n(R>0)={sum(1 for x in rs if x>0)}  n(R>3)={sum(1 for x in rs if x>3)}  n(R>10)={sum(1 for x in rs if x>10)}")
    print(f"  total_R HARIC top5: {total-top5sum:.2f}  (top5 cikarilinca sistem hala pozitif mi: {(total-top5sum)>0})")
    print(flush=True)

print("TAMAMLANDI")
