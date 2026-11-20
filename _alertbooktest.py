#!/usr/bin/env python3
"""Offline tests for AlertBook — the alert must fire itself, and only when hit.

No network, no engine: price and clock are injected, so every rule is provable.
"""
import os
import tempfile
from datetime import datetime, timedelta, timezone

import alertbook
from alertbook import AlertBook, ARMED, FIRED, CANCELLED

TZ = timezone(timedelta(hours=-4))          # America/New_York, EDT
T0 = datetime(2026, 10, 18, 9, 0, 0, tzinfo=TZ)

CLOCK = {"now": T0}
book = AlertBook(os.path.join(tempfile.mkdtemp(), "alerts.json"),
                 tzinfo=TZ, now_fn=lambda: CLOCK["now"])
PX = {}


def price_fn(sym):
    return PX.get(sym)


def tick(dt=None, **px):
    if dt:
        CLOCK["now"] = dt
    PX.update(px)
    return book.check(price_fn, now=CLOCK["now"])


def armed_count():
    return len(book.armed())


def side_of(aid):
    for r in book.armed():
        if r["id"] == aid:
            return r["side"]
    return None


# ---------------------------------------------------------------- validation
print("== validation: an alert that cannot fire is refused, not stored ==")
for bad, why in (
    (dict(symbol="BTCUSDT", atype="TIME"), "TIME with no clock"),
    (dict(symbol="BTCUSDT", atype="CROSS UP"), "CROSS UP with no level"),
    (dict(symbol="BTC", atype="CROSS UP", price=100), "non-USDT symbol"),
    (dict(symbol="BTCUSDT", atype="MOON", price=100), "unknown type"),
    (dict(symbol="BTCUSDT", atype="ABOVE", price=0), "zero level"),
    (dict(symbol="BTCUSDT", atype="BELOW", price=-5), "negative level"),
):
    try:
        book.arm(**bad)
        raise AssertionError("accepted an alert it cannot fire: " + why)
    except ValueError:
        pass
assert armed_count() == 0, "a refused alert still got stored"
print("   refused:", "TIME-no-clock, no-level, bad-symbol, bad-type, zero, negative")

# ------------------------------------------------------------- clock parsing
print("== clock parsing: hunter timezone, today or tomorrow ==")
d = book.parse_when("14:30")
assert d.strftime("%H:%M") == "14:30" and d.date() == T0.date(), "same-day clock not parsed"
d2 = book.parse_when("08:00")               # already gone at 09:00 → tomorrow
assert d2.date() == (T0 + timedelta(days=1)).date(), "past clock did not roll to tomorrow"
assert book.parse_when("") is None and book.parse_when("nonsense") is None, "bad clock accepted"
assert book.parse_when("2026-10-19 14:30").strftime("%Y-%m-%d %H:%M") == "2026-10-19 14:30"
print("   14:30 -> today · 08:00 -> tomorrow · 'nonsense' -> None")

# ------------------------------------------------------------------- TIME
print("== TIME: fires when the clock arrives, not a second before ==")
a = book.arm("BTCUSDT", "TIME", at="14:30", note="pre-market check")
assert tick() == [], "TIME alert fired early"
assert armed_count() == 1
CLOCK["now"] = T0.replace(hour=14, minute=29, second=59)
assert tick() == [], "TIME alert fired at 14:29:59"
CLOCK["now"] = T0.replace(hour=14, minute=30, second=0)
fired = tick()
assert len(fired) == 1 and fired[0]["fired_reason"] == "time", "TIME alert did not fire on time"
assert armed_count() == 0, "fired alert stayed armed"
print("   armed 09:00 -> silent at 14:29:59 -> fired 14:30:00 (reason=time)")

# --------------------------------------------------------------- CROSS UP
print("== CROSS UP: the first tick only learns which side we start on ==")
CLOCK["now"] = T0
b = book.arm("ETHUSDT", "CROSS UP", price=2500.0, note="reclaim of 2500")
assert tick(ETHUSDT=2400) == [], "fired with no crossing at all"
assert side_of(b["id"]) == -1, "did not record that price started below"
assert tick(ETHUSDT=2450) == [], "fired while still below the level"
assert tick(ETHUSDT=2499.99) == [], "fired just under the level"
fired = tick(ETHUSDT=2500.0)
assert len(fired) == 1 and fired[0]["fired_reason"] == "price", "CROSS UP did not fire on the cross"
assert fired[0]["fired_price"] == 2500.0, "fired price not recorded"
assert fired[0]["state"] == FIRED and armed_count() == 0
print("   2400 -> 2450 -> 2499.99 silent · 2500.00 fired (reason=price)")

print("== CROSS UP: never fires from above, even at the level ==")
c = book.arm("SOLUSDT", "CROSS UP", price=140.0)
assert tick(SOLUSDT=141.0) == [], "fired on the first tick from above"
assert side_of(c["id"]) == 1, "did not record that price started above"
assert tick(SOLUSDT=140.0) == [], "fired at the level without a cross from below"
assert tick(SOLUSDT=140.01) == [], "fired above the level"
print("   armed above the level -> stayed silent through a touch at 140.00")

# ------------------------------------------------------------- CROSS DOWN
print("== CROSS DOWN: symmetric, fires only on a downward cross ==")
d1 = book.arm("BTCUSDT", "CROSS DOWN", price=80000.0, note="lost the line")
assert tick(BTCUSDT=80500) == [] and side_of(d1["id"]) == 1
assert tick(BTCUSDT=80001) == [], "CROSS DOWN fired above the level"
fired = tick(BTCUSDT=80000)
assert len(fired) == 1 and fired[0]["type"] == "CROSS DOWN", "CROSS DOWN did not fire"
print("   80500 -> 80001 silent · 80000 fired")

# --------------------------------------------------------------- ABOVE/BELOW
print("== ABOVE / BELOW: level triggers, may fire on the very first tick ==")
book.clear(FIRED)
e = book.arm("XRPUSDT", "ABOVE", price=1.20)
assert len(tick(XRPUSDT=1.25)) == 1, "ABOVE did not fire when already above"
f = book.arm("XRPUSDT", "BELOW", price=1.20)
assert len(tick(XRPUSDT=1.10)) == 1, "BELOW did not fire when already below"
assert len(tick(XRPUSDT=1.30)) == 0, "BELOW fired above its level"
print("   ABOVE fired at 1.25 · BELOW fired at 1.10 · BELOW silent at 1.30")

# ----------------------------------------------------------- missing price
print("== a missing price never fires a price alert ==")
g = book.arm("DOGEUSDT", "ABOVE", price=0.10)
PX.pop("DOGEUSDT", None)
assert tick() == [], "fired with no market data"
for _ in range(3):
    assert tick() == [], "fired on repeated empty ticks"
assert armed_count() >= 1, "alert was dropped instead of staying armed"
print("   3 empty ticks -> still armed, nothing sent")

# ---------------------------------------------------------- price + clock
print("== price AND clock: whichever is hit first fires it ==")
h = book.arm("ADAUSDT", "CROSS UP", price=0.50, at="23:59")
assert tick(ADAUSDT=0.40) == []
fired = tick(ADAUSDT=0.51)                  # price hits long before the clock
assert len(fired) == 1 and fired[0]["fired_reason"] == "price", "price leg did not win"
i = book.arm("ADAUSDT", "CROSS UP", price=9.99, at="10:00")
CLOCK["now"] = T0.replace(hour=10, minute=0)
fired = tick(ADAUSDT=0.51)                  # clock arrives, price never gets there
assert len(fired) == 1 and fired[0]["fired_reason"] == "time", "time leg did not win"
print("   price leg won at 0.51 · time leg won at 10:00")

# ------------------------------------------------------------ cancel/clear
print("== cancel and clear never touch a live alert ==")
book.clear(FIRED)
j = book.arm("BNBUSDT", "ABOVE", price=999.0, note="keep me armed")
assert book.cancel("nope") is False, "cancel accepted an unknown id"
assert book.cancel(j["id"]) is True, "cancel did not close the alert"
assert all(r["id"] != j["id"] for r in book.armed()), "cancelled alert still armed"
k = book.arm("BNBUSDT", "ABOVE", price=999.0)
book.clear(FIRED)
assert any(r["id"] == k["id"] for r in book.armed()), "clear(FIRED) removed an armed alert"
assert book.clear(ARMED) == 0, "clear(ARMED) is not allowed to remove armed alerts"
vb = book.view()
assert vb["counts"]["armed"] >= 1 and "cancelled" in vb["counts"]
print("   cancel ok · clear(fired) kept the armed row · clear(ARMED) refused")

# ------------------------------------------------------------ persistence
print("== persistence: armed alerts survive a restart ==")
path2 = os.path.join(tempfile.mkdtemp(), "alerts.json")
b1 = AlertBook(path2, tzinfo=TZ, now_fn=lambda: CLOCK["now"])
b1.arm("LINKUSDT", "CROSS UP", price=20.0, note="carry over")
b1.arm("LINKUSDT", "TIME", at="15:45")
b2 = AlertBook(path2, tzinfo=TZ, now_fn=lambda: CLOCK["now"])
assert len(b2.armed()) == 2, "alerts did not reload after a restart"
assert b2.armed()[0]["note"] == "carry over", "note lost across a restart"
assert b2.armed()[1]["when_disp"], "clock display lost"
print("   2 armed alerts reloaded with their notes and clocks intact")

# --------------------------------------------------------------- semantics
print("== the book holds alerts, never trade sides ==")
for r in book.rows:
    assert r["type"] in alertbook.TYPES, "unknown type stored: " + str(r["type"])
    assert r["state"] in (ARMED, FIRED, CANCELLED), "unknown state: " + str(r["state"])
print("   types:", ", ".join(alertbook.TYPES))

print("\nALL ALERTBOOK TESTS PASSED")
