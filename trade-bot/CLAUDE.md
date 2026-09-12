# NOAFVGBOT — Trade-Bot Branch

MT5 algo-trading research project. MQL5 EA (`TradeBot_NOA_MultiSymbol.mq5`) +
Python research/backtest stack for a Smart Money Concepts signal engine.
This `trade-bot/` folder is the active branch — the repo root above it
(loose `.mq5`/`.ex5` files) is legacy/staging, not the current focus.

## Strategy modules (`strategy/`)

Four independent signal modules, combined in `signal_engine.py`:
- **FVG** — `fvg.py` (3-candle Fair Value Gap detection)
- **iFVG** — `ifvg.py` (inverse/mitigated FVG)
- **Order Block** — `order_block.py`
- **Trendline** — `trendline.py`

Plus supporting filters: `session.py` (London/NY kill-zones), `trend.py`
(EMA 50/200), `zone.py`, `support_resistance.py`. Config/parameters live
in `config.py`.

## Kept symbols

Universe was pruned down to **GOLD, BTCUSD, EURGBP** after scanning a
much larger symbol list (see `scanner/`, `module_diagnostic_full_*` results).
Everything else was screened out.

## Current research status (as of 2026-09-07 holdout run)

**No robust, regime-independent edge has been found yet.**

- Official "sacred holdout v2" run (`final_holdout.py`, held-out 20%) came
  back **RED FLAG**: GOLD +0.0827R (validated but fragile, maxDD 89R),
  BTCUSD -0.0817R (**failed to generalize**), EURGBP -0.2375R (**failed
  to generalize**, maxDD 1096R).
- Confluence between FVG/iFVG/OrderBlock alone has ~zero edge on its
  own — the earlier "confluence works" result was a Simpson's-paradox
  artifact almost entirely driven by Trendline participation (~10.8% of
  the population), not a real interaction between the other three.
- **Live trading readiness: NO.** Only GOLD shows a weak, fragile signal.
- A visual trade-review panel (`webapp/`, `phase_b_charts/`,
  `scratch_phase_b_render.py`) is in progress to manually inspect trades
  rather than rely on aggregate stats alone.

## Where to look for detail

- `NOA_KONSEPTI_KAYNAK_ANALIZI.md` — narrative/decision history only
  (large file, don't re-derive experiment numbers from it)
- `NOA_RESEARCH_LEDGER.md` — **source of truth for experiment details**,
  per-experiment results tables, ongoing work
- Both files are append-only running logs — check the tail for latest
  state, don't assume earlier sections still apply.

## Hard rule observed throughout the project

Never change `config.py` parameters based on a single measurement
without re-validating through the independent holdout
(`backtest/final_holdout.py`). This was violated implicitly in the
past (SL-buffer tuning on train/val only) and contributed to the
2026-09-07 red flag — treat holdout results as the only thing that can
green-light a parameter change.

## Execution model note

Live EA uses **MARKET orders**, not pending limits, on signal trigger.
The backtest fill model (`backtest/engine.py`) was corrected on
2026-09-06/07 to reflect this (slippage is now applied unconditionally
and symmetrically, no longer capped at the limit price) — the
SPREAD/SLIPPAGE constants are still flagged as "representative, not yet
calibrated" against real broker/EA data.
