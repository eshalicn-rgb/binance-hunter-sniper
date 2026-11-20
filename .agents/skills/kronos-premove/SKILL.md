---
name: kronos-premove
description: Measure whether the Kronos K-line foundation model can predict a crypto move BEFORE it happens, and decide PASS/FAIL against momentum and volatility controls plus trading fees. Use when asked to test, validate, benchmark, backtest or trust Kronos as a signal engine for the hunter, when asked "does the model have an edge", "can it catch the pump", "is the signal real", "should we wire this into entries", "prove it works", or before any change that would let a model forecast influence entries. Binance-native, Windows-native, CPU-only, deterministic and fail-closed. Do NOT use it to show a single forecast card (that is the separate `kronos` skill).
argument-hint: "[--symbols BTCUSDT,ETHUSDT] [--interval 5m] [--bars 3000] [--verdict]"
---

# Kronos pre-move — the accuracy authority

This skill answers one question with numbers: **can Kronos predict a move before
it happens, well enough to trade after fees?** It is a *measurement* tool, not a
signal generator. It never emits an entry.

Its verdict is **fail-closed**: a missing field fails its gate, and silence is
never a pass.

## The one rule

> A model forecast may only influence an entry if `verdict.py` returns **PASS**
> (exit code 0).

Everything below exists to make that rule checkable. The hunter is long-only and
has a measured, explainable filter chain; an unvalidated foundation model must
not quietly bypass it.

## Current status (already measured — do not re-derive)

At 5m on six Binance majors, 1290 walk-forward windows, Kronos-mini:

| Gate | Result | Why |
|---|---|---|
| A. Directional | **FAIL** | accuracy 0.50–0.52, a coin flip |
| B. Pre-move | **FAIL** | AUC 0.60–0.66, but the **volatility** control scores 0.75–0.83 |
| C. Payoff after fees | marginal | optimistic metric (max favourable excursion) |
| **Overall** | **FAIL — do not wire into entries** | |

So all Kronos is really saying is *"volatile things move"*, which is not new
information and does not survive a 0.20% round trip. Details and the frozen
table: `references/measured-5m-baseline.md`. Re-run it whenever the model, the
data window, or the timeframe changes — the answer is allowed to change, but only
on evidence.

## Run it

```powershell
cd G:\GrokMT5Bot\binance_hunter
& C:\Python314\python.exe .agents\skills\kronos-premove\scripts\measure.py --symbols BTCUSDT,ETHUSDT,SOLUSDT --interval 5m --verdict
```

Fast smoke run (~1 minute, proves the plumbing, decides nothing):

```powershell
& C:\Python314\python.exe .agents\skills\kronos-premove\scripts\measure.py --symbols BTCUSDT --bars 1200 --lookback 300 --stride 40 --max-windows 12 --interval 5m --verdict
```

Verdict on an existing measurement (no model load, instant):

```powershell
& C:\Python314\python.exe .agents\skills\kronos-premove\scripts\verdict.py _kronos_lab_5m.json --out _kronos_verdict.md
& C:\Python314\python.exe .agents\skills\kronos-premove\scripts\verdict.py _kronos_lab_5m.json --json
```

`measure.py` writes `<project-root>\_kronos_lab_<interval>.json`; the human report
is `_kronos_report.py` (`_kronos_accuracy.md`), and the decision is `verdict.py`
(`_kronos_verdict.md`).

**Exit codes: 0 PASS, 1 FAIL, 2 insufficient evidence.** With `--verdict`,
`measure.py` exits with the verdict's own code, so you can gate a change on it
directly. Script them, don't skim them:

```powershell
if ((& C:\Python314\python.exe scripts\measure.py --interval 5m --verdict) -ne 0) {
  Write-Host "no edge on this evidence - do not open the gate"
}
```

## The three gates

**A. Directional** — pooled accuracy ≥ 0.55 at some horizon, and it must beat
momentum *only when momentum itself is ≥ 0.50*. A baseline worse than a coin flip
is not a bar worth clearing.

**B. Pre-move** — pooled AUC ≥ 0.60 for some move size (+1%/+2%/+3% inside the
horizon), and strictly greater than **both** the momentum control and the
**volatility** control. Volatility is the bar that matters.

**C. Payoff after fees** — the mean move when the model flags its top 10% must
clear the 0.20% round trip *and* beat the unconditional mean by more than the fee.
This one is deliberately labelled optimistic: it reads the **maximum favourable
excursion**, i.e. it assumes you exit exactly at the high. A thin margin is noise,
which is why C alone can never carry a PASS.

Read `references/method.md` before arguing with a number.

## Environment (already verified on this machine)

- Interpreter: `C:\Python314\python.exe`. `torch 2.14.0+cpu` works on Python 3.14. **No GPU.**
- Models cached locally: `NeoQuasar/Kronos-mini` + `NeoQuasar/Kronos-Tokenizer-2k`.
- `max_context` **must match the tokenizer**: 2048 for `Tokenizer-2k`, 512 for `Tokenizer-base`. Kronos-mini *requires* the 2k tokenizer, so it is not the "cheap" option — it drags a 2048 context.
- Cost: ~0.8 s per window on CPU. Six symbols × 215 windows ≈ 18 minutes.
- Raising `--sample-count` (ensemble of forecast paths) buys more than raising model size, per the paper.

## Two landmark facts not to get wrong

1. The in-page **chart is TradingView only**; live prices, order book and tape come from Binance websockets. This skill must not depend on the chart.
2. The Kronos repo at `vendor\Kronos` is the upstream project (41k★, MIT, AAAI 2026) and its authors state the pipeline is *"a demonstration… not a production-ready quantitative trading system"*. Quote them, not marketing.

## Files

| Path | Role |
|---|---|
| `scripts/measure.py` | walk-forward measurement over the project harness |
| `scripts/verdict.py` | deterministic PASS/FAIL/INSUFFICIENT gate + markdown |
| `references/method.md` | methodology, controls, fee arithmetic, reading rules |
| `references/measured-5m-baseline.md` | the frozen 2026-10-18 result on Binance 5m |

The implementation of the measurement itself is **not** duplicated here. It lives
once, at `<project-root>\_kronos_lab.py`, and this skill is the interface to it —
so any number quoted anywhere traces back to a single code path. Override the
location with the `HUNTER_ROOT` env var if the project moves.
