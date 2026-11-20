# Kronos pre-move verdict — FAIL

- source: `_kronos_lab_5m.json`
- model: `NeoQuasar/Kronos-mini` + `NeoQuasar/Kronos-Tokenizer-2k`
- interval: `5m` · lookback 400 → pred_len 24 · stride 12 · sample_count 1
- round-trip fee: **0.2%**

A change may only be wired into the entry path if the verdict is **PASS**.
A missing field fails its gate; silence is never a pass.

## A. Directional — FAIL

| h (bars) | model acc | momentum acc | pass | why |
|---|---|---|---|---|
| 1 | 0.5248 | 0.4760 | no | acc 0.5248 < 0.55; momentum 0.4760 is worse than a coin flip, so beating it counts for nothing |
| 12 | 0.4977 | 0.4667 | no | acc 0.4977 < 0.55; momentum 0.4667 is worse than a coin flip, so beating it counts for nothing |
| 24 | 0.5155 | 0.4752 | no | acc 0.5155 < 0.55; momentum 0.4752 is worse than a coin flip, so beating it counts for nothing |
| 3 | 0.4992 | 0.4581 | no | acc 0.4992 < 0.55; momentum 0.4581 is worse than a coin flip, so beating it counts for nothing |
| 6 | 0.5062 | 0.4930 | no | acc 0.5062 < 0.55; momentum 0.4930 is worse than a coin flip, so beating it counts for nothing |

## B. Pre-move detection — FAIL

| event | AUC model | AUC momentum | AUC volatility | pass | why |
|---|---|---|---|---|---|
| move1 | 0.6273 | 0.4131 | 0.7495 | no | volatility control 0.7495 is at least as good |
| move2 | 0.6565 | 0.4646 | 0.7780 | no | volatility control 0.7780 is at least as good |
| move3 | 0.5984 | 0.4713 | 0.8330 | no | auc 0.5984 < 0.6; volatility control 0.8330 is at least as good |

## C. Payoff after fees (optimistic metric) — PASS

| event | flagged mean move | unconditional mean move | pass | why |
|---|---|---|---|---|
| move1 | 0.7515% | 0.5405% | yes | ok |
| move2 | 0.7515% | 0.5405% | yes | ok |
| move3 | 0.8042% | 0.5876% | yes | ok |

> Gate C is measured on the **maximum favourable excursion** inside the horizon, so it assumes a perfect exit at the high. Read it as a ceiling on what the flags could ever pay, never as realised edge — and a thin margin (under ~0.05%) is noise. This is why C alone cannot carry a PASS.

## Decision

**Do not wire Kronos into the entry path on this evidence.** Leave the hunter's gate where it is and keep hunting on the measured, explainable filters.
