# Kronos pre-move accuracy — measured, not assumed

Every number below is from real Binance spot klines through the vendored Kronos model on CPU. `sample_count` averages stochastic forecast paths. A round-trip fee of 0.20% is stated so a gross edge can be judged as tradeable or not.


## 5m — NeoQuasar/Kronos-mini / NeoQuasar/Kronos-Tokenizer-2k

- file: `_kronos_lab_5m.json`
- lookback 400 bars → forecast 24 bars, stride 12, max_context 2048, sample_count 1, fee 0.2%
- symbols: 6

| symbol | windows | MAPE % | dir@1 | pred/act corr |
|---|---|---|---|---|
| BTCUSDT | 215 | 0.263 | 0.577 | 0.072 |
| ETHUSDT | 215 | 0.383 | 0.530 | -0.085 |
| SOLUSDT | 215 | 0.507 | 0.516 | -0.027 |
| DOGEUSDT | 215 | 0.474 | 0.558 | 0.135 |
| LINKUSDT | 215 | 0.607 | 0.493 | -0.094 |
| AVAXUSDT | 215 | 0.687 | 0.474 | 0.027 |

### Directional accuracy by horizon (pooled)

| horizon | n | Kronos | momentum | beats momentum? |
|---|---|---|---|---|
| 1 bars | 1290 | 0.5248 | 0.4760 | yes |
| 3 bars | 1290 | 0.4992 | 0.4581 | yes |
| 6 bars | 1290 | 0.5062 | 0.4930 | yes |
| 12 bars | 1290 | 0.4977 | 0.4667 | yes |
| 24 bars | 1290 | 0.5155 | 0.4752 | yes |

> Note: where the momentum column sits below 0.50 it is *worse than a coin flip*, so "beating momentum" is not evidence of skill. The volatility control is the bar that actually matters.
### Pre-move detection (pooled) — can it SEE the move coming?

Event = the forward high reaches +X% within the forecast horizon. AUC 0.50 = coin flip. The score must beat momentum and volatility.

| event | n | base rate | AUC Kronos | AUC momentum | AUC volatility |
|---|---|---|---|---|---|
| +1% | 1290 | 0.1450 | 0.6273 | 0.4131 | 0.7495 |
| +2% | 1290 | 0.0295 | 0.6565 | 0.4646 | 0.7780 |
| +3% | 1075 | 0.0130 | 0.5984 | 0.4713 | 0.8330 |

**Verdict per event:**

- `move1`: **NO EDGE — baselines match or beat it** (AUC 0.6273)
- `move2`: **NO EDGE — baselines match or beat it** (AUC 0.6565)
- `move3`: **NO EDGE — baselines match or beat it** (AUC 0.5984)


## How to read this

- Anything near 0.50 AUC or near the momentum column is **noise**, not a signal.
- A pre-move signal is only worth wiring into an engine if it beats momentum *and* volatility, holds up out-of-sample, and clears the 0.20% round-trip fee.
- Base rate is the share of windows that actually moved; lift over it is the only reason to bother.
