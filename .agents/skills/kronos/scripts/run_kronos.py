#!/usr/bin/env python
"""Kronos skill runner (Windows port).

Outer launcher. Resolves the *vendored* Kronos repo, sanity-checks that the
current interpreter already has the model dependencies, then delegates to the
inner predict script.

There is NO venv, NO pip install and NO git clone here. This port uses the
interpreter that is running this script (``sys.executable``), which must
already have torch / pandas / einops installed (they are installed globally on
``C:\\Python314\\python.exe`` on this machine).

Usage:
    python run_kronos.py <SYMBOL> [interval] [bars] [pred_len] [--sample-count N]

Examples:
    python run_kronos.py BTCUSDT 5m 400 12
    python run_kronos.py ETHUSDT 1h 300 6

Arguments:
    SYMBOL      Binance symbol, e.g. BTCUSDT, ETHUSDT
    interval    one of 1m, 5m, 15m, 1h, 4h, 1d   (default 5m)
    bars        number of historical klines to fetch (default 400, max 1000)
    pred_len    number of future candles to forecast (default 24)
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
INNER = SKILL_DIR / "scripts" / "_predict.py"

# Vendored Kronos repo on this machine. Do not clone another copy.
VENDORED_KRONOS = Path(r"G:\GrokMT5Bot\binance_hunter\vendor\Kronos")

REQUIRED_MODULES = ("torch", "pandas", "einops")


def info(msg: str) -> None:
    print(f"[kronos] {msg}", file=sys.stderr, flush=True)


def resolve_repo() -> str:
    """KRONOS_REPO env var first, then the vendored repo, else a clear failure."""
    env_repo = os.environ.get("KRONOS_REPO")
    if env_repo:
        path = Path(env_repo)
        if (path / "model" / "kronos.py").exists():
            return str(path)
        print(
            f"[kronos] ERROR: KRONOS_REPO is set to '{env_repo}' but no "
            f"model/kronos.py was found there.",
            file=sys.stderr,
        )
        sys.exit(2)

    if (VENDORED_KRONOS / "model" / "kronos.py").exists():
        return str(VENDORED_KRONOS)

    print(
        "[kronos] ERROR: could not locate the Kronos repo.\n"
        f"  Set the KRONOS_REPO environment variable to the repo root, or place it at:\n"
        f"  {VENDORED_KRONOS}",
        file=sys.stderr,
    )
    sys.exit(2)


def missing_deps() -> list[str]:
    """Return required modules the running interpreter cannot import."""
    return [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]


def run_prediction(symbol: str, interval: str, bars: int, pred_len: int, sample_count: int) -> int:
    env = os.environ.copy()
    env["KRONOS_REPO"] = resolve_repo()
    argv = [
        sys.executable,
        str(INNER),
        symbol,
        interval,
        str(bars),
        str(pred_len),
        "--sample-count",
        str(sample_count),
    ]
    proc = subprocess.run(argv, env=env)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_kronos.py",
        description="Run a Kronos forecast on a Binance symbol (Windows port).",
    )
    parser.add_argument("symbol", help="Binance symbol, e.g. BTCUSDT")
    parser.add_argument("interval", nargs="?", default="5m", help="1m, 5m, 15m, 1h, 4h, 1d (default 5m)")
    parser.add_argument("bars", nargs="?", type=int, default=400, help="historical klines to fetch (default 400)")
    parser.add_argument("pred_len", nargs="?", type=int, default=24, help="future candles to forecast (default 24)")
    parser.add_argument("--sample-count", type=int, default=1, help="forward samples to draw (default 1)")
    args = parser.parse_args(argv)

    missing = missing_deps()
    if missing:
        print(
            f"[kronos] ERROR: {sys.executable} is missing required module(s): "
            f"{', '.join(missing)}. Install them into this interpreter "
            f"(no venv is created by this skill).",
            file=sys.stderr,
        )
        return 2

    return run_prediction(
        args.symbol.upper(),
        args.interval,
        args.bars,
        args.pred_len,
        args.sample_count,
    )


if __name__ == "__main__":
    sys.exit(main())
