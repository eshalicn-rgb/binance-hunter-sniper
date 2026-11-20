import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["HUNTER_TZ"] = "Asia/Riyadh"
import notify

print(notify.card_signal(
    "LINKUSDT", "BUY", 71, "pre-pump",
    price=22.4183, vol=14.19, mom=-0.07, imb=-0.02,
    ta_bias="NEUTRAL", ta_score=45, flags=["whale-"], tf="5m"))
print()
print(notify.card_signal(
    "TROLLSOLUSDT", "BUY", 88, "structure-breakout",
    price=0.00001234, vol=6.5, mom=3.4, imb=0.71,
    ta_bias="BULLISH", ta_score=72, flags=["trend", "oi+"],
    structure="BOS up 78", tf="15m"))
print()
print(notify.card_entry(
    {"symbol": "ARBUSDT", "side": "BUY", "entry_price": 0.4213, "quantity": 12.0,
     "order_flow_score": 84, "volume_ratio": 5.2, "order_id": 8812341,
     "timestamp": None},
    {"ta": {"bias": "BULLISH", "score": 70},
     "struct": {"tf": "5m", "state": "BOS up", "score": 78},
     "feed_flags": ["whale+", "trending"]}, "pre-pump"))
print()
print(notify.card_exit(
    {"symbol": "ARBUSDT", "side": "BUY", "entry_price": 0.4213, "exit_price": 0.4845,
     "held": "2h 14m"}, 0.7584, 15.0, "TAKE PROFIT +15%"))
print()
print(notify.card_alert("BTCUSDT", "BUY", 81114.63, "CROSS UP", 2.55))
print()
print(notify.card_alert("ETHUSDT", "SELL", 2498.11, "CROSS DOWN", -1.82))

# --- assertions: a CROSS UP is a BUY, a CROSS DOWN is a SELL, in every card ---
up = notify.card_alert("BTCUSDT", "BUY", 81114.63, "CROSS UP", 2.55)
dn = notify.card_alert("ETHUSDT", "SELL", 2498.11, "CROSS DOWN", -1.82)
assert "ALERT" in up and "CROSS UP" in up and "BUY" in up, "cross-up card malformed"
assert "ALERT" in dn and "CROSS DOWN" in dn and "SELL" in dn, "cross-down card malformed"
# a SIGNAL card is long-only: the side must never read SELL
sig = notify.card_signal(
    "SOLUSDT", "BUY", 66, "pre-pump", price=141.02, vol=3.1, mom=0.9, imb=0.64,
    ta_bias="LONG", ta_score=66, flags=["whale+"], tf="5m")
assert "SIDE      BUY" in sig, "signal card side is not BUY"
assert "SELL" not in sig, "signal card leaked a SELL side"

# --- CROSS UP with a real text note: wrapped to the box, never clipped mid-note
NOTE = ("weekly resistance 148.5 breached on 4h, volume 3.1x, watching for a "
        "retest of 141 then continuation")
note_card = notify.card_alert("SOLUSDT", "BUY", 141.02, "CROSS UP", 3.1, note=NOTE)
print(note_card)
box = "\n".join(l for l in note_card.split("\n") if l.startswith("\u2502"))
assert "TEXT" in box, "note row missing from the alert card"
assert all(w in box for w in NOTE.split()), "a note word was lost"
assert all(len(l) <= 36 for l in box.split("\n")), "a note line overflowed the box"

# --- escaping: angle brackets/ampersands are neutralised, never emitted raw ---
def _box(card_text):
    return "\n".join(l for l in card_text.split("\n") if l.startswith("\u2502"))

sbox = _box(notify.card_alert("SOLUSDT", "BUY", 141.02, "CROSS UP", note="<b>"))
assert "<b>" not in sbox, "raw angle brackets leaked into the card"
assert "&lt;b&gt;" in sbox, "escaped angle brackets missing"

abox = _box(notify.card_alert("SOLUSDT", "BUY", 141.02, "CROSS UP", note="a & b"))
assert "&amp;" in abox, "ampersand was not escaped"

# a long note full of special characters must still be valid HTML inside the box
ebox = _box(notify.card_alert("SOLUSDT", "BUY", 141.02, "CROSS UP",
                              note="break <b>bold</b> & <i>italic</i> 12 < 15 and more <text> here"))
assert "<b>" not in ebox and "<i>" not in ebox and "<text>" not in ebox, "note was not escaped"
import re as _re
bad = _re.findall(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#\d+|#x[0-9a-fA-F]+);)", ebox)
assert not bad, "broken HTML entity emitted: " + repr(bad[:3])
assert all(len(l) <= 36 for l in ebox.split("\n")), "escaped note overflowed the box"

print("\nCARD TESTS PASSED")
