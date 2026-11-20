#!/usr/bin/env python
"""Kronos pre-move accuracy measurement -- the project's accuracy authority.

This is a thin, explicit interface over the project harness that already lives at
    <project-root>/_kronos_lab.py
It deliberately does NOT reimplement kline fetching, walk-forward anchoring or the
model call. There is exactly one implementation of the measurement, so a number
quoted anywhere in the project can always be traced back to one code path.

What it measures, per symbol and pooled:
  * forecast error            MAPE, predicted/actual return correlation
  * directional signal        accuracy at h = 1,3,6,12,24 bars vs momentum + base rate
  * pre-move detection        ROC-AUC / precision@10% / lift, vs MOMENTUM and VOLATILITY
  * tradeability              flagged mean move vs the round-trip fee

Read references/method.md before interpreting any number. Then run verdict.py,
which is the part that actually decides PASS/FAIL.

Usage (Windows, this machine's interpreter):
    C:\\Python314\\python.exe scripts\\measure.py --symbols BTCUSDT,ETHUSDT --interval 5m
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# <root>\.agents\skills\kronos-premove\scripts\measure.py  ->  <root>
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if os.environ.get("HUNTER_ROOT"):
    PROJECT_ROOT = Path(os.environ["HUNTER_ROOT"]).resolve()

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Measure Kronos pre-move accuracy on real Binance klines.")
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT",
                    help="comma-separated Binance symbols")
    ap.add_argument("--interval", default="5m",
                    choices=["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"])
    ap.add_argument("--bars", type=int, default=3000)
    ap.add_argument("--lookback", type=int, default=400)
    ap.add_argument("--pred-len", type=int, default=24)
    ap.add_argument("--stride", type=int, default=12)
    ap.add_argument("--sample-count", type=int, default=1,
                    help="forecast paths averaged internally (raise before raising model size)")
    ap.add_argument("--model", default="NeoQuasar/Kronos-mini")
    ap.add_argument("--tokenizer", default="NeoQuasar/Kronos-Tokenizer-2k")
    ap.add_argument("--max-context", type=int, default=2048,
                    help="must match the tokenizer: 2048 for Tokenizer-2k, 512 for Tokenizer-base")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--max-windows", type=int, default=0,
                    help="cap windows per symbol (0 = all). Use for a fast smoke run.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--verdict", action="store_true",
                    help="run verdict.py on the result immediately")
    a = ap.parse_args()

    try:
        import _kronos_lab
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: cannot import _kronos_lab from {PROJECT_ROOT}: {e}", file=sys.stderr)
        print("       pass --project-root via the HUNTER_ROOT env var if the project moved.",
              file=sys.stderr)
        return 2

    out = a.out or str(PROJECT_ROOT / f"_kronos_lab_{a.interval}.json")
    print(f"[kronos-premove] project root : {PROJECT_ROOT}", flush=True)
    print(f"[kronos-premove] writing       : {out}", flush=True)

    rep = _kronos_lab.run(
        symbols=[s.strip().upper() for s in a.symbols.split(",") if s.strip()],
        interval=a.interval,
        bars=a.bars,
        lookback=a.lookback,
        pred_len=a.pred_len,
        stride=a.stride,
        model_name=a.model,
        tokenizer_name=a.tokenizer,
        sample_count=a.sample_count,
        horizons=[1, 3, 6, 12, 24],
        events=[{"tag": "move1", "move_pct": 1.0},
                {"tag": "move2", "move_pct": 2.0},
                {"tag": "move3", "move_pct": 3.0}],
        out_json=out,
        limit_windows=a.max_windows or None,
        max_context=a.max_context,
        batch_size=a.batch,
    )

    print("\n===== POOLED =====")
    import json as _json
    for k, v in rep["pooled"].items():
        print(f"  {k:<22} {_json.dumps(v)}")

    if a.verdict:
        import subprocess
        print(flush=True)
        verdict = Path(__file__).with_name("verdict.py")
        rc = subprocess.run([sys.executable, str(verdict), str(out)]).returncode
        if rc:
            print(f"\n[kronos-premove] NOT a PASS (exit {rc}) — do not wire Kronos "
                  f"into the entry path on this evidence.", flush=True)
        # With --verdict this process exits with the gate's own code, so a caller can
        # gate on it: 0 PASS, 1 FAIL, 2 insufficient evidence.
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
