#!/usr/bin/env python3
"""
SIGNAL FOLLOW-UP  —  fronttest (live) + backtest (replayed) for every signal we fire.

The engine fires signals from four entry paths. This module keeps up with them:

FRONTTEST
    every signal that fires is opened here with the price, direction, entry path and
    the timeframe it was hunted on. Each cycle the open signals are marked against
    real 1m klines, so MFE (max favourable excursion) and MAE (max adverse) are
    measured, not guessed. A signal resolves on the engine's own exits — +15% take
    profit, -5% stop — or times out after HORIZON_MIN minutes.

BACKTEST
    the same structural rule, replayed bar by bar over the symbol's own history.
    Every historical bar where the rule would have fired is entered at that close and
    carried forward under the identical TP / SL / horizon. The result is the base rate
    the live signal is being judged against — so "is this earning?" has an answer that
    does not depend on the last two trades.

Nothing is invented: an unmeasurable cell stays None.
"""
import json
import os
import time

import structure as S
import symbol_filter

TP = 15.0                 # take profit %, matches the engine
SL = 3.0                  # stop loss %, tightened from 5% for better R:R and expectancy
HORIZON_MIN = 90          # scalp: if it neither hits TP nor SL, leave after 90m — do not marry the trade
MAX_ROWS = 800
FEE_ROUND_TRIP = 0.20     # taker fee paid twice, in % — a replay that ignores it grades a market that does not exist

# --- trade-plan envelope: the four numbers that make a signal tradable -------
RISK_PER_TRADE = 0.02     # fraction of the balance risked on one entry (2%, matches .env)
MAX_POSITIONS = 3         # size is capped to an even balance slice
PLAN_MIN_RR = 2.0         # a plan below this reward:risk is not worth hunting (2:1 min for ~30% win rate)
TRAIL_AT_R = 0.7          # "eat and leave": arm the trail early, don't wait for +1R
TP_R = (1.0, 2.2, 3.5)    # scalp targets in R — tp2 at 2.2R clears PLAN_MIN_RR=2.0, improves expectancy
TRAIL_ATR_MULT = 0.6      # follow 0.6xATR behind the high
TRAIL_MIN_PCT = 0.005     # ...but never tighter than 0.5%
MIN_NOTIONAL_USD = 6.0    # Binance spot min is ~$5; keep a buffer so an order never rejects
MAX_POS_FRAC = 0.65       # never commit more than this share of equity to one entry


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def plan(analysis, balance=None, risk_pct=None, max_positions=MAX_POSITIONS):
    """The real hunting plan for one signal: entry, stop, targets, trail, size.

    Every level is derived from the structure / ATR the engine already computed —
    the structural trigger, the invalidation the swing actually broke, 1xATR for
    the trail — so the numbers are the trade, not decoration. When the structure
    gives nothing usable it falls back to ATR and still reports the source.
    """
    if not analysis:
        return None
    # A pegged asset (stablecoin / fiat / gold peg) or a tokenised equity has no
    # scalp to plan: a "pump" there is a peg wobble or a stock gapping. Refuse
    # here so no call site can accidentally build a tradable plan for one.
    if not symbol_filter.huntable(analysis.get("symbol")):
        return None
    st = analysis.get("struct") or {}
    px = _f(analysis.get("current_price")) or _f(st.get("price"))
    if px <= 0:
        return None
    atr = _f(st.get("atr")) or px * 0.01

    # entry — the structural trigger while it is still ahead of us, else market
    entry, entry_src = px, "market"
    trig = _f(st.get("trigger"))
    if 0 < (trig - px) / px <= 0.02:
        entry, entry_src = trig, "trigger"

    # stop — the invalidation the structure broke, else 1.5xATR, inside -5%..-0.4%
    stop, stop_src = None, None
    inv = _f(st.get("invalidation"))
    if 0 < inv < entry and (entry - inv) / entry <= SL / 100.0:
        stop, stop_src = inv, "invalidation"
    if stop is None:
        stop, stop_src = entry - 1.5 * atr, "1.5xATR"
    floor = entry * (1 - SL / 100.0)
    if stop < floor:
        stop, stop_src = floor, stop_src + " cap5%"
    ceil = entry * (1 - 0.004)
    if stop > ceil:
        stop, stop_src = ceil, stop_src + " min0.4%"
    stop = round(stop, 10)
    # never let a stop sit at or above entry for a long — that is an instant loss
    if stop >= entry:
        stop = entry * (1 - SL / 100.0)
        stop_src = "forced-below-entry"
    risk = entry - stop
    if risk <= 0:
        return None

    # targets — R multiples, with the structure's own measured move taking TP2
    tps = [entry + k * risk for k in TP_R]
    tgt = _f(st.get("target"))
    if tps[0] < tgt < tps[2]:
        tps[1] = tgt
    tps = sorted({round(t, 10) for t in tps if t > entry})[:3] or [round(entry + 2 * risk, 10)]
    tp1, tp2 = tps[0], tps[1] if len(tps) > 1 else tps[0]
    tp3 = tps[2] if len(tps) > 2 else tp2
    rr = round((tp2 - entry) / risk, 2)

    # trail — arm early, then follow 0.6xATR (or 0.5%) behind the high
    trail_arm = round(entry + TRAIL_AT_R * risk, 10)
    trail_dist = round(max(TRAIL_ATR_MULT * atr, entry * TRAIL_MIN_PCT), 10)

    # size — risk budget over the stop distance, lifted to the exchange floor (a
    # 10% slice of a micro account lands under the $5 min, so without the lift the
    # plan would describe an order Binance would reject) and capped so one entry
    # can never commit more than MAX_POS_FRAC of equity.
    bal = _f(balance, 0.0)
    risk_frac = RISK_PER_TRADE if risk_pct is None else risk_pct
    qty = notional = None
    if bal > 0:
        # only as many positions as the floor allows — a $9 account fits one $6 entry
        mp = max(1, min(int(max_positions), int(bal // MIN_NOTIONAL_USD) or 1))
        notional = (bal * risk_frac) * entry / risk
        cap = min(bal * MAX_POS_FRAC, bal / mp)
        notional = min(max(notional, MIN_NOTIONAL_USD), cap, bal)
        q = notional / entry
        qty, notional = round(q, 8), round(notional, 4)

    return {
        "entry": round(entry, 10), "entry_src": entry_src,
        "stop": stop, "stop_src": stop_src,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "trail_arm": trail_arm, "trail_dist": trail_dist,
        "risk_pct": round(risk / entry * 100.0, 3), "rr": rr,
        "qty": qty, "notional": notional, "atr": round(atr, 10),
        "tf": analysis.get("hunt_tf") or st.get("tf") or "1m",
        "valid": bool(entry > stop > 0 and rr >= PLAN_MIN_RR),
    }


MAX_ROWS = 400      # resolved rows are trimmed oldest-first once the ledger passes this


class SignalLedger:
    def __init__(self, path):
        self.path = path
        self.rows = self._load()
        self._bt = {}          # symbol -> {"ts": float, "result": dict}
        self.bt_ttl = 900

    # ---------------------------------------------------------------- storage
    def _load(self):
        try:
            with open(self.path, "r") as f:
                rows = json.load(f)
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    def save(self):
        try:
            with open(self.path, "w") as f:
                json.dump(self.rows[-MAX_ROWS:], f, indent=1)
        except Exception:
            pass

    # ---------------------------------------------------------------- record
    def record(self, symbol, direction, price, entry_type="order-flow",
               timeframe="1m", score=0, kind="watch", reasons=None,
               trigger=None, target=None, invalidation=None, state=None, ts=None,
               plan=None):
        """Open one signal for follow-up. Returns the row."""
        # long-only hunter: the ledger is the record of what we hunt, and we hunt
        # bullish setups only. A non-BUY direction can never enter it.
        if str(direction).upper() != "BUY":
            return None
        ts = ts or time.time()
        row = {
            "id": "%s-%d" % (symbol, int(ts)),
            "ts": ts,
            "symbol": symbol,
            "direction": direction,
            "entry_type": entry_type,
            "kind": kind,                     # "entry" (real trade) or "watch"
            "timeframe": timeframe,           # the timeframe this signal was hunted on
            "score": int(score or 0),
            "entry": round(_f(price), 10),
            "state": state,
            "trigger": trigger,
            "target": target,
            "invalidation": invalidation,
            "plan": plan,                     # entry / stop / tp1-3 / trail / size
            "reasons": (reasons or [])[:4],
            "status": "OPEN",
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
            "last_pct": 0.0,
            "last_px": round(_f(price), 10),
            "bars": 0,
            "resolved_ts": None,
            "outcome": None,
        }
        # one row per symbol, ever — signal OR prepump, never both at once
        for r in self.rows:
            if r.get("status") == "OPEN" and r.get("symbol") == symbol:
                return r
        self.rows.append(row)
        if len(self.rows) > MAX_ROWS:
            live = [r for r in self.rows if r.get("status") == "OPEN"]
            done = sorted((r for r in self.rows if r.get("status") != "OPEN"),
                          key=lambda r: -_f(r.get("ts")))
            self.rows = live + done[:max(0, MAX_ROWS - len(live))]
        self.save()
        return row

    # ---------------------------------------------------------------- marking
    def mark(self, symbol, klines, tf_min=1, now=None):
        """Mark every OPEN row for one symbol against real klines since its signal time.

        Resolution is bar-by-bar, so whichever of TP / SL was actually touched first
        is the one that resolves the signal — the same rule the backtest replays.
        """
        now = now or time.time()
        open_rows = [r for r in self.rows if r.get("status") == "OPEN" and r.get("symbol") == symbol]
        if not open_rows or not klines:
            return 0
        touched = 0
        for r in open_rows:
            start_ms = _f(r.get("ts")) * 1000.0
            bars = [k for k in klines if _f(k[0]) >= start_ms]
            if not bars:
                continue
            entry = _f(r.get("entry"))
            if entry <= 0:
                continue
            sign = 1.0 if r.get("direction") == "BUY" else -1.0
            hi = max(_f(k[2]) for k in bars)
            lo = min(_f(k[3]) for k in bars)
            mfe = (hi - entry) / entry * 100.0 if sign > 0 else (entry - lo) / entry * 100.0
            mae = (lo - entry) / entry * 100.0 if sign > 0 else (entry - hi) / entry * 100.0
            last = (_f(bars[-1][4]) - entry) / entry * 100.0 * sign
            r["mfe_pct"] = round(max(mfe, 0.0), 3)
            r["mae_pct"] = round(min(mae, 0.0), 3)
            r["last_pct"] = round(last, 3)
            r["last_px"] = round(_f(bars[-1][4]), 10)
            r["bars"] = len(bars)
            touched += 1

            # resolve against the plan's own levels when one was recorded,
            # falling back to the engine's flat +TP/-SL envelope
            pl = r.get("plan") or {}
            tp_px = _f(pl.get("tp2")) or (entry * (1 + TP / 100.0) if sign > 0 else entry * (1 - TP / 100.0))
            sl_px = _f(pl.get("stop")) or (entry * (1 - SL / 100.0) if sign > 0 else entry * (1 + SL / 100.0))
            # a plan level on the wrong side of the entry is meaningless; fall back to
            # the engine's flat envelope rather than inventing a phantom stop that
            # would resolve as a "win" the moment the row opens
            if sign > 0:
                if not (0 < sl_px < entry):
                    sl_px = entry * (1 - SL / 100.0)
                if not (tp_px > entry):
                    tp_px = entry * (1 + TP / 100.0)
            else:
                if not (sl_px > entry):
                    sl_px = entry * (1 + SL / 100.0)
                if not (0 < tp_px < entry):
                    tp_px = entry * (1 - TP / 100.0)
            arm = _f(pl.get("trail_arm"))
            dist = _f(pl.get("trail_dist"))
            run_hi = entry
            for b in bars:
                b_hi, b_lo = _f(b[2]), _f(b[3])
                hit_tp = (b_hi >= tp_px) if sign > 0 else (b_lo <= tp_px)
                hit_sl = (b_lo <= sl_px) if sign > 0 else (b_hi >= sl_px)
                # ONE BAR CANNOT BE ORDERED. When a single minute spans both the stop
                # and the target there is no tick data to say which came first, and
                # grading it as the win (as this used to) hands the strategy a free
                # victory on every ambiguous bar. The stop is the only defensible
                # answer: it is the pessimistic half of the ambiguity, so a measured
                # edge has to survive a world where the coin lands wrong.
                if hit_sl:
                    r.update(status="SL", outcome=round((sl_px - entry) / entry * 100.0 * sign, 3),
                             resolved_ts=now)
                    break
                if hit_tp:
                    r.update(status="TP", outcome=round((tp_px - entry) / entry * 100.0 * sign, 3),
                             resolved_ts=now)
                    break
                if sign > 0 and arm > 0 and dist > 0:
                    run_hi = max(run_hi, b_hi)
                    if run_hi >= arm and b_lo <= run_hi - dist:
                        px_out = run_hi - dist
                        r.update(status="TRAIL",
                                 outcome=round((px_out - entry) / entry * 100.0, 3),
                                 resolved_ts=now)
                        break
            else:
                if (now - _f(r.get("ts"))) / 60.0 >= HORIZON_MIN * max(1, tf_min):
                    r.update(status="TIMEOUT", outcome=round(last, 3), resolved_ts=now)
        if touched:
            self.save()
        return touched

    def expire(self, now=None):
        """Time-based expiry for signals we never got klines for."""
        now = now or time.time()
        n = 0
        for r in self.rows:
            if r.get("status") == "OPEN" and (now - _f(r.get("ts"))) / 60.0 >= HORIZON_MIN * 4:
                r["status"] = "TIMEOUT"
                r["outcome"] = round(_f(r.get("last_pct")), 3)
                r["resolved_ts"] = now
                n += 1
        if n:
            self.save()
        return n

    # ---------------------------------------------------------------- time in trade
    @staticmethod
    def _dur(now, ts):
        """Minutes from `ts` to `now`, to one decimal. None if either is usable-but-absent.

        This is the holding duration the dashboard shows: `resolved_ts - ts` for a
        resolved row, `now - ts` for one still open. An unmeasurable span stays None.
        """
        if not now or not ts:
            return None
        return round((_f(now) - _f(ts)) / 60.0, 1)

    @classmethod
    def _follow_row(cls, r, now):
        """One Signal Follow-Up row: the plan's levels plus when it was sent and for how long."""
        pl = r.get("plan") or {}
        closed = r.get("status") != "OPEN"
        return {
            "symbol": r.get("symbol"), "direction": r.get("direction"),
            "kind": r.get("kind"), "tf": r.get("timeframe"),
            "score": r.get("score"), "entry_type": r.get("entry_type"),
            "entry": r.get("entry"), "stop": pl.get("stop"), "tp2": pl.get("tp2"),
            "status": r.get("status"), "outcome": r.get("outcome"),
            "ts": r.get("ts"), "resolved_ts": r.get("resolved_ts"),
            # a resolved row carries how long it was held; an open row how long it has been live
            "hold_min": cls._dur(r.get("resolved_ts"), r.get("ts")) if closed else None,
            "age_min": None if closed else cls._dur(now, r.get("ts")),
        }

    # ---------------------------------------------------------------- fronttest stats
    def summary(self):
        rows = self.rows
        open_rows = [r for r in rows if r.get("status") == "OPEN"]
        done = [r for r in rows if r.get("status") != "OPEN"]
        wins = [r for r in done if _f(r.get("outcome")) > 0]
        losses = [r for r in done if _f(r.get("outcome")) < 0]
        outs = [_f(r.get("outcome")) for r in done]
        gross_w = sum(o for o in outs if o > 0)
        gross_l = -sum(o for o in outs if o < 0)
        tail = sorted(rows, key=lambda r: -_f(r.get("ts")))[:30]
        now = time.time()
        # the follow-up table: what is live right now (newest first), then what has
        # since resolved (newest first) — so entry -> exit time is readable per row
        follow = ([self._follow_row(r, now) for r in sorted(open_rows, key=lambda r: -_f(r.get("ts")))]
                  + [self._follow_row(r, now) for r in sorted(done, key=lambda r: -_f(r.get("ts")))])[:24]
        return {
            "total": len(rows),
            "open": len(open_rows),
            "closed": len(done),
            "wins": len(wins),
            "losses": len(losses),
            "tp": sum(1 for r in done if r.get("status") == "TP"),
            "sl": sum(1 for r in done if r.get("status") == "SL"),
            "trail": sum(1 for r in done if r.get("status") == "TRAIL"),
            "timeout": sum(1 for r in done if r.get("status") == "TIMEOUT"),
            "win_rate": round(len(wins) / len(done) * 100.0, 1) if done else None,
            "avg_ret": round(sum(outs) / len(outs), 3) if outs else None,
            "expectancy": round((gross_w - gross_l) / len(done), 3) if done else None,
            "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else None,
            "avg_mfe": round(sum(_f(r.get("mfe_pct")) for r in rows) / len(rows), 3) if rows else None,
            "avg_mae": round(sum(_f(r.get("mae_pct")) for r in rows) / len(rows), 3) if rows else None,
            "best": round(max(outs), 3) if outs else None,
            "worst": round(min(outs), 3) if outs else None,
            "by_type": self._by_type(done),
            "open_rows": sorted(open_rows, key=lambda r: -_f(r.get("ts")))[:14],
            "recent": tail[:16],
            "follow": follow,
            "follow_closed": sum(1 for r in follow if r.get("status") != "OPEN"),
        }

    @staticmethod
    def _by_type(done):
        agg = {}
        for r in done:
            k = r.get("entry_type") or "?"
            a = agg.setdefault(k, {"n": 0, "wins": 0, "sum": 0.0})
            a["n"] += 1
            a["sum"] += _f(r.get("outcome"))
            if _f(r.get("outcome")) > 0:
                a["wins"] += 1
        return {k: {"n": v["n"], "win_rate": round(v["wins"] / v["n"] * 100.0, 1),
                    "avg": round(v["sum"] / v["n"], 3)} for k, v in agg.items()}

    # ---------------------------------------------------------------- backtest
    def backtest(self, symbol, klines, tf="1m", tf_min=1, stride=1, min_score=None,
                 warmup=60, horizon=None):
        """Replay the structural rule over the symbol's own history.

        Enters at the close of every bar where `structure.hunt` would have fired,
        then carries forward under the identical TP / SL / horizon. Cached for
        `bt_ttl` seconds so the engine can call it every cycle for free.
        """
        if not klines or len(klines) < warmup + 20:
            return None
        horizon = horizon or max(6, HORIZON_MIN // max(1, tf_min))
        thr = S.STRUCT_MIN if min_score is None else min_score
        trades = []
        n = len(klines)
        i = warmup
        while i < n - 2:
            kk = klines[:i + 1]
            try:
                r = S.hunt(symbol, kk, tf)
            except Exception:
                r = None
            if r and S.bullish_gate(r)[0]:
                entry = _f(kk[-1][4])
                if entry <= 0:
                    i += stride
                    continue
                tp_px = entry * (1 + TP / 100.0)
                sl_px = entry * (1 - SL / 100.0)
                fwd = klines[i + 1:i + 1 + horizon]
                out = None
                for b in fwd:
                    # the stop is tested first: one bar that spans both levels cannot be
                    # ordered without tick data, and the optimistic reading is exactly
                    # how a backtest lies to you
                    if _f(b[3]) <= sl_px:
                        out = -SL
                        break
                    if _f(b[2]) >= tp_px:
                        out = TP
                        break
                if out is None:
                    last = _f(fwd[-1][4]) if fwd else entry
                    out = round((last - entry) / entry * 100.0, 3)
                # friction: a round trip pays the taker fee twice
                out = round(_f(out) - FEE_ROUND_TRIP, 3)
                trades.append({"i": i, "ts": _f(kk[-1][0]), "entry": round(entry, 10),
                               "outcome": round(_f(out), 3), "score": r["score"],
                               "tf": tf, "state": r.get("state")})
            i += stride

        wins = [t for t in trades if t["outcome"] > 0]
        losses = [t for t in trades if t["outcome"] < 0]
        outs = [t["outcome"] for t in trades]
        gross_w = sum(o for o in outs if o > 0)
        gross_l = -sum(o for o in outs if o < 0)
        res = {
            "symbol": symbol, "tf": tf, "bars": n, "horizon": horizon,
            "threshold": thr,
            "trades": len(trades), "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100.0, 1) if trades else None,
            "avg_ret": round(sum(outs) / len(outs), 3) if outs else None,
            "expectancy": round((gross_w - gross_l) / len(trades), 3) if trades else None,
            "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else None,
            "best": round(max(outs), 3) if outs else None,
            "worst": round(min(outs), 3) if outs else None,
            "gross_w": round(gross_w, 3), "gross_l": round(gross_l, 3),
            "ts": time.time(),
        }
        self._bt[symbol] = res
        return res

    def cached_backtest(self, symbol):
        r = self._bt.get(symbol)
        if r and time.time() - r.get("ts", 0) < self.bt_ttl:
            return r
        return None

    @staticmethod
    def _aggregate(res):
        """Pool per-symbol backtests honestly, and show the spread.

        Profit factor is pooled gross profit / gross loss, never the mean of the
        per-symbol ratios -- averaging ratios lets a handful of trades on one
        symbol dominate. Dispersion (median, share of profitable symbols, best and
        worst symbol) is reported alongside, so a base rate carried by a single
        flattering symbol cannot hide inside the average.
        """
        tot = sum(r["trades"] for r in res)
        wins = sum(r["wins"] for r in res)
        gw = sum(_f(r.get("gross_w")) for r in res)
        gl = sum(_f(r.get("gross_l")) for r in res)
        outs = sorted(_f(r["avg_ret"]) for r in res if r.get("avg_ret") is not None)
        exp = [_f(r["expectancy"]) for r in res if r.get("expectancy") is not None]
        med = outs[len(outs) // 2] if outs else None
        ranked = sorted(res, key=lambda r: -_f(r.get("avg_ret")))
        return {
            "symbols": len(res), "trades": tot,
            "win_rate": round(wins / tot * 100.0, 1) if tot else None,
            "avg_ret": round(sum(outs) / len(outs), 3) if outs else None,
            "median_ret": round(med, 3) if med is not None else None,
            "expectancy": round(sum(exp) / len(exp), 3) if exp else None,
            "profit_factor": round(gw / gl, 2) if gl > 0 else None,
            "pct_profitable": round(len([o for o in outs if o > 0]) / len(outs) * 100.0, 1) if outs else None,
            "best_sym": ({"symbol": ranked[0]["symbol"], "avg_ret": ranked[0].get("avg_ret")}
                         if ranked else None),
            "worst_sym": ({"symbol": ranked[-1]["symbol"], "avg_ret": ranked[-1].get("avg_ret")}
                          if ranked else None),
        }

    def backtest_summary(self):
        """Aggregate every cached backtest into one base-rate line."""
        res = [r for r in self._bt.values() if r and r.get("trades")]
        if not res:
            return None
        return dict(self._aggregate(res), per_symbol=sorted(
            [{"symbol": r.get("symbol"), "trades": r.get("trades", 0),
              "win_rate": r.get("win_rate"), "avg_ret": r.get("avg_ret"),
              "tf": r.get("tf")} for r in res],
            key=lambda x: -(x["avg_ret"] or 0))[:12])

    # ---------------------------------------------------------------- live plans
    def open_plans(self):
        """The plan behind every OPEN row — the trade currently being hunted."""
        now = time.time()
        out = []
        for r in self.rows:
            if r.get("status") != "OPEN":
                continue
            pl = r.get("plan") or {}
            out.append({
                "symbol": r.get("symbol"), "direction": r.get("direction"),
                "kind": r.get("kind"), "tf": r.get("timeframe"),
                "score": r.get("score"), "entry_type": r.get("entry_type"),
                "entry": r.get("entry"), "stop": pl.get("stop"),
                "tp1": pl.get("tp1"), "tp2": pl.get("tp2"), "tp3": pl.get("tp3"),
                "trail_arm": pl.get("trail_arm"), "trail_dist": pl.get("trail_dist"),
                "rr": pl.get("rr"), "risk_pct": pl.get("risk_pct"),
                "qty": pl.get("qty"), "notional": pl.get("notional"),
                "plan_valid": pl.get("valid"), "ts": r.get("ts"),
                "resolved_ts": r.get("resolved_ts"),
                "age_min": self._dur(now, r.get("ts")),
                "last_pct": r.get("last_pct"), "mfe_pct": r.get("mfe_pct"),
                "mae_pct": r.get("mae_pct"), "bars": r.get("bars"),
            })
        return sorted(out, key=lambda x: -_f(x.get("score")))

    # ---------------------------------------------------------------- sweep
    def backtest_all(self, symbols, klines_for, tf="1m", tf_min=1, stride=3,
                     warmup=60, horizon=None, limit=6):
        """Replay the structural rule across a whole universe and aggregate.

        `klines_for(symbol)` must return real klines or None. The result is the
        base rate across the universe plus a per-symbol table — the honest answer
        to "does this rule earn?". A symbol we cannot fetch is counted as skipped,
        never as a win.
        """
        ran, skipped = [], []
        for sym in list(symbols)[:max(1, limit)]:
            try:
                kl = klines_for(sym)
            except Exception:
                kl = None
            if not kl or len(kl) < warmup + 20:
                skipped.append(sym)
                continue
            r = self.backtest(sym, kl, tf=tf, tf_min=tf_min, stride=stride,
                              warmup=warmup, horizon=horizon)
            if r and r.get("trades"):
                ran.append(r)
            else:
                skipped.append(sym)
        if not ran:
            return {"symbols": 0, "ran": [], "skipped": skipped, "trades": 0, "ts": time.time()}
        out = self._aggregate(ran)
        out.update({
            "skipped": skipped,
            "ts": time.time(),
            "ran": sorted(
                [{"symbol": r["symbol"], "trades": r["trades"], "win_rate": r["win_rate"],
                  "avg_ret": r["avg_ret"], "expectancy": r["expectancy"], "tf": r["tf"]}
                 for r in ran], key=lambda x: -(x["avg_ret"] or 0)),
        })
        return out
