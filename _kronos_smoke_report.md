# Kronos pre-move accuracy — measured, not assumed

Every number below is from real Binance spot klines through the vendored Kronos model on CPU. `sample_count` averages stochastic forecast paths. A round-trip fee of 0.20% is stated so a gross edge can be judged as tradeable or not.


## 5m — NeoQuasar/Kronos-mini / NeoQuasar/Kronos-Tokenizer-2k

- file: `_kronos_smoke.json`
- lookback 400 bars → forecast 24 bars, stride 24, max_context 2048, sample_count 1, fee 0.2%
- symbols: 1

| symbol | windows | MAPE % | dir@1 | pred/act corr |
|---|---|---|---|---|
| BTCUSDT | 15 | 0.201 | 0.533 | -0.362 |

### Directional accuracy by horizon (pooled)

| horizon | n | Kronos | momentum | beats momentum? |
|---|---|---|---|---|
| 1 bars | 15 | 0.5333 | 0.6000 | no |
| 3 bars | 15 | 0.6000 | 0.4667 | yes |
| 6 bars | 15 | 0.6667 | 0.6000 | yes |
| 12 bars | 15 | 0.6000 | 0.6667 | no |
| 24 bars | 15 | 0.4000 | 0.6000 | no |


## How to read this

- Anything near 0.50 AUC or near the momentum column is **noise**, not a signal.
- A pre-move signal is only worth wiring into an engine if it beats momentum *and* volatility, holds up out-of-sample, and clears the 0.20% round-trip fee.
- Base rate is the share of windows that actually moved; lift over it is the only reason to bother.
