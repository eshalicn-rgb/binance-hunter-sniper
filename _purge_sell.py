#!/usr/bin/env python3
"""One-time migration: archive and remove legacy SELL rows from the signal ledger.

Before the long-only fix, `direction` was derived from taker flow, so a sell-side
signal was stored with a long-only plan stapled to it (stop below entry, targets
above) — a logical contradiction, and exactly the "SIDE SELL with a BUY plan" the
dashboard showed. The hunter is bullish-only now, so those rows are not valid
history: archive them and leave the ledger consistent with what we actually hunt.

Run this while the hunter is STOPPED, otherwise the running engine overwrites the
file from its in-memory copy on the next save.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LED = os.path.join(HERE, "signals.json")
ARCH = os.path.join(HERE, "signals.sell_archive.json")

if not os.path.exists(LED):
    raise SystemExit("no ledger at %s" % LED)

with open(LED, "r") as f:
    rows = json.load(f)
if not isinstance(rows, list):
    rows = []

keep = [r for r in rows if str(r.get("direction", "")).upper() == "BUY"]
sell = [r for r in rows if str(r.get("direction", "")).upper() != "BUY"]

print("ledger rows        :", len(rows))
print("bullish (kept)     :", len(keep))
print("legacy non-BUY (out):", len(sell))

if sell:
    old = []
    if os.path.exists(ARCH):
        try:
            with open(ARCH, "r") as f:
                old = json.load(f)
            if not isinstance(old, list):
                old = []
        except Exception:
            old = []
    with open(ARCH, "w") as f:
        json.dump(old + sell, f, indent=1)
    with open(LED, "w") as f:
        json.dump(keep, f, indent=1)
    print("archived to        :", ARCH)
else:
    print("nothing to purge")


def stats(rs):
    done = [r for r in rs if r.get("status") != "OPEN"]
    wins = [r for r in done if float(r.get("outcome") or 0) > 0]
    outs = [float(r.get("outcome") or 0) for r in done]
    gw = sum(o for o in outs if o > 0)
    gl = -sum(o for o in outs if o < 0)
    return (len(rs), len(rs) - len(done), len(done), len(wins),
            round(len(wins) / len(done) * 100, 1) if done else 0.0,
            round(gw / gl, 2) if gl > 0 else None)


for label, rs in (("before", rows), ("after ", keep)):
    t, o, c, w, wr, pf = stats(rs)
    print("%s  total=%-4d open=%-4d closed=%-4d wins=%-3d win_rate=%-5s profit_factor=%s"
          % (label, t, o, c, w, wr, pf))

print("\nPURGE DONE")
