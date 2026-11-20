#!/usr/bin/env python3
"""
ARMED ALERTS — you set the level, the hunter watches, the card fires itself.

An alert is NOT a one-off message. It is armed with a symbol, a direction, and a
trigger (a target price, a clock time, or both). The engine re-checks every armed
alert on each cycle and only pushes the Telegram card when the market actually
does the thing. Nothing is ever sent on a guess.

Conditions
    CROSS UP     was below the target, price is now at/above it
    CROSS DOWN   was above the target, price is now at/below it
    ABOVE        price is at/above the target (level entry — can fire at once)
    BELOW        price is at/below the target (level entry — can fire at once)
    TIME         the armed clock has arrived

A CROSS needs a previous observation: the first price tick only records which side
of the level the market started on, so a freshly armed alert can never "cross" out
of nothing. A TIME alert needs no market data at all.

The clock is always the hunter's timezone (`HUNTER_TZ`), the same clock every card
and the candle timer already use.
"""
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

# State
ARMED = "armed"
FIRED = "fired"
CANCELLED = "cancelled"

TYPES = ("CROSS UP", "CROSS DOWN", "ABOVE", "BELOW", "TIME")

# A price alert needs a level; a TIME alert needs a clock.
PRICE_TYPES = ("CROSS UP", "CROSS DOWN", "ABOVE", "BELOW")


def _f(v):
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


class AlertBook:
    """Persisted store of armed price/time alerts plus the trigger engine."""

    MAX_ROWS = 200
    MAX_ARMED = 50

    def __init__(self, path, tzinfo=None, now_fn=None):
        self.path = path
        self.tzinfo = tzinfo or timezone.utc
        self._now_fn = now_fn
        self.lock = threading.RLock()
        self.rows = []
        self.load()

    # ---------------------------------------------------------------- clock
    def now(self):
        if self._now_fn:
            return self._now_fn()
        return datetime.now(self.tzinfo)

    def parse_when(self, s):
        """Resolve a user clock string to an aware datetime on the hunter clock.

        Accepts "HH:MM" (today, or tomorrow when that time has already passed),
        "YYYY-MM-DD HH:MM[:SS]", "YYYY/MM/DD HH:MM" and full ISO strings.
        Returns None when the string cannot be read — the caller fails closed.
        """
        s = (s or "").strip()
        if not s:
            return None
        now = self.now()
        tz = now.tzinfo or self.tzinfo
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=tz)
        except Exception:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=tz)
            except Exception:
                pass
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                t = datetime.strptime(s, fmt)
            except Exception:
                continue
            d = now.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)
            if d <= now:                       # already gone today → aim at tomorrow
                d += timedelta(days=1)
            return d
        return None

    @staticmethod
    def _disp(d):
        """Compact, unambiguous stamp for a card: 10-18 14:30 -04:00"""
        try:
            off = d.strftime("%z")
            off = off[:3] + ":" + off[3:] if len(off) == 5 else off
            return "%s %s" % (d.strftime("%m-%d %H:%M"), off)
        except Exception:
            return ""

    # ---------------------------------------------------------- persistence
    def load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r") as fh:
                    data = json.load(fh)
                rows = data.get("rows") if isinstance(data, dict) else data
                self.rows = [r for r in (rows or []) if isinstance(r, dict) and r.get("id")]
        except Exception:
            self.rows = []

    def save(self):
        try:
            with self.lock:
                rows = self.rows[-self.MAX_ROWS:]
                tmp = self.path + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump({"rows": rows}, fh, indent=1)
                os.replace(tmp, self.path)
        except Exception:
            pass

    # ------------------------------------------------------------------ api
    def arm(self, symbol, atype, price=None, at=None, note=None, armed_price=None):
        """Arm one alert. Returns the row, or raises ValueError with the reason."""
        symbol = (symbol or "").strip().upper()
        atype = (atype or "CROSS UP").strip().upper()
        if atype in ("CROSSUP", "CROSS-UP", "UP"):
            atype = "CROSS UP"
        elif atype in ("CROSSDOWN", "CROSS-DOWN", "DOWN"):
            atype = "CROSS DOWN"
        elif atype in ("PRICE ABOVE", "ABOVE"):
            atype = "ABOVE"
        elif atype in ("PRICE BELOW", "BELOW"):
            atype = "BELOW"
        if atype not in TYPES:
            raise ValueError("unknown alert type: %s" % atype)
        if not symbol or not symbol.endswith("USDT"):
            raise ValueError("symbol must be a Binance USDT pair, e.g. BTCUSDT")

        level = _f(price)
        when = self.parse_when(at) if at else None
        if atype == "TIME":
            if when is None:
                raise ValueError("TIME alert needs a clock — e.g. 14:30")
            level = None
        elif level is None:
            raise ValueError("%s needs a target price" % atype)
        if atype != "TIME" and when is None and at is None:
            pass                                # price-only: fires on the cross
        if at and when is None:
            raise ValueError("cannot read the time %r — use HH:MM or YYYY-MM-DD HH:MM" % at)

        with self.lock:
            live = [r for r in self.rows if r.get("state") == ARMED]
            if len(live) >= self.MAX_ARMED:
                raise ValueError("too many armed alerts (%d) — cancel some first" % self.MAX_ARMED)
            now = self.now()
            a_price = _f(armed_price) or level
            side = 0
            dist = None
            if level and a_price:
                side = 1 if a_price > level else (-1 if a_price < level else 0)
                dist = round((a_price - level) / level * 100.0, 3)
            row = {
                "id": "al_" + uuid.uuid4().hex[:10],
                "symbol": symbol,
                "type": atype,
                "price": level,
                "when": when.isoformat() if when else None,
                "when_disp": self._disp(when) if when else None,
                "note": (note or "").strip()[:280] or None,
                "state": ARMED,
                "armed_at": now.isoformat(),
                "armed_price": a_price,
                # side: +1 above the level, -1 below, 0 until the first tick.
                # A cross can only be called once a side is known.
                "side": side,
                "last": a_price,
                "dist_pct": dist,
            }
            self.rows.append(row)
            self.save()
            return row

    def cancel(self, aid):
        with self.lock:
            for r in self.rows:
                if r.get("id") == aid and r.get("state") == ARMED:
                    r["state"] = CANCELLED
                    r["closed_at"] = self.now().isoformat()
                    self.save()
                    return True
        return False

    def clear(self, state=FIRED):
        """Drop fired (or cancelled) rows. Never touches armed alerts."""
        if state == ARMED:
            return 0
        with self.lock:
            keep = [r for r in self.rows if r.get("state") != state]
            n = len(self.rows) - len(keep)
            if n:
                self.rows = keep
                self.save()
            return n

    def armed(self):
        with self.lock:
            return [r for r in self.rows if r.get("state") == ARMED]

    # -------------------------------------------------------------- trigger
    def check(self, price_fn, now=None):
        """Test every armed alert. Returns the rows that just fired.

        `price_fn(symbol)` returns the live price or None. A missing price never
        fires a price alert — it only leaves the alert armed.
        """
        now = now or self.now()
        fired = []
        with self.lock:
            for a in self.rows:
                if a.get("state") != ARMED:
                    continue
                atype = a.get("type")
                tgt = a.get("price")
                cur = None
                if tgt:
                    try:
                        cur = _f(price_fn(a.get("symbol")))
                    except Exception:
                        cur = None
                hit = None
                if tgt and cur:
                    side = int(a.get("side") or 0)
                    if atype == "CROSS UP":
                        if side < 0 and cur >= tgt:
                            hit = "price"
                    elif atype == "CROSS DOWN":
                        if side > 0 and cur <= tgt:
                            hit = "price"
                    elif atype == "ABOVE":
                        if cur >= tgt:
                            hit = "price"
                    elif atype == "BELOW":
                        if cur <= tgt:
                            hit = "price"
                    # record which side of the level we are on for the next cycle
                    a["side"] = 1 if cur > tgt else (-1 if cur < tgt else side)
                    a["last"] = cur
                    a["dist_pct"] = round((cur - tgt) / tgt * 100.0, 3)
                if not hit and a.get("when"):
                    try:
                        w = datetime.fromisoformat(a["when"])
                        if w.tzinfo is None:
                            w = w.replace(tzinfo=now.tzinfo)
                        if now >= w:
                            hit = "time"
                    except Exception:
                        pass
                if hit:
                    a["state"] = FIRED
                    a["fired_at"] = now.isoformat()
                    a["fired_at_disp"] = self._disp(now)
                    a["fired_reason"] = hit
                    a["fired_price"] = cur
                    fired.append(dict(a))
            if fired:
                self.save()
        return fired

    # ---------------------------------------------------------------- views
    @staticmethod
    def row_view(r, now=None):
        """JSON-safe row for the dashboard, with the clock shown on hunter time."""
        out = dict(r)
        if r.get("when") and not out.get("when_disp"):
            try:
                out["when_disp"] = AlertBook._disp(datetime.fromisoformat(r["when"]))
            except Exception:
                out["when_disp"] = r["when"]
        if r.get("fired_at") and not out.get("fired_at_disp"):
            try:
                out["fired_at_disp"] = AlertBook._disp(datetime.fromisoformat(r["fired_at"]))
            except Exception:
                out["fired_at_disp"] = r["fired_at"]
        return out

    def view(self, fired_limit=8):
        with self.lock:
            rows = list(self.rows)
        armed = [self.row_view(r) for r in rows if r.get("state") == ARMED]
        fired = [self.row_view(r) for r in rows if r.get("state") == FIRED]
        fired = fired[-fired_limit:][::-1]
        return {
            "armed": armed,
            "fired": fired,
            "counts": {"armed": len(armed), "fired": len(fired),
                       "cancelled": sum(1 for r in rows if r.get("state") == CANCELLED)},
        }
