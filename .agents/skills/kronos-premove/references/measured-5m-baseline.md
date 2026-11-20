# Measured baseline — Binance 5m, 2026-10-18

Frozen record of the run that produced the current FAIL verdict. Any future
change must beat **this** table, on the same gates, to be taken seriously.

## Run configuration

| | |
|---|---|
| model | `NeoQuasar/Kronos-mini` |
| tokenizer | `NeoQuasar/Kronos-Tokenizer-2k` |
| `max_context` | 2048 |
| interval | `5m` |
| bars per symbol | 3000 |
| lookback → horizon | 400 bars → 24 bars |
| stride | 12 |
| `sample_count` | 1 |
| device | CPU, no GPU |
| round-trip fee | 0.20% |
| window | 2026-10-08 09:35 → 2026-10-18 19:55 |
| symbols | BTCUSDT, ETHUSDT, SOLUSDT, DOGEUSDT, LINKUSDT, AVAXUSDT |
| artifacts | `_kronos_lab_5m.json`, `_kronos_accuracy.md`, `_kronos_verdict.md` |

215 windows per symbol → **1290 total**. Cost: ~0.8 s/window (164–205 s per symbol).

## Forecast error per symbol

| symbol | windows | MAPE % | pred/actual return corr |
|---|---|---|---|
| BTCUSDT | 215 | 0.263 | +0.072 |
| ETHUSDT | 215 | 0.383 | −0.085 |
| SOLUSDT | 215 | 0.507 | −0.027 |
| DOGEUSDT | 215 | 0.474 | +0.135 |
| LINKUSDT | 215 | 0.607 | −0.094 |
| AVAXUSDT | 215 | 0.687 | +0.027 |

MAPE is small in absolute terms but the return correlations straddle zero — the
forecast tracks the price level without predicting its direction.

## Gate A — directional accuracy (pooled, n = 1290)

| horizon (bars) | Kronos | momentum | verdict |
|---|---|---|---|
| 1 | 0.5248 | 0.4760 | fail |
| 3 | 0.4992 | 0.4581 | fail |
| 6 | 0.5062 | 0.4930 | fail |
| 12 | 0.4977 | 0.4667 | fail |
| 24 | 0.5155 | 0.4752 | fail |

Every horizon is a coin flip (0.498–0.525), and **momentum is itself below 0.50
at every horizon**, so "Kronos beats momentum" is meaningless here.

## Gate B — pre-move detection (pooled)

| event | base rate | AUC Kronos | AUC momentum | **AUC volatility** |
|---|---|---|---|---|
| +1% | 14.5% | 0.6273 | 0.4131 | **0.7495** |
| +2% | 2.95% | 0.6565 | 0.4646 | **0.7780** |
| +3% | 1.30% | 0.5984 | 0.4713 | **0.8330** |

`auc_model` equals `auc_model_trapz` to four decimals at every event, which
confirms the AUC implementation is consistent.

**The volatility control wins at every event size, and the gap grows with move
size.** Trailing realised volatility predicts a coming +3% move at 0.833 versus
Kronos's 0.598. The model's apparent pre-move skill is volatility exposure.

## Gate C — payoff after fees (optimistic)

Top-10% flagged windows versus all windows, per event:

| event | flagged mean move | unconditional mean move | margin over fee |
|---|---|---|---|
| +1% | 0.7515% | 0.5405% | +0.011% |
| +2% | 0.7515% | 0.5405% | +0.011% |
| +3% | 0.8042% | 0.5876% | +0.017% |

Technically clears, but the margin is ~0.01% — an order of magnitude below noise,
and the metric is the maximum favourable excursion (perfect exit assumed). **This
is not evidence of edge.** It is recorded here so nobody later mistakes the
"PASS" on C for a reason to trade.

## Verdict

```
A. Directional  FAIL
B. Pre-move     FAIL   (volatility 0.75–0.83 beats Kronos 0.60–0.66)
C. Payoff       marginal, optimistic metric
OVERALL         FAIL — do not wire Kronos into the entry path
```

Run to reproduce: `scripts/measure.py ... --verdict` (exit code 1).

## What would change this

Allowed to change the answer, but only on evidence:

1. A **different timeframe**. The trigger labs showed 1h and 4h carry real signal
   on some variants — but sign-flipping between halves, i.e. regime dependence.
   Test 1h/4h before assuming 5m is representative.
2. A **larger sample**. 1290 overlapping windows is not 1290 independent bets.
3. **Finetuning** on this market — but the vendored trainers are multi-GPU
   `torchrun`, CPU finetuning of `Kronos-small` is days-long, and any finetune must
   clear zero-shot Kronos *and* the volatility control out-of-sample.
4. **Higher `sample_count`** (forecast ensembling), which the paper reports buys
   more than model size, at a fraction of the cost.

Not allowed to change the answer: raising `sample_count` alone without re-measuring,
quoting a vendor's accuracy claim (see `vendor\Kronos\RELATED.md` — one popular
community project's advertised benchmark file is an unfilled placeholder), or
citing a blended multi-indicator accuracy number as proof about Kronos.
