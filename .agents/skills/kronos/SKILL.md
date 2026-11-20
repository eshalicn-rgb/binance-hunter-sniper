---
name: kronos
description: Run Kronos (open source candlestick foundation model) technical analysis on a Binance crypto symbol and get back a price prediction with a confidence band in plain English. Windows port — uses the globally installed Python at C:\Python314\python.exe, the vendored Kronos repo, and Binance klines (no venv, no yfinance). Triggers on "/kronos", "run kronos on X", "kronos analysis", "predict X with kronos", "technical analysis on X", "what does kronos say about X".
argument-hint: "<SYMBOL> [interval] [bars] [pred_len]"
---

# Kronos Technical Analysis Skill (Windows / Binance port)

The same kind of price prediction AI Wall Street pays millions for, packaged so you can run it from any Claude conversation with one command.

**This is a research tool, not financial advice.** It outputs a forward probability distribution with a confidence interval. Wide interval = noise. Narrow interval across multiple timeframes = signal worth investigating.

> **This skill is a convenience viewer for a single forecast.** The project's accuracy authority is the separate `kronos-premove` skill, which measures Kronos against momentum and volatility controls and reported **no tradeable edge at 5m on Binance**. See `WINDOWS-NOTES.md` in this skill directory.

---

## How to invoke

When the user asks for technical analysis on a symbol, calls the skill explicitly, or asks Kronos for a prediction, run the script and present the output verbatim. Do not editorialize the prediction. Add a "Not financial advice" reminder if the user is making decisions based on the output.

```powershell
& C:\Python314\python.exe "G:\GrokMT5Bot\binance_hunter\.agents\skills\kronos\scripts\run_kronos.py" <SYMBOL> [interval] [bars] [pred_len]
```

**Arguments:**
- `SYMBOL` (required) — Binance symbol, e.g. `BTCUSDT`, `ETHUSDT` (uppercased automatically). Not a Yahoo ticker — no `-USD` suffix.
- `interval` (default `5m`) — Candle size, one of `1m`, `5m`, `15m`, `1h`, `4h`, `1d`
- `bars` (default `400`) — How many historical klines to fetch (Binance caps at 1000). This is the lookback, not a period string.
- `pred_len` (default `24`) — How many future candles to forecast
- `--sample-count` (default `1`) — Optional flag: number of forward samples to draw

**Examples:**
- `run_kronos.py BTCUSDT` — 400 x 5m candles, 24-candle forecast
- `run_kronos.py BTCUSDT 5m 400 12` — 400 x 5m candles, 12-candle forecast
- `run_kronos.py ETHUSDT 1h 300 6` — 300 x 1h candles, 6-candle forecast

---

## Prerequisites (already satisfied on this machine)

This port creates **no venv**, runs **no pip install**, and **clones nothing**. It uses the interpreter running the script (`sys.executable`) — `C:\Python314\python.exe` here — which must already have `torch`, `pandas`, and `einops` installed (they are). The Kronos repo is resolved from, in order:

1. the `KRONOS_REPO` environment variable, then
2. `G:\GrokMT5Bot\binance_hunter\vendor\Kronos`

The launcher checks `torch` / `pandas` / `einops` up front and prints a clear one-line error if any is missing. Model weights (`NeoQuasar/Kronos-mini` + `NeoQuasar/Kronos-Tokenizer-2k`) are already in the local HuggingFace cache. Runs on CPU (~1 s per forecast window).

---

## What the output looks like

The script returns markdown with:
1. Last close price + timestamp
2. Predicted close after `pred_len` periods
3. Direction (UP / DOWN / FLAT) with percentage change
4. Confidence band (narrow = signal, wide = noise)
5. Interpretation rules
6. Full forecast trajectory as a table

Present this to the user as-is. Do not invent a prediction or modify the numbers.

---

## When to recommend a wider stack

If the user is making a real investment decision based on the output, recommend they pair this with:
1. Their own symbol-specific Claude Project containing the relevant filings / research
2. A bull case and bear case memo written by Claude using only the documents in the Project
3. A weekly run of `/kronos` across their watchlist
4. A quarterly refresh of the memos when earnings drop

This is the full two-layer stack: Kronos for the chart side, Claude for the fundamentals side.

Link to the full walkthrough: `https://ai-basic-series.vercel.app/run-kronos-walkthrough`

---

## What this is NOT

- Not a trading bot. Does not place orders.
- Not a price target. Outputs a probability distribution.
- Not financial advice. Research tool only.
- Not a license to skip risk management.
- Not validated as profitable — the `kronos-premove` skill found no tradeable edge at 5m on Binance.

When the user asks "should I buy this," redirect to the two-layer stack and remind them this is research, not a recommendation.

---

## Troubleshooting

**"is missing required module(s): torch, ..."** — The interpreter running the script lacks a dependency. Install it into that interpreter (e.g. `& C:\Python314\python.exe -m pip install torch`). This port never creates its own venv.

**"could not locate the Kronos repo"** — Set `KRONOS_REPO` to the repo root, or make sure the vendored copy exists at `G:\GrokMT5Bot\binance_hunter\vendor\Kronos`.

**"No data for SYMBOL"** — Binance has no klines for that symbol. Use Binance style (`BTCUSDT`, not `BTC` or `BTC-USD`), and a supported `interval`.

**"Unsupported interval"** — Use one of `1m`, `5m`, `15m`, `1h`, `4h`, `1d`.

**Slow / out of memory** — Reduce `bars` or `pred_len`. Everything runs on CPU.
