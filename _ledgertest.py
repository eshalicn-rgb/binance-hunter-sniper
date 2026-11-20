"""Regression tests for the follow-up ledger.

Pins the phantom-stop bug: a row whose plan stop sits on the WRONG side of its
entry used to resolve as status=SL with a POSITIVE outcome, so the dashboard read
"100% win / SL 1". Also covers the normal TP/SL resolution and the row cap.
"""
import os
import tempfile
import time

import signals

FAILED = []


def check(name, got, want):
    ok = got == want
    print(("  PASS " if ok else "  FAIL ") + name + "  got=%r want=%r" % (got, want))
    if not ok:
        FAILED.append(name)


def mk_bars(ts, bars):
    """bars = [(high, low, close), ...] starting at the bar containing ts."""
    t0 = (int(ts) // 60 + 1) * 60000
    return [[t0 + i * 60000, 0.0, h, l, c, 1.0] for i, (h, l, c) in enumerate(bars)]


def new_ledger():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)
    return signals.SignalLedger(path)


print("=== mark(): plan-stop on the WRONG side of entry (the phantom-stop bug) ===")
led = new_ledger()
ts = time.time() - 600
# entry 100, but the plan's stop is ABOVE the entry and so is the target --
# exactly the shape the engine produced from a bearish structure.
bad = {"entry": 100.0, "stop": 105.0, "tp2": 110.0, "trail_arm": 104.0, "trail_dist": 1.0}

# bars that never reach the flat envelope: the old code resolved an instant
# positive-outcome SL here, purely because the stop sat above the entry.
led.record("BADUSDT", "BUY", 100.0, kind="watch", ts=ts, plan=bad)
led.mark("BADUSDT", mk_bars(ts, [(100.5, 99.0, 99.5), (100.2, 98.8, 99.0)]), now=ts + 120)
row = led.rows[0]
check("wrong-side stop no longer fires", row["status"], "OPEN")
check("wrong-side stop leaves outcome empty", row["outcome"], None)

# the same broken plan, now with price actually reaching the flat -5% stop
led.record("BAD2USDT", "BUY", 100.0, kind="watch", ts=ts, plan=bad)
led.mark("BAD2USDT", mk_bars(ts, [(100.5, 99.0, 99.5), (100.0, 94.5, 95.0)]), now=ts + 120)
row = [x for x in led.rows if x["symbol"] == "BAD2USDT"][0]
check("falls back to the flat envelope stop", row["status"], "SL")
check("flat envelope stop resolves negative", row["outcome"], round(-signals.SL, 3))

print()
print("=== mark(): a normal long resolves at its own plan levels ===")
led = new_ledger()
ts = time.time() - 600
plan = {"entry": 100.0, "stop": 98.0, "tp2": 104.0, "trail_arm": 103.0, "trail_dist": 1.0}

led.record("TPUSDT", "BUY", 100.0, kind="watch", ts=ts, plan=plan)
led.mark("TPUSDT", mk_bars(ts, [(101.0, 99.5, 100.5), (104.5, 101.0, 104.2)]), now=ts + 120)
check("target hit -> TP", led.rows[0]["status"], "TP")
check("target hit -> positive outcome", led.rows[0]["outcome"], 4.0)

led.record("SLUSDT", "BUY", 100.0, kind="watch", ts=ts, plan=plan)
led.mark("SLUSDT", mk_bars(ts, [(101.0, 99.5, 100.5), (101.0, 97.5, 98.0)]), now=ts + 120)
r = [x for x in led.rows if x["symbol"] == "SLUSDT"][0]
check("stop hit -> SL", r["status"], "SL")
check("stop hit -> negative outcome", r["outcome"], -2.0)

print()
print("=== summary() never contradicts itself (no win on a stop) ===")
s = led.summary()
check("closed counted", s["closed"], 2)
check("tp counted", s["tp"], 1)
check("sl counted", s["sl"], 1)
check("win rate is 50 on one TP one SL", s["win_rate"], 50.0)

print()
print("=== ledger is capped, live rows survive the trim ===")
led = new_ledger()
ts = time.time()
led.rows = [dict(symbol="OLD%d" % i, ts=ts - 10000 + i, status="TP", outcome=1.0,
                 direction="BUY", kind="watch") for i in range(signals.MAX_ROWS)]
led.record("LIVEUSDT", "BUY", 1.0, kind="watch", ts=ts, plan=None)
check("capped at MAX_ROWS", len(led.rows), signals.MAX_ROWS)
check("live row kept", any(r["symbol"] == "LIVEUSDT" for r in led.rows), True)
check("newest resolved kept", led.rows[-1]["status"], "TP")

print()
print("=== base rate pools gross profit/loss, never the mean of per-symbol ratios ===")
led = new_ledger()
led._bt = {
    "AUSDT": {"symbol": "AUSDT", "trades": 1, "wins": 1, "win_rate": 100.0, "avg_ret": 10.0,
              "expectancy": 10.0, "profit_factor": None, "gross_w": 10.0, "gross_l": 0.0, "tf": "1m"},
    "BUSDT": {"symbol": "BUSDT", "trades": 20, "wins": 1, "win_rate": 5.0, "avg_ret": -0.85,
              "expectancy": -0.85, "profit_factor": 0.105, "gross_w": 2.0, "gross_l": 19.0, "tf": "1m"},
}
s = led.backtest_summary()
# pooled = (10 + 2) / (0 + 19) = 0.6316 -> 0.63, NOT the 0.105 a mean-of-ratios gives
check("profit factor is pooled gross/gross", s["profit_factor"], 0.63)
check("win rate is pooled over all trades", s["win_rate"], 9.5)
check("mean return across symbols", s["avg_ret"], 4.575)
check("median return exposed", s["median_ret"], 10.0)
check("share of profitable symbols exposed", s["pct_profitable"], 50.0)
check("best symbol named", s["best_sym"]["symbol"], "AUSDT")
check("worst symbol named", s["worst_sym"]["symbol"], "BUSDT")

ignored = signals.SignalLedger._aggregate([])
check("empty aggregate is safe", ignored["symbols"], 0)

print()
print("=== long-only: a non-BUY direction can never enter the ledger ===")
led = new_ledger()
before = len(led.rows)
refused = led.record("SHORTUSDT", "SELL", 100.0, kind="signal", ts=time.time())
check("record() returns None for SELL", refused, None)
check("nothing stored for SELL", len(led.rows), before)
check("no SELL row present", any(str(r.get("direction")).upper() == "SELL" for r in led.rows), False)
buy = led.record("LONGUSDT", "BUY", 100.0, kind="signal", ts=time.time())
check("BUY still records", buy is not None, True)
check("BUY row is stored", len(led.rows), before + 1)

print()
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    raise SystemExit(1)
print("ALL LEDGER TESTS PASSED")
