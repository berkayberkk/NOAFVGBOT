# Experiment Policy

This policy governs every research experiment run in this project —
backtests, walk-forward runs, and (later) machine learning experiments. It
exists to prevent overfitting, hindsight bias, and misleading result
reporting from creeping into the research process.

## Every Experiment Must Start With a Written Hypothesis

Before running an experiment, write down what is being tested and why. An
experiment without a prior hypothesis is exploratory data dredging, and must
be labeled as such — it cannot be reported as a confirmatory result.

## Data Version Must Be Recorded

Every experiment must record the exact version/snapshot of the data it used
(see `data/metadata/`), so results can be reproduced or invalidated if the
underlying data pipeline changes later.

## Strategy Version Must Be Recorded

Every experiment must record the exact strategy code version (e.g., a Git
commit hash) it ran against. Strategy logic must not silently change between
runs being compared.

## Cost Assumptions Must Be Recorded

Every experiment must record the spread, commission, and slippage
assumptions used, since these materially affect reported performance and
must be auditable.

## Parameters Must Be Recorded

Every parameter value used in an experiment (strategy parameters, risk
parameters, filters) must be recorded alongside the result — no implicit or
"whatever was in the file at the time" parameters.

## Train, Validation, and Test Periods Must Be Recorded

Every experiment must record its exact train/validation/test date ranges.
Splits must be time-ordered (train precedes validation precedes test) —
**random train/test splitting for time-series data is prohibited**, per
[../CLAUDE.md](../CLAUDE.md).

## Failed Experiments Must Not Be Deleted

Experiments that fail to show an edge, or that reveal a bug, must remain in
the experiment registry (`experiments/registry/`) rather than being deleted.
A visible history of failures is required to judge whether a later "success"
is real or the product of repeated retries.

## Untouched Test Data Must Not Be Repeatedly Reused

Once a test period has been used to evaluate a candidate strategy, it is
considered spent for that research line. Reusing the same test period
repeatedly across parameter tweaks turns it into a second validation set and
invalidates its purpose — this is prohibited.

## No Cherry-Picking

Results must be reported for all runs in an experiment line, not just the
best-performing configuration. Selecting only favorable runs for reporting
is prohibited.

## No Undocumented Parameter Search

Any parameter sweep or optimization must be declared as such up front (as
part of the hypothesis), with the full search space and search method
documented — not retrofitted as "the parameters we chose" after the fact.

## No Reporting Only the Best Result

Summaries and reports must include the distribution of results across an
experiment line (e.g., all folds of a walk-forward run), not solely the
single best fold or configuration.

## Experiment ID and Git Commit Hash Requirements

Every experiment must be assigned a unique experiment ID and must record the
Git commit hash of the codebase used to run it, stored in
`experiments/registry/`.

## Reproducibility Requirements

- Experiments must be deterministic given the same data version, code
  version, parameters, and configuration (fixed random seeds where
  randomness is used).
- Any experiment that cannot be reproduced from its recorded metadata is
  considered invalid and must be re-run or discarded (not reported as a
  result).
