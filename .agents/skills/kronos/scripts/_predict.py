#!/usr/bin/env python
"""Inner predict runner for the Windows port of the Kronos skill.

Runs on the interpreter that already has torch / pandas / einops installed
(no venv). The Kronos repo must be on disk and pointed at by $KRONOS_REPO.

Market data comes from Binance public klines (no API key, stdlib urllib only),
not yfinance. Output is a markdown card printed to stdout for display.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

_DEFAULT_REPO = r"G:\GrokMT5Bot\binance_hunter\vendor\Kronos"
KRONOS_REPO = Path(os.environ.get("KRONOS_REPO", _DEFAULT_REPO))
sys.path.insert(0, str(KRONOS_REPO))

try:
    from model import Kronos, KronosTokenizer, KronosPredictor
except Exception as e:
    print(f"ERROR loading Kronos model module: {e}", file=sys.stderr)
    print(f"Expected Kronos repo at: {KRONOS_REPO}", file=sys.stderr)
    print("Set KRONOS_REPO to the repo root, or place it at:", file=sys.stderr)
    print(f"  {_DEFAULT_REPO}", file=sys.stderr)
    sys.exit(2)


# Kronos-mini is paired with the 2k tokenizer, which gives it a 2048-token
# context. That is why max_context must be 2048 here, not 512: 512 is the
# ceiling for Kronos-small/Kronos-base, which use Kronos-Tokenizer-base.
# Using the 2k tokenizer with max_context=512 would throw away most of the
# context the mini model was built for.
TOKENIZER_ID = os.environ.get("KRONOS_TOKENIZER_ID", "NeoQuasar/Kronos-Tokenizer-2k")
MODEL_ID = os.environ.get("KRONOS_MODEL_ID", "NeoQuasar/Kronos-mini")
MAX_CONTEXT = int(os.environ.get("KRONOS_MAX_CONTEXT", "2048"))

# Binance interval -> pandas frequency for the FUTURE timestamp index.
INTERVAL_TO_FREQ = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}

BINANCE_FALLBACK_HOSTS = (
    "https://api.binance.com",
    "https://data-api.binance.vision",
)

# Binance caps a single klines request at 1000 rows.
MAX_BARS = 1000


def fetch_ohlcv(symbol: str, interval: str, bars: int) -> pd.DataFrame:
    """Pull OHLCV from Binance public klines (with a mirror fallback)."""
    if bars > MAX_BARS:
        print(f"[kronos] bars={bars} exceeds Binance max {MAX_BARS}; clamping.", file=sys.stderr)
        bars = MAX_BARS

    query = f"symbol={symbol}&interval={interval}&limit={bars}"
    last_err: Exception | None = None

    for host in BINANCE_FALLBACK_HOSTS:
        url = f"{host}/api/v3/klines?{query}"
        try:
            print(f"[kronos] fetching {symbol} {bars} x {interval} from {host.split('//')[1]}...", file=sys.stderr)
            with urllib.request.urlopen(url, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if not isinstance(payload, list) or not payload:
                raise ValueError(f"empty/unexpected response from {host}")

            history = pd.DataFrame(
                [[row[1], row[2], row[3], row[4], row[5]] for row in payload],
                columns=["open", "high", "low", "close", "volume"],
                index=pd.to_datetime([row[0] for row in payload], unit="ms"),
            )
            history.index.name = "timestamps"
            history = history.astype(float)
            return history
        except Exception as e:  # noqa: BLE001 - try the next host
            last_err = e
            print(f"[kronos] {host.split('//')[1]} failed: {e}", file=sys.stderr)

    raise SystemExit(
        f"No data for {symbol} interval={interval} limit={bars} from Binance. "
        f"Check the symbol (Binance style, e.g. BTCUSDT) and the interval. "
        f"Last error: {last_err}"
    )


def build_future_timestamps(last_ts: pd.Timestamp, interval: str, pred_len: int) -> pd.DatetimeIndex:
    """Build a future-timestamp index matching the Binance interval cadence."""
    freq = INTERVAL_TO_FREQ[interval]
    return pd.date_range(start=last_ts, periods=pred_len + 1, freq=freq)[1:]


def load_predictor() -> KronosPredictor:
    print(
        f"[kronos] loading {MODEL_ID} + {TOKENIZER_ID} (max_context={MAX_CONTEXT}, cpu)...",
        file=sys.stderr,
    )
    tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_ID)
    model = Kronos.from_pretrained(MODEL_ID)
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=MAX_CONTEXT)
    return predictor


def format_output(
    symbol: str,
    history: pd.DataFrame,
    forecast: pd.DataFrame,
    pred_len: int,
    interval: str,
) -> str:
    last_close = float(history["close"].iloc[-1])
    pred_close = float(forecast["close"].iloc[-1])
    pct_change = ((pred_close - last_close) / last_close) * 100.0

    pred_high = float(forecast["close"].max())
    pred_low = float(forecast["close"].min())
    band_width_pct = ((pred_high - pred_low) / last_close) * 100.0

    if pct_change > 0.25:
        direction = "UP"
    elif pct_change < -0.25:
        direction = "DOWN"
    else:
        direction = "FLAT"

    if band_width_pct < 5:
        confidence = "NARROW (signal worth investigating)"
    elif band_width_pct < 10:
        confidence = "MODERATE (mixed signal, check other timeframes)"
    else:
        confidence = "WIDE (treat as noise, model is hedging)"

    last_ts = history.index[-1].strftime("%Y-%m-%d %H:%M")

    output = []
    output.append(f"# Kronos Prediction: {symbol}")
    output.append("")
    output.append(f"**Last close:** ${last_close:,.2f} ({last_ts})")
    output.append(f"**Predicted close after {pred_len} x {interval} candles:** ${pred_close:,.2f}")
    output.append(f"**Direction:** {direction} ({pct_change:+.2f}%)")
    output.append(f"**Confidence band:** {confidence}")
    output.append(f"**Forecast range:** ${pred_low:,.2f} - ${pred_high:,.2f} (±{band_width_pct:.2f}% of last close)")
    output.append("")
    output.append("## Interpretation rules")
    output.append("")
    output.append("- **NARROW band (<5%):** model is confident across its forward distribution. Treat as a signal worth investigating. Look for confirmation on a second timeframe before acting.")
    output.append("- **MODERATE band (5-10%):** mixed signal. Useful for context, not for decisions on its own.")
    output.append("- **WIDE band (>10%):** model is hedging. Treat the prediction as noise. Do not act on it.")
    output.append("")
    output.append("## What this is NOT")
    output.append("")
    output.append("This is a probability distribution over likely price paths, not a price target.")
    output.append("Not financial advice. Markets carry real risk. Run on multiple timeframes")
    output.append("(daily AND weekly, for example) and pair with the fundamental side before")
    output.append("giving any signal weight.")
    output.append("")
    output.append("## Full forecast trajectory")
    output.append("")
    output.append("```")
    output.append(forecast.round(2).to_string())
    output.append("```")
    output.append("")
    output.append("---")
    output.append("")
    output.append(
        f"*Model: {MODEL_ID} — Kronos foundation model, trained on 12B candlesticks from 45 exchanges. "
        f"Data: Binance klines ({interval}). Skill: G:\\GrokMT5Bot\\binance_hunter\\.agents\\skills\\kronos "
        f"(Windows port; vendored repo at G:\\GrokMT5Bot\\binance_hunter\\vendor\\Kronos).*"
    )
    return "\n".join(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="_predict.py")
    parser.add_argument("symbol")
    parser.add_argument("interval", nargs="?", default="5m")
    parser.add_argument("bars", nargs="?", type=int, default=400)
    parser.add_argument("pred_len", nargs="?", type=int, default=24)
    parser.add_argument("--sample-count", type=int, default=1)
    args = parser.parse_args(argv)

    symbol = args.symbol.upper()

    if args.interval not in INTERVAL_TO_FREQ:
        print(
            f"Unsupported interval '{args.interval}'. "
            f"Choose one of: {', '.join(INTERVAL_TO_FREQ)}",
            file=sys.stderr,
        )
        return 1
    if args.bars < 1 or args.pred_len < 1:
        print("bars and pred_len must be positive integers", file=sys.stderr)
        return 1

    history = fetch_ohlcv(symbol, args.interval, args.bars)
    predictor = load_predictor()

    last_ts = history.index[-1]
    x_timestamp = pd.Series(history.index)
    y_timestamp = pd.Series(build_future_timestamps(last_ts, args.interval, args.pred_len))

    print(f"[kronos] predicting {args.pred_len} forward candles for {symbol}...", file=sys.stderr)
    forecast = predictor.predict(
        df=history,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=args.pred_len,
        T=1.0,
        top_p=0.9,
        sample_count=args.sample_count,
    )

    print(format_output(symbol, history, forecast, args.pred_len, args.interval))
    return 0


if __name__ == "__main__":
    sys.exit(main())
