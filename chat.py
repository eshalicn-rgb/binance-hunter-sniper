"""AI CEO ChatBrain for the Binance Hunter.

Consumes the TelegramTools registry (tg_tools.tools) to answer questions,
run hunter tools (status, pnl, positions, signals, watch, price, ta, regime,
risk, sweep, ledger, alerts, prepump, id, tools, help), and keeps a message
history exposed via /api/chat and /api/chat/history.

Uses Ollama (127.0.0.1:11434, qwen3.5:4b) for natural-language understanding
when available, falling back to keyword-based tool dispatch.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_TAGS = "http://127.0.0.1:11434/api/tags"
OLLAMA_MODEL = "qwen3.5:4b"
OLLAMA_TIMEOUT = 6

# Tools that take no positional args — call with []
NO_ARG_TOOLS = {
    "help", "status", "pnl", "positions", "signals", "top", "watch",
    "alerts", "ledger", "risk", "regime", "sweep", "id", "tools",
}
# Tools that take a single symbol arg
SYMBOL_TOOLS = {"price", "ta", "chart", "prepump"}


class ChatBrain:
    def __init__(self, tg_tools):
        self.tg_tools = tg_tools
        self.history = []  # list of {role, content, ts}
        self._ollama_ok = None  # probed lazily

    # ---------------------------------------------------------------- history
    def _add(self, role, content):
        self.history.append({"role": role, "content": content, "ts": time.time()})
        if len(self.history) > 80:
            self.history = self.history[-80:]

    def get_history(self):
        return list(self.history)

    def clear_history(self):
        self.history = []

    # ---------------------------------------------------------------- ollama
    def _ollama_available(self):
        if self._ollama_ok is not None:
            return self._ollama_ok
        try:
            req = urllib.request.Request(OLLAMA_TAGS, method="GET")
            with urllib.request.urlopen(req, timeout=3) as r:
                self._ollama_ok = (r.status == 200)
        except Exception:
            self._ollama_ok = False
        return self._ollama_ok

    def _ollama_chat(self, system, user_msg):
        if not self._ollama_available():
            return None
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 256},
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                OLLAMA_URL, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as r:
                body = json.loads(r.read().decode("utf-8"))
            return (body.get("message") or {}).get("content", "")
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return None

    # ---------------------------------------------------------- tool dispatch
    def _tool_names(self):
        return set(self.tg_tools.tools.keys()) if self.tg_tools else set()

    def _extract_symbol(self, message):
        """Pull a plausible symbol (BTCUSDT, ETH, PEPE…) from the message."""
        m = re.search(r"\b([A-Z]{2,10}(?:USDT|USDC|BUSD)?)(\b|$)", message.upper())
        if m:
            sym = m.group(1)
            if sym.endswith(("USDT", "USDC", "BUSD")) or len(sym) <= 5:
                return sym
        return None

    def _match_tool(self, message):
        """Keyword-based tool dispatch when Ollama isn't available."""
        m = message.lower().strip()
        tools = self.tg_tools.tools if self.tg_tools else {}
        aliases = getattr(self.tg_tools, "ALIASES", {})
        for k, v in aliases.items():
            if k in m:
                return v
        for name in tools:
            if name in m:
                return name
        return None

    def _call_tool(self, name, args=None):
        if not self.tg_tools:
            return {"error": "telegram tools unavailable"}
        try:
            return self.tg_tools.call(name, args)
        except Exception as exc:
            return {"error": f"tool {name} failed: {type(exc).__name__}: {exc}"}

    def _resolve_tool_and_args(self, message, used_ollama_tool=None):
        """Return (tool_name, args_list) for the message."""
        if used_ollama_tool:
            sym = self._extract_symbol(message)
            args = [sym] if (sym and used_ollama_tool in SYMBOL_TOOLS) else []
            return used_ollama_tool, args
        name = self._match_tool(message)
        if not name:
            return None, None
        sym = self._extract_symbol(message)
        if name in SYMBOL_TOOLS and sym:
            args = [sym]
        elif name in NO_ARG_TOOLS:
            args = []
        else:
            args = [sym] if sym else []
        return name, args

    # ---------------------------------------------------------------- process
    def process(self, message):
        """Process a user message.

        Returns {text, tool, tool_result, used_ollama}.
        """
        self._add("user", message)
        m = message.strip()
        if not m:
            reply = ("Ask me about the hunter: status, pnl, positions, signals, "
                     "watch, price, ta, regime, risk, sweep, ledger, alerts, "
                     "prepump, id, tools, help.")
            self._add("assistant", reply)
            return {"text": reply, "tool": None, "tool_result": None,
                    "used_ollama": False}

        tool_name = None
        tool_args = None
        tool_result = None
        reply = None
        used_ollama = False

        # Try Ollama first for natural-language understanding
        if self._ollama_available():
            system = (
                "You are the AI CEO of the Binance Hunter trading desk. "
                "The hunter is long-only (no shorts). Available tools: "
                + ", ".join(sorted(self._tool_names())) +
                ". If the user wants a tool invoked, reply with exactly: "
                "TOOL:<tool_name>\nOptionally add a symbol on the next line. "
                "Otherwise answer helpfully in one or two sentences."
            )
            ollama_reply = self._ollama_chat(system, m)
            if ollama_reply and ollama_reply.startswith("TOOL:"):
                used_ollama = True
                tool_name = ollama_reply.split(":", 1)[1].strip().split()[0]
                tool_result = self._call_tool(tool_name, tool_args)
                reply = self._format_tool_result(tool_name, tool_result)
            elif ollama_reply:
                used_ollama = True
                reply = ollama_reply

        # Keyword dispatch fallback (only if no tool selected and no reply yet)
        if tool_name is None and reply is None:
            tool_name, tool_args = self._resolve_tool_and_args(m)
            if tool_name:
                tool_result = self._call_tool(tool_name, tool_args)
                reply = self._format_tool_result(tool_name, tool_result)
            else:
                reply = ("I can help with: status, pnl, positions, signals, "
                         "watch, price <sym>, ta <sym>, regime, risk, sweep, "
                         "ledger, alerts, prepump <sym>, id, tools, help. "
                         "Try 'status' or 'signals'.")

        self._add("assistant", reply)
        return {"text": reply, "tool": tool_name, "tool_result": tool_result,
                "used_ollama": used_ollama}

    # ---------------------------------------------------------------- formatters
    def _format_tool_result(self, name, res):
        if isinstance(res, dict) and res.get("error"):
            return f"⚠️ {name}: {res['error']}"
        if isinstance(res, str):
            return res if res else "(no output)"
        if isinstance(res, dict):
            if name == "status":
                return self._fmt_status(res)
            if name == "pnl":
                return self._fmt_pnl(res)
            if name == "positions":
                return self._fmt_positions(res)
            if name == "signals":
                return self._fmt_signals(res)
            if name == "watch":
                return self._fmt_watch(res)
            if name == "price":
                return self._fmt_price(res)
            if name == "regime":
                return self._fmt_regime(res)
            if name == "risk":
                return self._fmt_risk(res)
            if name == "ledger":
                return self._fmt_ledger(res)
            if name == "tools":
                return self._fmt_tools(res)
            if name == "help":
                return self._fmt_help(res)
            return json.dumps(res, indent=2)[:2000]
        return str(res)[:2000]

    def _fmt_status(self, res):
        lines = ["🎯 Hunter Status"]
        for k in ("running", "positions", "trades_today", "pnl_today",
                  "balance", "target", "mode"):
            if k in res:
                lines.append(f"  {k}: {res[k]}")
        return "\n".join(lines)

    def _fmt_pnl(self, res):
        return f"💰 P&L: {json.dumps(res)[:700]}"

    def _fmt_positions(self, res):
        return f"📈 Positions: {json.dumps(res)[:900]}"

    def _fmt_signals(self, res):
        return f"📡 Signals: {json.dumps(res)[:900]}"

    def _fmt_watch(self, res):
        return f"👁 Watch: {json.dumps(res)[:900]}"

    def _fmt_price(self, res):
        return f"💲 Price: {json.dumps(res)[:700]}"

    def _fmt_regime(self, res):
        return f"🌐 Regime: {json.dumps(res)[:700]}"

    def _fmt_risk(self, res):
        return f"🛡️ Risk: {json.dumps(res)[:700]}"

    def _fmt_ledger(self, res):
        return f"📒 Ledger: {json.dumps(res)[:900]}"

    def _fmt_tools(self, res):
        return f"🛠️ Tools: {json.dumps(res)[:900]}"

    def _fmt_help(self, res):
        return ("🤖 AI CEO Chat — ask about: status, pnl, positions, signals, "
                "watch, price <sym>, ta <sym>, regime, risk, sweep, ledger, "
                "alerts, prepump <sym>, id, tools, help.")
