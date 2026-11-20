"""Crypto market regime gate — wraps the ``crypto-regime-analyzer`` skill.

The regime score describes whether the market supports risk at all (broad
participation, healthy trend, sane leverage). It is a *risk control*, never a
signal: it can only BLOCK new entries, it can never create one. When the market
regime reads RISK_OFF the hunter stands down; when it is NEUTRAL or RISK_ON the
hunter is free to hunt exactly as it does today.

The analyzer's live run fetches CoinGecko + Binance and can take 2-4 minutes, so
it is refreshed on a background daemon thread behind a long throttle. The last
good result is cached to disk so an engine restart does not lose it, and a stale
or missing result fails *open* for NEUTRAL (we do not stall trading on a data
outage) but is always visible on the dashboard.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

SKILL_DIR = os.environ.get(
    "CRYPTO_REGIME_DIR",
    r"C:\Users\BSArt\.agents\skills\crypto-regime-analyzer",
)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "crypto_regime_analyzer.py")
HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(HERE, "reports", "regime")
CACHE_FILE = os.path.join(REPORT_DIR, "last_regime.json")

TTL_SEC = 1800          # re-run the analyzer at most every 30 minutes
RUN_TIMEOUT = 600       # the live fetch is slow; give it room
VALID_ZONES = ("RISK_ON", "NEUTRAL", "RISK_OFF")


def _find_python() -> str:
    for c in (sys.executable, r"C:\Python314\python.exe", "python"):
        if c and (os.path.exists(c) or c == "python"):
            return c
    return "python"


class RegimeGate:
    """Throttled, background-refreshed crypto market regime."""

    def __init__(self, script=SCRIPT, ttl=TTL_SEC, enabled=True,
                 block_on_risk_off=True):
        self.script = script
        self.ttl = ttl
        self.enabled = bool(enabled) and os.path.exists(script)
        self.python = _find_python()
        self.block_on_risk_off = block_on_risk_off
        self.lock = threading.Lock()
        self.zone = "UNKNOWN"
        self.score = None
        self.guidance = ""
        self.updated = 0.0
        self.duration = None
        self.error = ""
        self.runs = 0
        self._inflight = False
        self._load_cache()

    # ------------------------------------------------------------------ cache
    def _load_cache(self):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.zone = d.get("zone", "UNKNOWN")
            self.score = d.get("score")
            self.guidance = d.get("guidance", "")
            self.updated = float(d.get("updated", 0) or 0)
        except Exception:
            pass

    def _save_cache(self):
        try:
            os.makedirs(REPORT_DIR, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"zone": self.zone, "score": self.score,
                           "guidance": self.guidance, "updated": self.updated}, f)
        except Exception:
            pass

    # ---------------------------------------------------------------- refresh
    def refresh(self, force=False):
        if not self.enabled:
            return False
        now = time.time()
        with self.lock:
            if self._inflight:
                return False
            if not force and now - self.updated < self.ttl:
                return False
            self._inflight = True
        t0 = time.time()
        try:
            os.makedirs(REPORT_DIR, exist_ok=True)
            proc = subprocess.run(
                [self.python, self.script, "--output-dir", REPORT_DIR,
                 "--cache-dir", os.path.join(REPORT_DIR, "cache"),
                 "--top-n", "20", "--quiet"],
                capture_output=True, text=True, timeout=RUN_TIMEOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                # Parent is pythonw.exe: without this every refresh allocates a
                # fresh console window. Never remove this flag on Windows.
                **({} if sys.platform != "win32" else
                   {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}),
            )
            self.runs += 1
            jf = os.path.join(REPORT_DIR, "crypto_regime.json")
            if os.path.exists(jf):
                with open(jf, "r", encoding="utf-8") as f:
                    d = json.load(f)
                comp = d.get("composite") or {}
                with self.lock:
                    self.zone = str(comp.get("zone") or "UNKNOWN").upper()
                    self.score = comp.get("score")
                    self.guidance = comp.get("guidance") or ""
                    self.updated = time.time()
                    self.duration = round(time.time() - t0, 1)
                    self.error = ""
                self._save_cache()
                return True
            self.error = (proc.stderr or proc.stdout or "no report")[:160]
            return False
        except Exception as e:
            self.error = str(e)[:160]
            return False
        finally:
            with self.lock:
                self._inflight = False

    def maybe_refresh_async(self):
        if not self.enabled or time.time() - self.updated < self.ttl:
            return
        with self.lock:
            if self._inflight:
                return
        threading.Thread(target=self.refresh, kwargs={"force": True},
                         daemon=True, name="regime-refresh").start()

    # ----------------------------------------------------------------- policy
    def allow_entries(self):
        """RISK_OFF stands the hunter down; anything else (including UNKNOWN after
        an outage) leaves it free — this is documented fail-open, and the state is
        always displayed."""
        if not self.enabled or not self.block_on_risk_off:
            return True, "gate off"
        with self.lock:
            z = self.zone
        if z == "RISK_OFF":
            return False, f"market regime {z}" + (f" {self.score:.0f}" if self.score is not None else "")
        return True, f"regime {z}" + (f" {self.score:.0f}" if self.score is not None else "")

    def snapshot(self):
        with self.lock:
            age = time.time() - self.updated if self.updated else None
            return {
                "enabled": self.enabled,
                "zone": self.zone,
                "score": self.score,
                "guidance": self.guidance,
                "age_sec": round(age, 1) if age is not None else None,
                "stale": (age is None or age > self.ttl * 2),
                "duration_sec": self.duration,
                "runs": self.runs,
                "error": self.error,
            }


if __name__ == "__main__":   # manual smoke: python regime.py  (slow on first run)
    g = RegimeGate()
    print("cached:", g.snapshot())
    ok = g.refresh(force=True)
    print("refreshed:", ok, g.snapshot())
