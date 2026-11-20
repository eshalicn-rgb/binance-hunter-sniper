# Windows port notes

The upstream skill (`coopersimson96/kronos-claude-skill@kronos`) targets macOS.
This copy was ported to run on this Windows machine. Only files inside this
`.agents/skills/kronos/` directory were changed.

## What changed from upstream

| Upstream (macOS) | This port (Windows) |
| --- | --- |
| Created a `.venv` and `pip install`ed torch/transformers/yfinance on first run (3–7 min, ~2 GB) | **No venv, no pip install.** Uses the interpreter running the script (`sys.executable`), i.e. `C:\Python314\python.exe`, which already has torch/pandas/einops globally |
| `git clone`d the Kronos repo into `_kronos/` | **No clone.** Resolves the vendored repo: `KRONOS_REPO` env var → `G:\GrokMT5Bot\binance_hunter\vendor\Kronos` → clear error |
| Market data from **yfinance** (`BTC-USD`, period strings like `6mo`) | Market data from **Binance klines** via stdlib `urllib` (`BTCUSDT`), with a `data-api.binance.vision` fallback. No new dependency |
| Default model `Kronos-small` + `Kronos-Tokenizer-base`, `max_context=512` | Default `NeoQuasar/Kronos-mini` + `NeoQuasar/Kronos-Tokenizer-2k`, **`max_context=2048`** (mini needs the 2k tokenizer, so the ceiling is 2048, not 512). Overridable via `KRONOS_MODEL_ID`, `KRONOS_TOKENIZER_ID`, `KRONOS_MAX_CONTEXT` |
| Args: `<TICKER> [period] [interval] [pred_len]` | Args: `<SYMBOL> [interval] [bars] [pred_len]` — defaults `5m 400 24`. `interval` is a Binance interval; `bars` is the lookback count, **not** a yfinance period |
| Hardcoded `python3 ~/.claude/skills/...` | Uses `C:\Python314\python.exe` and paths inside this skill directory |

Unchanged: markdown output card (last close, predicted close, direction,
confidence band, interpretation rules, caveats, full trajectory table),
`sample_count=1`, `T=1.0`, `top_p=0.9`. The footer now points at the vendored
repo instead of `~/.claude/skills/kronos/*`.

## How to run

```powershell
cd G:\GrokMT5Bot\binance_hunter\.agents\skills\kronos
& C:\Python314\python.exe .\scripts\run_kronos.py BTCUSDT 5m 400 12
& C:\Python314\python.exe .\scripts\run_kronos.py ETHUSDT 1h 300 6
```

Supported intervals: `1m`, `5m`, `15m`, `1h`, `4h`, `1d`. Binance caps a klines
request at 1000 bars (`bars` is clamped to that). CPU only; about 1 s per
forecast window. `--sample-count N` is optional.

## Accuracy authority

**This skill is a convenience viewer for a single forecast.** The project's
accuracy authority is the separate **`kronos-premove`** skill, which measures
Kronos against momentum and volatility controls and **reported no tradeable
edge at 5m on Binance**. Treat the card below as one input, not a signal.

## Maintenance warning

A future `npx skills update` (or any re-sync of the upstream skill) would
overwrite this port with the original macOS version. Re-apply these changes
after any such update, or vendor this directory.
