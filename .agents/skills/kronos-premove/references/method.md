# Method — how these numbers are produced, and how to read them

## The question, stated so it can be falsified

"We can catch a token before it pumps." A falsifiable version: *conditioned on
Kronos's forecast, the probability of an upward move of at least X% within the
next H bars is materially higher than the unconditional rate, and the difference
survives a 0.20% round trip.*

Everything below is in service of that one sentence.

## Data

Real Binance spot klines over public REST (`api.binance.com`, with
`data-api.binance.vision` as fallback). No key, no vendor, no synthetic series.
Klines are paged backwards until the requested bar count is filled, de-duplicated
on open time, and sorted ascending.

## Walk-forward, not a single split

For each symbol the harness anchors at bar `t`, feeds exactly the `lookback` bars
that ended at `t-1` into the model, and compares the forecast against the
`pred_len` bars that actually followed at `t`. Anchors step by `stride`, so
consecutive windows overlap; that is intentional and it is why the *count* of
windows is not the count of independent bets (see "Reading rules").

There is no shuffling and no fitting: the model never sees the bars it is scored
against. This is a pure forecast test.

## Metrics

**Forecast error.** MAPE between the predicted and actual close path, plus the
Pearson correlation between predicted and actual h-bar return. A model can have
low MAPE and still be useless directionally — it just tracks the last price — so
MAPE alone is never evidence.

**Directional accuracy at h ∈ {1,3,6,12,24} bars.** Compared against two controls:

* *majority base rate* — always predicting the more common outcome;
* *momentum* — predicting the sign of the trailing h-bar return.

**Pre-move detection.** For an event defined as "the high reached at least X%
above the entry price within the horizon" (X ∈ {1,2,3}), the model's
`predicted_max_up` is used as a score and scored by rank-based ROC-AUC, plus
precision@top-10%, lift over base rate, and the mean move of flagged windows
versus all windows.

## The controls are the whole point

Three controls run on the same windows as the model:

| Control | What it represents |
|---|---|
| base rate | no skill at all |
| momentum | the cheapest possible trend rule |
| **volatility** | trailing realised volatility of the same window |

A result is only interesting if it beats **momentum** and **volatility**
simultaneously. This matters because a prior finding in this project was that a
structural filter performed no better than *no filter* — a filter that matches
the control is a filter that does nothing.

**Momentum's own score is informative.** In the measured baseline momentum scores
0.41–0.47, i.e. *worse than a coin flip*, because trailing momentum mean-reverts at
these horizons. Beating a broken baseline proves nothing, which is why gate A
refuses to count it.

**Volatility is the real bar.** Volatility predicts upward moves at AUC
0.75–0.83 versus Kronos's 0.60–0.66. High volatility precedes large moves in both
directions; "this is about to move" is not "this is about to move **up**". A model
that only ranks volatility has rediscovered a one-line indicator.

## The fee arithmetic

`FEE_ROUND_TRIP = 0.20%`, matching `signals.FEE_ROUND_TRIP`. On a plan whose stop
sits 0.4% away, the fee alone is **50% of the risk** — that framing comes from the
trigger labs and it is why tight-stop designs die regardless of signal quality.

Kronos's MAPE is 0.26–0.69% per symbol at 5m. A forecast error of the same order
as the typical move it is meant to predict is not a basis for an entry.

## Ambiguity, look-ahead and other honest compromises

- When one bar spans both the stop and the target, the ledger resolves it as the
  **stop**. This is pessimistic on purpose: it is the only safe assumption when
  intrabar order is unknown.
- Windows overlap (stride 12 over a 24-bar horizon), so the pooled `n` overstates
  independent evidence. Treat pooled counts as indicative, not as a sample size.
- Gate C is measured on the **maximum favourable excursion**, so it assumes an
  exit at the exact high. It is a ceiling, not an expectation.
- Agreement between `auc_model` (rank based) and `auc_model_trapz` (trapezoidal
  integration of the ROC curve) is a consistency check on the AUC implementation.

## Reading rules

1. A single horizon clearing gate A is not a pass — every gate must clear.
2. A sign that flips between in-sample and out-of-sample halves is **regime
   dependence**, not edge. The earlier trigger labs showed exactly that pattern.
3. Anything under `n ≈ 300` independent windows is a smoke test, not a verdict.
4. The threshold for acting is the fee, not zero. A positive but sub-fee edge is a
   losing strategy.
5. Report the control that beat the model, every time. Hiding it is how a
   measurement tool becomes a marketing tool.
