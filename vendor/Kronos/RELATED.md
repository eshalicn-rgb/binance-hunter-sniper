# Kronos — Related Artfacts, Ecosystem & Fit Assessment

Scope: evidence for deciding whether/how to use the vendored Kronos model inside
`binance_hunter` as a Binance spot **pre-move hunter**. All counts below were measured on
**2026-10-18** via `api.github.com`, `huggingface.co/api/models`, and `raw.githubusercontent.com`.
Nothing here is estimated; where a number could not be verified it is marked **unverified**.

---

## 1. Official artefacts

### Source repos

| Artefact | URL | Measured |
|---|---|---|
| Kronos (vendored upstream) | https://github.com/shiyu-coder/Kronos | **41,061 stars**, 6,847 forks, 282 open issues, MIT, created 2025-07-01, last push 2026-10-18 |
| Kronos live demo | https://github.com/shiyu-coder/Kronos-demo | **145 stars**, 63 forks (GitHub Pages demo, BTC/USDT 24h forecast) |
| Paper | https://arxiv.org/abs/2508.02739 | arXiv 2508.02739v1, q-fin.ST, 2 Aug 2025; README says accepted at AAAI 2026 |
| WindFM (separate project, same authors) | https://github.com/shiyu-coder/WindFM | **117 stars**, 16 forks, MIT — homepage of the HF weights below |

### Model zoo (HuggingFace)

Context length / params as published in the upstream README table; downloads and likes measured live.

| Model | HF repo | Tokenizer | Context | Params | Downloads | Likes |
|---|---|---|---|---|---|---|
| Kronos-mini | [NeoQuasar/Kronos-mini](https://huggingface.co/NeoQuasar/Kronos-mini) | Kronos-Tokenizer-2k | 2048 | 4.1M | **431,892** | 33 |
| Kronos-small | [NeoQuasar/Kronos-small](https://huggingface.co/NeoQuasar/Kronos-small) | Kronos-Tokenizer-base | 512 | 24.7M | **1,166,466** | 42 |
| Kronos-base | [NeoQuasar/Kronos-base](https://huggingface.co/NeoQuasar/Kronos-base) | Kronos-Tokenizer-base | 512 | 102.3M | **712,868** | 288 |
| Kronos-large | — | Kronos-Tokenizer-base | 512 | 499.2M | not released | — |
| Kronos-Tokenizer-base | [NeoQuasar/Kronos-Tokenizer-base](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-base) | — | — | — | **2,420,632** | 102 |
| Kronos-Tokenizer-2k | [NeoQuasar/Kronos-Tokenizer-2k](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-2k) | — | — | — | **405,868** | 12 |
| WindFM | [NeoQuasar/WindFM](https://huggingface.co/NeoQuasar/WindFM) | WindFM-Tokenizer | n/p | n/p | **1,093** | 2 |
| WindFM-Tokenizer | [NeoQuasar/WindFM-Tokenizer](https://huggingface.co/NeoQuasar/WindFM-Tokenizer) | — | — | — | **1,141** | 1 |
| WindFM-robust | [NeoQuasar/WindFM-robust](https://huggingface.co/NeoQuasar/WindFM-robust) | WindFM-Tokenizer-robust | n/p | n/p | **141** | 2 |
| WindFM-Tokenizer-robust | [NeoQuasar/WindFM-Tokenizer-robust](https://huggingface.co/NeoQuasar/WindFM-Tokenizer-robust) | — | — | — | **160** | 1 |

Every HF card carries `license: mit` and `arxiv:2508.02739`.

**What WindFM is:** from its GitHub description it is *"WindFM: An Open-Source Foundation
Model for Zero-Shot Wind Power Forecasting"* — a **wind-power**, not financial, foundation
model by the same group. The HF cards are near-empty ("Regarding how to use this model,
please refer to this GitHub repository"), so parameter counts and context length are
**unverified**. The `-robust` variants are documented on their cards: *"The model supports
prediction when some covariates are missing. When a covariate is missing, set all values of
that variable to 0."* → **WindFM is irrelevant to a crypto pre-move hunter.** Noted for
completeness (same author namespace, easy to confuse in a `NeoQuasar` listing).

---

## 2. What actually ships in the vendored repo (verified on disk)

| Path | What it is | Notes for us |
|---|---|---|
| `model/kronos.py`, `model/module.py` | `Kronos`, `KronosTokenizer`, `KronosPredictor` (RoPE / MHA / BSQuantizer) | `predict(df, x_timestamp, y_timestamp, pred_len, T, top_p, sample_count)`; also `predict_batch` |
| `webui/` | Flask UI + CORS + Plotly, port **7070** (confirmed in `webui/app.py:708`, `run.py:82`, `start.sh:36`, `webui/README.md:36`) | Browser tool for eyeballing forecasts. Fixed 400+120 window slider; CPU/CUDA/MPS. Not a trading component. |
| `finetune/` | Qlib pipeline: `qlib_data_preprocess.py`, `train_tokenizer.py`, `train_predictor.py`, `qlib_test.py`, `config.py`, `dataset.py` | Needs `pyqlib`; multi-GPU `torchrun`; A-share **daily** example. Heaviest path. |
| `finetune_csv/` | CSV pipeline: `finetune_tokenizer.py`, `finetune_base_model.py`, `train_sequential.py`, `config_loader.py`, `configs/`, `data/HK_ali_09988_kline_5min_all.csv` | **The easier path.** Ships a real **5-min** config: `lookback_window: 512`, `predict_window: 48`, `max_context: 512`, `tokenizer_epochs: 30`, `basemodel_epochs: 20`, `batch_size: 32`, predictor LR `1e-6`. Required CSV cols: `timestamps, open, high, low, close, volume, amount`. |
| `tests/test_kronos_regression.py` + `tests/data/` | Recorded regression fixtures: `regression_input.csv` (147 KB), `regression_output_256.csv`, `regression_output_512.csv`; ctx `[512, 256]`, `pred_len=8`, `REL_TOLERANCE=1e-5`; plus MSE fixtures `[0.008979, 0.003741]`; pinned revisions `MODEL_REVISION=901c26c1…`, `TOKENIZER_REVISION=0e011738…`, `DEVICE="cpu"` | **This is the free correctness gate.** Deterministic CPU test that proves our vendored copy matches upstream numerics — run it before trusting any signal. |
| `examples/run_backtest_kronos.py` | `KronosBacktester` class (capital, data_dir, model_dir) | Simple internal backtest harness, not a cost model. |
| `requirements.txt` | numpy, pandas, `torch>=2.0`, einops 0.8.1, huggingface_hub 0.33.1, matplotlib 3.9.3, pandas 2.2.2, tqdm, safetensors 0.6.2 | No CUDA-specific pins → CPU install is clean. |

---

## 3. Community projects applying Kronos to crypto

| Project | Stars | Approach | Worth borrowing |
|---|---|---|---|
| [Billkst/Crypto-Pilot](https://github.com/Billkst/Crypto-Pilot) | 4 | Binance **1h** OHLCV via ccxt → **Kronos-base** CPU → 24h forecast → threshold signal engine; Streamlit; L2 disk cache; Plotly | The clean layered layout (`data_feed` / `model_engine` / `strategy`) and honest FAQ. States 488+24=512 as a "hard model constraint". Its `docs/BENCHMARK.md` **contains no number** — it is an unfilled placeholder ("基准报告尚未生成"), and `docs/V1_SUMMARY.md` marks `accuracy_pct` as "**[后填]**" (to be filled). So its "direction accuracy" claim is **unverified**. Also states: *"Never use predictions as sole trading basis."* |
| [niranjanniru-max/crowdwisdom-crypto-agent](https://github.com/niranjanniru-max/crowdwisdom-crypto-agent) | 2 | **Kronos-mini + Tokenizer-2k, `max_context=2048`**, 1000×1m candles; two modes: `direct_5min` (predict 5 bars) and `stacked_1min` (5 sequential 1m, majority vote); Kelly sizing (half-Kelly) + RSI/MACD + LLM sentiment + Markov regime filter; **scores every prediction after the 5-min window** | Per-prediction correctness tracking is the single best idea here — copy the feedback loop. Reports BTC 61.8% over 65 self-scored predictions (small n, and *not* a pure-Kronos figure — it is a blended signal). `stacked_1min` scored ~50% overall, i.e. **no better than a coin flip**. Treat both as unverified self-reports. |
| [Itsalanbrahh/CryptoOracle](https://github.com/Itsalanbrahh/CryptoOracle) | 1 | **13-agent** ensemble (Kronos + Macro + Micro/order-book + Volume + OnChain + Sentiment + Technical) → Claude synthesis → BUY/SELL/HOLD; Alpaca paper/live; SQLite + FastAPI + React; self-adjusting agent weights | The *weighting* idea: boost agents that called the last 2 moves right, cut the ones wrong. Useful as an architecture **only if** you first prove Kronos alone has edge — otherwise you are averaging noise. Requires Anthropic + Alpaca keys (~$90–140/mo). |
| [Boom-Caoq/KronosAiCrypto](https://github.com/Boom-Caoq/KronosAiCrypto) | 4 | Chinese-language fork; Binance API → per-symbol/per-interval CSVs → Flask API layer split from a webui frontend; explicitly **drops GPU for CPU mode to trade speed for stability**; supports concurrent requests | The API/frontend split and the explicit CPU trade-off note. Says auto-trading/backtest "后期将会" (planned later) — **not implemented**, so it is a prediction viewer, not a strategy. |
| [yaohongrui/Kronos-for-crypto](https://github.com/yaohongrui/Kronos-for-crypto) | 9 | "优化后的kronos"; Binance **futures** klines, drops incomplete candles, multi-coin/multi-timeframe, TP/SL visualisation, multi-sample prediction + stats (example: BTCUSDT 15m) | The "drop the incomplete last candle" data-hygiene step, and multi-sample statistics. Its author's own caveats are blunt: *"关键位置方向指示准确度较高"* (direction at key levels is fairly accurate) but *"模型结果仅供参考"* (results are reference only), *"不要扛单"* (do not hold losers) and *"TP/SL看看就好，自己可以改"* (treat TP/SL as indicative). |
| [abhijatchaturvedi/FineForecast](https://github.com/abhijatchaturvedi/FineForecast) | 3 | **QLoRA on a frozen 4-bit Kronos-base** on NSE OHLCV → **MASTER-style market-conditioned cross-attention gating head** → rank Nifty-500 → long–short deciles; walk-forward splits; explicit per-trade **cost model (brokerage + spread + sqrt impact)** | Best *methodology* reference of the set even though the market is equities: frozen backbone + adapters + a separate ranking head; ablations incl. **zero-shot vs fine-tuned Kronos**; RankIC/ICIR metrics. Licence is **Proprietary (personal use)** — read for ideas, do not vendor code. |

---

## 4. The authors' own caveats (verbatim, from the upstream README)

Section: **"🔧 Finetuning on Your Own Data (A-Share Market Example)"**.

> **Disclaimer:** This pipeline is intended as a demonstration to illustrate the finetuning process. It is a simplified example and not a production-ready quantitative trading system. A robust quantitative strategy requires more sophisticated techniques, such as portfolio optimization and risk factor neutralization, to achieve stable alpha.

Section: **"💡 From Demo to Production: Important Considerations"**.

> **Raw Signals vs. Pure Alpha**: The signals generated by the model in this demo are raw predictions. In a real-world quantitative workflow, these signals would typically be fed into a portfolio optimization model. This model would apply constraints to neutralize exposure to common risk factors (e.g., market beta, style factors like size and value), thereby isolating the **"pure alpha"** and improving the strategy's robustness.

> **Strategy and Backtesting Complexity**: The simple top-K strategy used here is a basic starting point. Production-level strategies often incorporate more complex logic for portfolio construction, dynamic position sizing, and risk management (e.g., stop-loss/take-profit rules). Furthermore, a high-fidelity backtest should meticulously model transaction costs, slippage, and market impact to provide a more accurate estimate of real-world performance.

Also in that section (relevant to trusting `finetune/` code):

> **📝 AI-Generated Comments**: Please note that many of the code comments within the `finetune/` directory were generated by an AI assistant (Gemini 2.5 Pro) for explanatory purposes. While they aim to be helpful, they may contain inaccuracies.

### Paper's own reported results (arXiv abstract, reached)

> On benchmark datasets, Kronos boosts price series forecasting RankIC by 93% over the leading TSFM and 87% over the best non-pre-trained baseline. It also achieves a 9% lower MAE in volatility forecasting and a 22% improvement in generative fidelity for synthetic K-line sequences.

> pre-train Kronos using an autoregressive objective on a massive, multi-market corpus of over **12 billion K-line records from 45 global exchanges**

Named baselines found in the paper body: **Chronos** (Ansari et al.), **iTransformer** (Liu et al.), plus continuous-space baselines **Direct-AR** (MSE) and **Prob-AR**. The paper also reports — importantly — *"a consistent improvement in both IC and RankIC as more samples are included in the ensemble"*, which is the justification for `sample_count` averaging.

**Caveat on the headline number:** the 93%/87% figures are **RankIC** gains on a *cross-sectional ranking* benchmark, i.e. relative ordering across many instruments. They are **not** single-symbol directional accuracy and do **not** transfer directly to "will BTC go up in the next 5 minutes".

---

## 5. Recommendation

Target box: **CPU-only Windows, 16 GB RAM, 12 threads**, Binance spot, 5m–1h pre-move hunter.

**Model to start with: `Kronos-small` + `Kronos-Tokenizer-base`, `max_context=512`.**
- `Kronos-base` (102.3M) is ~4× the compute of small for the same 512 context; on a CPU-only box that is the difference between usable and painful latency. It is also what most untested community forks use.
- `Kronos-mini` (4.1M) looks cheaper but runs the **2048-ctx Tokenizer-2k**; attention and token count scale with context, so the parameter saving does not translate into the lowest CPU latency. Mini is nonetheless the *fallback* if `small` is too slow, and it is what the only project that scored every prediction actually ran.
- Upgrade to `base` only if `small` shows measurable edge **and** the latency budget still fits the hunting cadence.

**Lookback / pred_len (respecting the ceilings).**
- Upstream README: *"The `max_context` for `Kronos-small` and `Kronos-base` is 512… recommended that your input data length (i.e. `lookback`) does not exceed this limit"* → treat **512 as the lookback ceiling**; the predictor truncates longer input.
- Note the honest discrepancy: `Billkst/Crypto-Pilot` reads the window as **lookback + pred_len ≤ 512** (488+24). The README wording points at *lookback* for `max_context`; the reference example uses `lookback=400, pred_len=120` (sum 520) with `max_context=512`. **Do not assume the sum rule** — measure it, and keep `lookback + pred_len ≤ 512` as the conservative default until measured otherwise.
- Concrete starting points: **5m** → lookback 400, pred_len 24 (2h horizon); **1h** → lookback 400, pred_len 12 (12h). Only reach for `Kronos-mini`+2k when you actually need >512 bars of 5m history (2048 bars ≈ 7 days) — otherwise the extra context buys nothing.
- Always `T=1.0, top_p=0.9`, and raise `sample_count` before raising model size — the paper reports IC/RankIC improving monotonically with ensembles.

**Finetuning on crypto 5m: not yet — later, and never as the first step.**
- The only in-repo crypto-shaped recipe is `finetune_csv/configs/config_ali09988_candle-5min.yaml` (512/48, tokenizer 30 epochs + predictor 20 epochs, batch 32), and the trainers are built for **multi-GPU `torchrun`**. On 12 CPU threads a full tokenizer+predictor finetune of `small` (let alone `base`) is days of compute with no way to know if it helped until you already have a validation harness.
- `finetune/config.py` defaults to Comet logging you don't want (`use_comet = False`).
- Do it in the right order: **(a)** freeze, zero-shot, `sample_count` averaging; **(b)** build the validation harness in §5-checkpoint below; **(c)** only if zero-shot clears every baseline but still leaves money on the table, finetune — and then follow FineForecast's shape (frozen backbone + small trainable adapters/gating head) rather than full-parameter training. `FineForecast` explicitly ablates zero-shot vs fine-tuned Kronos; copy that comparison.
- The authors' own words govern: the pipeline is *"a demonstration… not a production-ready quantitative trading system"*.

**Minimum honest validation before any signal is trusted.** A Kronos signal must beat *all* of these on the **same bars, out-of-sample, after costs**:

1. **Random / coin-flip (50%)** — the null. Test with a binomial test, p < 0.05.
2. **Always-up / majority class** — spot crypto drifts; a model that is never short can look "right" for free.
3. **Naive persistence** — `sign(next_close − close)` ≈ `sign(last_return)`. Cheap and surprisingly hard to beat on 5m bars.
4. **One trivial technical baseline** on identical bars (e.g. RSI/MACD crossover, or 20-bar momentum) — if a two-line indicator matches Kronos, the model adds nothing.
5. **Zero-shot Kronos itself** — this is the baseline any finetune must beat; if finetuning does not beat zero-shot, do not ship it.

Metric and protocol requirements: (i) use **IC / RankIC** as the model's own reported metric, not only directional accuracy; (ii) report directional accuracy **with n ≥ 500 non-overlapping windows and a confidence interval** — no n=3 or n=65 anecdotes; (iii) **walk-forward with purge/embargo**, zero lookahead, no scaler fitted across the split; (iv) the PnL must be **net** of Binance spot taker fees (~10 bps) plus modelled slippage — the authors require exactly this ("meticulously model transaction costs, slippage, and market impact"); (v) run `tests/test_kronos_regression.py` first so the signal is known to come from an unmodified, revision-pinned model (CPU, deterministic — it costs nothing).

**Bottom line:** Kronos is a well-supported, MIT-licensed, zero-shot forecaster with a real published cross-sectional result and a usable CPU path, but *no* credible published evidence of single-pair 5m–1h directional edge, and its own authors disclaim production use. Start with `Kronos-small`/Tokenizer-base at 512 ctx, zero-shot with `sample_count` averaging, behind a validation harness that must beat persistence and a trivial technical baseline net of fees. Do not finetune, and do not wire it into live sizing, until that harness says it earns its keep.
