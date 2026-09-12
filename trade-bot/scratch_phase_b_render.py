"""
FAZ B -- gorsel inceleme icin PNG montaj uretici (scratch, kalici degil).

webapp/visual_review.py:build_review() FONKSIYONUNU DOGRUDAN cagirir --
ayri/paralel bir tespit/backtest mantigi YOK, sadece panelin ZATEN
urettigi veriyi (gercek detect_*/generate_signals/run_backtest ciktisi)
matplotlib ile PNG'ye cizip Claude'un (tarayici olmadan) gozle
inceleyebilmesini saglar. Panelin kendisini DEGISTIRMEZ.
"""
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

TRADE_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TRADE_BOT_DIR, "webapp"))
os.chdir(TRADE_BOT_DIR)
import visual_review as vr

OUT_DIR = os.path.join(TRADE_BOT_DIR, "phase_b_charts")
os.makedirs(OUT_DIR, exist_ok=True)


def find_bar_index(candles, iso_time):
    if not iso_time:
        return -1
    t = datetime.fromisoformat(iso_time)
    best, best_diff = -1, None
    for i, c in enumerate(candles):
        diff = abs((datetime.fromisoformat(c["t"]) - t).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff, best = diff, i
    return best


def draw_candles(ax, candles):
    hi = max(c["h"] for c in candles)
    lo = min(c["l"] for c in candles)
    min_body = (hi - lo) * 0.002 or 1e-6
    for i, c in enumerate(candles):
        color = "#3ecf8e" if c["c"] >= c["o"] else "#f0556b"
        ax.plot([i, i], [c["l"], c["h"]], color=color, linewidth=0.8, zorder=2)
        top, bot = max(c["o"], c["c"]), min(c["o"], c["c"])
        ax.add_patch(mpatches.Rectangle((i - 0.3, bot), 0.6, max(top - bot, min_body), color=color, zorder=3))
    ax.set_xlim(-1, len(candles))


def plot_example(ax, ex):
    candles = ex["candles"]
    draw_candles(ax, candles)
    if ex.get("zone"):
        z = ex["zone"]
        ax.axhspan(z["bottom"], z["top"], color="orange", alpha=0.15, zorder=1)
    if ex.get("entry") is not None:
        ax.axhline(ex["entry"], color="#4f8cff", linestyle="--", linewidth=0.7)
        ax.axhline(ex["sl"], color="#c0304a", linestyle="--", linewidth=0.7)
        ax.axhline(ex["tp"], color="#2a9d6b", linestyle="--", linewidth=0.7)
        entry_idx = find_bar_index(candles, ex.get("entry_fill_time") or ex["signal_time"])
        if entry_idx >= 0:
            marker = "^" if ex["direction"] == "BUY" else "v"
            ax.plot(entry_idx, ex["entry"], marker=marker, color="#245bd6", markersize=7, zorder=4)
    else:
        sig_idx = find_bar_index(candles, ex["signal_time"])
        if sig_idx >= 0:
            ax.plot(sig_idx, candles[sig_idx]["c"], marker="x", color="#c98a1f", markersize=8, mew=2, zorder=4)

    r = ex.get("r_multiple")
    r_txt = f"{r:+.2f}R" if r is not None else (ex.get("invalid_reason") or "")
    st = ex["signal_time"][:16].replace("T", " ") if ex.get("signal_time") else "?"
    title = f'{ex["outcome"]} {ex["direction"]} {r_txt}\nidx={ex["signal_index"]} {st}'
    ax.set_title(title, fontsize=6.5)
    ax.tick_params(labelsize=5)


def render_grid(examples, title, path, ncols=4):
    n = len(examples)
    if n == 0:
        return False
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 3.3, nrows * 2.6))
    axes = axes.flatten() if n > 1 else [axes]
    for i, ex in enumerate(examples):
        plot_example(axes[i], ex)
    for j in range(n, len(axes)):
        axes[j].axis("off")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return True


TARGETS = [
    ("GOLD", "trendline"), ("BTCUSD", "trendline"),
    ("GOLD", "ob"), ("BTCUSD", "ob"),
    ("GOLD", "fvg"), ("BTCUSD", "fvg"),
    ("GOLD", "ifvg"), ("BTCUSD", "ifvg"),
]


def main():
    for symbol, module in TARGETS:
        print(f"=== {symbol} {module} ===", flush=True)
        data = vr.build_review(symbol, "M30", module, outcome_filter=None, limit=500, offset=0)
        if "error" in data:
            print("  HATA:", data["error"], flush=True)
            continue
        examples = data["examples"]
        wins = [e for e in examples if e["outcome"] == "win"]
        losses = [e for e in examples if e["outcome"] == "loss"]
        invalids = [e for e in examples if e["outcome"] == "invalid"]
        print(f"  havuz={len(examples)} win={len(wins)} loss={len(losses)} invalid={len(invalids)} "
              f"(toplam gercek n={data['aggregate']['n']}, consistency={data['consistency']['match']})", flush=True)
        render_grid(wins[:16], f"{symbol} {module} KAZANAN (havuzda {len(wins)})", f"{OUT_DIR}/{symbol}_{module}_win.png")
        render_grid(losses[:16], f"{symbol} {module} KAYBEDEN (havuzda {len(losses)})", f"{OUT_DIR}/{symbol}_{module}_loss.png")
        if invalids:
            render_grid(invalids[:16], f"{symbol} {module} GECERSIZ (havuzda {len(invalids)})", f"{OUT_DIR}/{symbol}_{module}_invalid.png")
    print("\nTAMAMLANDI", flush=True)


if __name__ == "__main__":
    main()
