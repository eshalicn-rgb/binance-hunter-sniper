#!/usr/bin/env python3
"""Live tests for ARMED alerts — the alert must fire itself, not be sent by hand.

Talks to the running engine on port 3245 and proves the whole pipe:
  arm -> stored -> re-checked by the engine -> fires on price / on the clock -> card.
Crossing arithmetic itself is proven offline in _alertbooktest.py; this file proves
the plumbing and the honesty rules (nothing is sent before the trigger).
"""
import json
import time
from datetime import datetime, timedelta, timezone

import requests

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:                                    # pragma: no cover
    NY = timezone(timedelta(hours=-4))

BASE = "http://127.0.0.1:3245"
SYM = "BTCUSDT"
FAILS = []
MINE = []          # every alert this test arms, so it can take them all back down


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + ((" — " + str(detail)) if detail else ""))
    if not ok:
        FAILS.append(label)


def post(path, body):
    return requests.post(BASE + path, json=body, timeout=15)


def alerts():
    return requests.get(BASE + "/api/alerts", timeout=15).json()


def sent_count():
    try:
        return requests.get(BASE + "/api/status", timeout=15).json().get("telegram", {}).get("sent")
    except Exception:
        return None


def fired_total():
    """The engine's own count of alerts that actually triggered."""
    return alerts().get("fired_total")


def live(sym):
    """Same source the engine reads: Binance spot last price."""
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/price",
                         params={"symbol": sym}, timeout=15)
        return float(r.json()["price"])
    except Exception:
        return None


def wait_fired(aid, secs=25):
    """Poll until the alert leaves the armed state. Returns the row or None."""
    end = time.time() + secs
    while time.time() < end:
        v = alerts()
        for r in v.get("fired", []):
            if r.get("id") == aid:
                return r
        time.sleep(2)
    return None


def armed_ids():
    return {r.get("id") for r in alerts().get("armed", [])}


print("== A. an alert that cannot fire is refused ==")
for body, why in (
    ({"symbol": SYM, "alert_type": "CROSS UP"}, "CROSS UP with no target"),
    ({"symbol": SYM, "alert_type": "TIME"}, "TIME with no clock"),
    ({"symbol": "BTC", "alert_type": "ABOVE", "price": 5}, "non-USDT symbol"),
    ({"symbol": SYM, "alert_type": "MOON", "price": 5}, "unknown trigger"),
    ({"symbol": "", "alert_type": "ABOVE", "price": 5}, "no symbol"),
):
    r = post("/api/alert", body)
    check("refused: " + why, r.status_code == 400 and "error" in r.json(), r.status_code)

px0 = live(SYM)
check("live BTCUSDT price available", bool(px0), px0)
if not px0:
    print("\n   cannot continue without a live price")
    raise SystemExit(1)

print("\n== B. arming is silent — no card until the trigger ==")
before, before_fired = sent_count(), fired_total()
r = post("/api/alert", {"symbol": SYM, "alert_type": "CROSS UP",
                        "price": round(px0 * 1.25, 2), "note": "awaiting the reclaim"})
j = r.json()
check("armed ok", r.status_code == 200 and j.get("armed") is True, j.get("error"))
a = j.get("alert") or {}
aid = a.get("id")
MINE.append(aid)
check("row is armed with a target", a.get("state") == "armed" and bool(a.get("price")), a.get("state"))
check("row carries the note", a.get("note") == "awaiting the reclaim", a.get("note"))
check("arming sent a receipt card", sent_count() == before + 1,
      "sent %s -> %s" % (before, sent_count()))
check("arming fired NOTHING", fired_total() == before_fired,
      "fired %s -> %s" % (before_fired, fired_total()))
time.sleep(4)
row = next((x for x in alerts().get("armed", []) if x.get("id") == aid), None)
check("engine re-checked it and knows the live distance",
      bool(row) and row.get("last") is not None and row.get("dist_pct") is not None,
      "%s / %s%%" % (row and row.get("last"), row and row.get("dist_pct")))
check("target far above is still waiting", bool(row), row and row.get("side"))

print("\n== C. a level alert fires ITSELF when the price is already through ==")
before, before_fired = sent_count(), fired_total()
r = post("/api/alert", {"symbol": SYM, "alert_type": "ABOVE",
                        "price": round(px0 * 0.995, 2), "note": "armed below market"})
j = r.json()
check("level alert armed", j.get("armed") is True, j.get("error"))
aid2 = (j.get("alert") or {}).get("id")
MINE.append(aid2)
# A level that is already satisfied is fired by the alert loop on its next tick, so
# "it is still armed" is not observable from out here without racing the engine — the
# previous version asserted the alert had NOT fired and so failed whenever the engine
# did exactly what it is supposed to. The proof that matters is below: it fires by
# itself, with the right reason and a real fill.
fired = wait_fired(aid2, 25)
check("fired by itself, no human action", bool(fired), "id " + str(aid2))
if fired:
    check("reason is the price", fired.get("fired_reason") == "price", fired.get("fired_reason"))
    check("a real fill price was recorded", bool(fired.get("fired_price")), fired.get("fired_price"))
    check("it carries the clock stamp", bool(fired.get("fired_at_disp")), fired.get("fired_at_disp"))
check("exactly one alert fired", fired_total() == before_fired + 1,
      "fired %s -> %s" % (before_fired, fired_total()))
check("the fired card was pushed", (sent_count() or 0) > (before or 0),
      "sent %s -> %s" % (before, sent_count()))

print("\n== D. a TIME alert fires on the clock, not the price ==")
when = (datetime.now(NY) + timedelta(seconds=12)).replace(microsecond=0)
before, before_fired = sent_count(), fired_total()
r = post("/api/alert", {"symbol": SYM, "alert_type": "TIME",
                        "at": when.isoformat(), "note": "scheduled check"})
j = r.json()
check("clock alert armed", j.get("armed") is True, j.get("error"))
aid3 = (j.get("alert") or {}).get("id")
MINE.append(aid3)
check("armed with a hunter-time stamp", bool((j.get("alert") or {}).get("when_disp")),
      (j.get("alert") or {}).get("when_disp"))
check("the clock has not arrived yet", fired_total() == before_fired, "fired %s" % fired_total())
# `sent` is a global card counter — it also counts signal cards, catch cards and other
# alerts firing concurrently (the ABOVE alert above fires ~3s after arming), so it can
# never isolate one alert's receipt. `fired_total()` is the precise instrument.
fired = wait_fired(aid3, 40)
check("fired when the clock arrived", bool(fired), when.isoformat())
if fired:
    check("reason is the clock", fired.get("fired_reason") == "time", fired.get("fired_reason"))
check("exactly one alert fired", fired_total() == before_fired + 1,
      "fired %s -> %s" % (before_fired, fired_total()))
check("the card was pushed on time", (sent_count() or 0) > (before or 0),
      "sent %s -> %s" % (before, sent_count()))

print("\n== E. disarm and cleanup ==")
r = post("/api/alert", {"symbol": SYM, "alert_type": "CROSS DOWN",
                        "price": round(px0 * 0.75, 2), "confirm": False})
aid4 = (r.json().get("alert") or {}).get("id")
MINE.append(aid4)
check("a second alert is armed", aid4 in armed_ids(), aid4)
canc = post("/api/alert/cancel", {"id": aid4}).json()
check("cancel disarms it", canc.get("cancelled") is True, canc.get("cancelled"))
check("it is gone from the armed list", aid4 not in armed_ids())
canc2 = post("/api/alert/cancel", {"id": aid2}).json()
check("a fired alert cannot be disarmed", canc2.get("cancelled") is False, aid2)
n_before = len(alerts().get("armed", []))
clr = post("/api/alert/clear", {"state": "fired"}).json()
check("clear(fired) dropped the spent rows", (clr.get("cleared") or 0) >= 1, clr.get("cleared"))
check("clear never touched an armed alert",
      len(alerts().get("armed", [])) == n_before, "%s -> %s" % (n_before, len(alerts().get("armed", []))))
v = alerts()
check("the board reports counts", "armed" in (v.get("counts") or {}), v.get("counts"))
check("fired_total is tracked", isinstance(v.get("fired_total"), int), v.get("fired_total"))

print("\n== F. the test leaves the live board as it found it ==")
for x in MINE:
    if x:
        post("/api/alert/cancel", {"id": x})
post("/api/alert/clear", {"state": "fired"})
post("/api/alert/clear", {"state": "cancelled"})
leftover = [r for r in alerts().get("armed", []) if r.get("id") in MINE]
check("no test alert left armed on the live board", not leftover,
      json.dumps([r.get("symbol") for r in leftover]))
print("   armed alerts now:", json.dumps([{k: r.get(k) for k in ("symbol", "type", "price", "note")}
                                          for r in alerts().get("armed", [])]))

print("\n" + ("ALL ARMED-ALERT TESTS PASSED" if not FAILS else "FAILURES: " + ", ".join(FAILS)))
