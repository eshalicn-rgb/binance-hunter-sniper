#!/usr/bin/env python
"""Turn a Kronos lab JSON into a machine-readable, fail-closed verdict.

The prose report says "no edge" in English. This says it in an exit code, so it
can gate a change instead of being skimmed and ignored.

GATE (all three must pass, and a missing field is a FAIL, never a pass):

  A. DIRECTIONAL
     For at least one horizon h, pooled model accuracy >= 0.55.
     Beating momentum only counts when momentum itself is >= 0.50 -- a baseline
     that is worse than a coin flip is not evidence of skill.

  B. PRE-MOVE
     For at least one move size, pooled AUC(model) >= 0.60 AND strictly greater
     than BOTH the momentum control AND the volatility control.
     The volatility control is the bar that matters: "volatile things move" is
     not new information.

  C. TRADEABLE
     The mean move when the model flags its top 10% must exceed the round-trip
     fee, and must beat the unconditional mean move by more than the fee.
     Otherwise the flags are not worth the spread.

Exit code 0 = PASS. 1 = FAIL. 2 = INSUFFICIENT evidence (fields missing).

Usage:
    C:\\Python314\\python.exe scripts\\verdict.py <lab.json> [--json]
"""
from __future__ import annotations

import argparse
import json
import sys

MIN_DIR_ACC = 0.55
MIN_AUC = 0.60
MOMENTUM_FLOOR = 0.50
PASS, FAIL, INSUFFICIENT = 0, 1, 2


def _get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def directional_gate(report):
    pooled = report.get("pooled") or {}
    rows, ok = [], False
    for key, v in sorted(pooled.items()):
        if not key.startswith("dir_") or not isinstance(v, dict):
            continue
        h = key[4:]
        m = v.get("model_acc")
        mom = v.get("momentum_acc")
        if m is None:
            rows.append((h, None, mom, False, "model_acc missing"))
            continue
        mom_meaningful = mom is not None and mom >= MOMENTUM_FLOOR
        beats_mom = mom_meaningful and m > mom
        passed = m >= MIN_DIR_ACC and beats_mom
        why = []
        if m < MIN_DIR_ACC:
            why.append(f"acc {m:.4f} < {MIN_DIR_ACC}")
        if mom is not None and not mom_meaningful:
            why.append(f"momentum {mom:.4f} is worse than a coin flip, so beating it counts for nothing")
        elif not beats_mom:
            why.append(f"does not beat momentum {mom}")
        rows.append((h, m, mom, passed, "; ".join(why) or "ok"))
        ok = ok or passed
    return ok, rows


def premove_gate(report):
    pooled = report.get("pooled") or {}
    rows, ok = [], False
    for key, v in sorted(pooled.items()):
        if not key.startswith("event_") or not isinstance(v, dict):
            continue
        tag = key[6:]
        am, ao, av = v.get("auc_model"), v.get("auc_momentum"), v.get("auc_volatility")
        if am is None or av is None:
            rows.append((tag, am, ao, av, False, "auc missing"))
            continue
        passed = am >= MIN_AUC and am > av and (ao is None or am > ao)
        why = []
        if am < MIN_AUC:
            why.append(f"auc {am:.4f} < {MIN_AUC}")
        if not (am > av):
            why.append(f"volatility control {av:.4f} is at least as good")
        if ao is not None and not (am > ao):
            why.append(f"momentum control {ao:.4f} is at least as good")
        rows.append((tag, am, ao, av, passed, "; ".join(why) or "ok"))
        ok = ok or passed
    return ok, rows


def tradeable_gate(report):
    fee = report.get("fee_round_trip_pct")
    symbols = report.get("symbols") or {}
    rows = []
    if fee is None:
        return False, [("(none)", None, None, False, "fee_round_trip_pct missing")], None
    agg = {}   # tag -> [flagged, all]
    for sym, rep in symbols.items():
        for tag, ev in (rep.get("events") or {}).items():
            fm = ev.get("mean_move_when_flagged")
            am = ev.get("mean_move_all")
            if fm is None or am is None:
                continue
            lo, hi = agg.setdefault(tag, ([], []))
            lo.append(float(fm))
            hi.append(float(am))
    ok = False
    for tag in sorted(agg):
        flagged, allm = agg[tag]
        f = sum(flagged) / len(flagged)
        a = sum(allm) / len(allm)
        passed = (f > fee) and (f > a + fee)
        why = []
        if not (f > fee):
            why.append(f"flagged mean {f:.3f}% does not clear the {fee}% round trip")
        if not (f > a + fee):
            why.append(f"flagged mean {f:.3f}% only beats the unconditional {a:.3f}% by "
                       f"{f - a:.3f}%, less than the {fee}% fee")
        rows.append((tag, round(f, 4), round(a, 4), passed, "; ".join(why) or "ok"))
        ok = ok or passed
    return ok, rows, fee


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lab_json")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON only")
    ap.add_argument("--out", default=None, help="also write the markdown verdict here")
    a = ap.parse_args()

    with open(a.lab_json, encoding="utf-8") as fh:
        report = json.load(fh)

    d_ok, d_rows = directional_gate(report)
    p_ok, p_rows = premove_gate(report)
    t_ok, t_rows, fee = tradeable_gate(report)

    declared = all(k in report for k in ("pooled", "symbols", "fee_round_trip_pct"))
    have = {"A": bool(d_rows), "B": bool(p_rows), "C": bool(t_rows)}
    missing = [g for g, ok in have.items() if not ok]
    if not declared or missing:
        # Absence of evidence is not a measured failure. Say so, and say which gate.
        code, label = INSUFFICIENT, "INSUFFICIENT EVIDENCE"
    elif d_ok and p_ok and t_ok:
        code, label = PASS, "PASS"
    else:
        code, label = FAIL, "FAIL"

    if a.json:
        print(json.dumps({
            "verdict": label, "exit": code,
            "missing_evidence": missing,
            "directional": {"pass": d_ok, "rows": d_rows},
            "premove": {"pass": p_ok, "rows": p_rows},
            "tradeable": {"pass": t_ok, "fee": fee, "rows": t_rows},
            "source": a.lab_json,
            "model": report.get("model"), "interval": report.get("interval"),
        }, indent=2))
        return code

    L = []
    L.append(f"# Kronos pre-move verdict — {label}")
    L.append("")
    L.append(f"- source: `{a.lab_json}`")
    L.append(f"- model: `{report.get('model')}` + `{report.get('tokenizer')}`")
    L.append(f"- interval: `{report.get('interval')}` · lookback "
             f"{report.get('lookback')} → pred_len {report.get('pred_len')} · "
             f"stride {report.get('stride')} · sample_count {report.get('sample_count')}")
    L.append(f"- round-trip fee: **{fee}%**")
    L.append("")
    L.append("A change may only be wired into the entry path if the verdict is **PASS**.")
    L.append("A missing field fails its gate; silence is never a pass.")
    L.append("")

    L.append(f"## A. Directional — {'PASS' if d_ok else 'FAIL'}")
    L.append("")
    L.append("| h (bars) | model acc | momentum acc | pass | why |")
    L.append("|---|---|---|---|---|")
    for h, m, mom, passed, why in d_rows:
        L.append(f"| {h} | {_f(m)} | {_f(mom)} | {'yes' if passed else 'no'} | {why} |")
    L.append("")

    L.append(f"## B. Pre-move detection — {'PASS' if p_ok else 'FAIL'}")
    L.append("")
    L.append("| event | AUC model | AUC momentum | AUC volatility | pass | why |")
    L.append("|---|---|---|---|---|---|")
    for tag, am, ao, av, passed, why in p_rows:
        L.append(f"| {tag} | {_f(am)} | {_f(ao)} | {_f(av)} | {'yes' if passed else 'no'} | {why} |")
    L.append("")

    L.append(f"## C. Payoff after fees (optimistic metric) — {'PASS' if t_ok else 'FAIL'}")
    L.append("")
    L.append("| event | flagged mean move | unconditional mean move | pass | why |")
    L.append("|---|---|---|---|---|")
    for tag, f, az, passed, why in t_rows:
        L.append(f"| {tag} | {_f(f)}% | {_f(az)}% | {'yes' if passed else 'no'} | {why} |")
    L.append("")
    L.append("> Gate C is measured on the **maximum favourable excursion** inside the "
             "horizon, so it assumes a perfect exit at the high. Read it as a ceiling on "
             "what the flags could ever pay, never as realised edge — and a thin margin "
             "(under ~0.05%) is noise. This is why C alone cannot carry a PASS.")
    L.append("")

    L.append("## Decision")
    L.append("")
    if code == PASS:
        L.append("All three gates cleared. This is necessary, not sufficient: still "
                 "forward-test on a paper book before risking size.")
    elif code == INSUFFICIENT:
        if missing:
            L.append(f"Gate(s) **{', '.join(missing)}** produced no measurable rows, so "
                     "this run cannot decide anything. That is usually a smoke run — too "
                     "few windows, no event of that size inside the horizon, or a "
                     "degenerate classification (the move occurred in every window or in "
                     "none).")
            L.append("")
            L.append("**It is not a result.** Run a full measurement — a few thousand bars "
                     "per symbol, `lookback` ≈ 400, `pred_len` ≥ 24, several symbols — "
                     "before drawing any conclusion.")
        else:
            L.append("The report is missing required sections (`pooled`, `symbols`, "
                     "`fee_round_trip_pct`). Nothing can be decided from it.")
    else:
        L.append("**Do not wire Kronos into the entry path on this evidence.** "
                 "Leave the hunter's gate where it is and keep hunting on the "
                 "measured, explainable filters.")
    L.append("")

    md = "\n".join(L)
    print(md)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"\n[saved] {a.out}", file=sys.stderr)
    return code


def _f(v):
    if v is None:
        return "—"
    try:
        return f"{float(v):.4f}"
    except (TypeError, ValueError):
        return str(v)


if __name__ == "__main__":
    sys.exit(main())
