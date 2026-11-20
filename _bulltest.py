#!/usr/bin/env python3
"""LONG-ONLY GATE regression.

The hunter buys pumps and never shorts. Every entry path must route through
structure.bullish_gate(), and that gate must never return a direction other than
"BUY" on success and must refuse the three bearish cases:
    * not enough buy-side taker flow
    * a SHORT Fib/Gann read
    * a DOWNTREND structure
This is the regression for the "SIDE SELL with a long plan" contradiction.
"""
import structure as S


def case(name, a, expect_ok, need=0.60, req=False):
    ok, why, d = S.bullish_gate(a, need=need, require_bullish_struct=req)
    assert ok == expect_ok, "FAIL %s: ok=%s why=%s" % (name, ok, why)
    if expect_ok:
        assert d == "BUY", "FAIL %s: direction %r must be BUY" % (name, d)
        print("  PASS %-34s -> BUY" % name)
    else:
        assert d is None, "FAIL %s: refused gate must not hand a direction" % name
        print("  PASS %-34s -> refused (%s)" % (name, why))


print("=== the pasted card: newsdesk on sell-side flow ===")
# BTCUSDT, IMBAL -0.25 / buy-side below half, FIB/GANN NEUTRAL
case("sell-side flow refused", {
    "buy_ratio": 0.22, "ta": {"bias": "NEUTRAL", "score": 45},
    "struct": {"state": "RANGE", "score": 50, "bullish": False}}, False)

print("=== each bearish veto ===")
case("SHORT fib/gann refused", {
    "buy_ratio": 0.90, "ta": {"bias": "SHORT", "score": 28},
    "struct": {"state": "UPTREND", "score": 80, "bullish": True}}, False)
case("DOWNTREND refused", {
    "buy_ratio": 0.90, "ta": {"bias": "LONG", "score": 70},
    "struct": {"state": "DOWNTREND", "score": 70, "bullish": False}}, False)
case("exactly half is not a pump", {
    "buy_ratio": 0.50, "ta": {"bias": "LONG", "score": 70},
    "struct": {"state": "UPTREND", "score": 70, "bullish": True}}, False)

print("=== a real bullish pump passes ===")
case("bullish pump accepted", {
    "buy_ratio": 0.72, "ta": {"bias": "LONG", "score": 68},
    "struct": {"state": "UPTREND", "score": 78, "bullish": True}}, True)
case("missing struct still needs flow", {
    "buy_ratio": 0.80, "ta": {"bias": "LONG", "score": 68}}, True)

print("=== pre-pump is the strictest ===")
case("pre-pump needs bullish struct", {
    "buy_ratio": 0.55, "ta": {"bias": "NEUTRAL"},
    "struct": {"state": "RANGE", "score": 55, "bullish": False}}, False, need=0.50, req=True)
case("pre-pump bullish coil accepted", {
    "buy_ratio": 0.55, "ta": {"bias": "NEUTRAL"},
    "struct": {"state": "UPTREND", "score": 70, "bullish": True}}, True, need=0.50, req=True)

print("ALL LONG-ONLY GATE TESTS PASSED")
