#!/usr/bin/env python3
"""
SWARM COORDINATOR - Multi-agent trading coordination for GrokMT5Bot + Binance Hunter
Agents communicate via shared decisions.jsonl blackboard and swarm_state.json state.
Consensus: majority vote on entry, unanimous on exit.
"""
import os, json, time, threading, datetime as dt
from collections import defaultdict

BOT = os.path.dirname(os.path.abspath(__file__).rsplit('\\', 1)[0]) if '\\' in __file__ else os.path.dirname(os.path.abspath(__file__))
SWARM_DIR = os.path.join(BOT, 'swarm')
STATE_FILE = os.path.join(SWARM_DIR, 'swarm_state.json')
DECISIONS_FILE = os.path.join(SWARM_DIR, 'decisions.jsonl')
AGENTS_FILE = os.path.join(SWARM_DIR, 'agents.json')

os.makedirs(SWARM_DIR, exist_ok=True)

AGENT_ROLES = {
    'coordinator': 'Swarm Coordinator',
    'scanner': 'Market Scanner',
    'analyst': 'Signal Analyst',
    'newsdesk': 'News & Social Desk',
    'quant': 'Fibonacci & Gann Quant',
    'whale': 'Whale Watcher',
    'risk_guard': 'Risk Manager',
    'executor': 'Execution Agent',
    'portfolio': 'Portfolio Manager',
    'dashboard': 'Dashboard Monitor',
}

# Trading-agent skills installed project-local under .agents/skills, mapped onto the
# role that actually exercises them. Every name here must exist on disk or the agent
# carries a skill it cannot use, so keep this list in step with the installs.
AGENT_SKILLS = {
    'coordinator': ['vibe-trading', 'crypto-regime-analyzer'],
    'scanner':     ['crypto-market-rank', 'trading-signal'],
    'analyst':     ['crypto-market-rank', 'crypto-regime-analyzer'],
    'newsdesk':    ['crypto-market-rank'],
    'quant':       ['crypto-regime-analyzer', 'vibe-trading'],
    'whale':       ['gmgn-track', 'gmgn-portfolio'],
    'risk_guard':  ['llm-trading-agent-security', 'position-sizer'],
    'executor':    ['llm-trading-agent-security', 'crypto-trading-bots'],
    'portfolio':   ['position-sizer', 'gmgn-portfolio'],
    'dashboard':   [],
}


class SwarmCoordinator:
    def __init__(self):
        self.state = self._load_state()
        self.agents = self._load_agents()
        self.lock = threading.Lock()
        self.heartbeat_timeout = 120  # seconds (a full-market sweep can run ~60s between beats)
    
    def _load_state(self):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {
                'created': dt.datetime.now(dt.timezone.utc).isoformat(),
                'agents': {},
                'consensus': [],
                'metrics': {'signals': 0, 'entries': 0, 'exits': 0, 'rejections': 0},
                'target_reached': False,
            }
    
    def _save_state(self):
        try:
            with open(STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"[SWARM] Save state error: {e}")
    
    def _load_agents(self):
        try:
            with open(AGENTS_FILE, 'r') as f:
                agents = json.load(f)
        except Exception:
            agents = {}
        # self-migrate: any role added since this file was written appears automatically
        for role, label in AGENT_ROLES.items():
            agents.setdefault(role, {'status': 'offline', 'last_hb': 0, 'role': label, 'tasks': 0})
            # keep each agent's skill loadout current as skills are installed
            agents[role]['skills'] = list(AGENT_SKILLS.get(role, []))
        return agents
    
    def _save_agents(self):
        try:
            with open(AGENTS_FILE, 'w') as f:
                json.dump(self.agents, f, indent=2)
        except Exception:
            pass
    
    def _bump(self, agent_name):
        """Count a piece of real work on an agent and refresh its liveness.

        Every record_* method calls this, so an agent's task count reflects the
        work it actually filed — not a hand-picked list of bump sites. Must be
        called while holding self.lock.
        """
        if agent_name in self.agents:
            self.agents[agent_name]['tasks'] = self.agents[agent_name].get('tasks', 0) + 1
            self.agents[agent_name]['last_hb'] = time.time()
            self.agents[agent_name]['status'] = 'online'

    def heartbeat(self, agent_name, bump=False):
        """Agent heartbeats to stay alive in swarm. bump=True records a completed task."""
        with self.lock:
            if agent_name in self.agents:
                self.agents[agent_name]['last_hb'] = time.time()
                self.agents[agent_name]['status'] = 'online'
                if bump:
                    self.agents[agent_name]['tasks'] = self.agents[agent_name].get('tasks', 0) + 1
                self._save_agents()
    
    def is_alive(self, agent_name):
        if agent_name not in self.agents:
            return False
        return time.time() - self.agents[agent_name].get('last_hb', 0) < self.heartbeat_timeout
    
    def register_signal(self, agent_name, symbol, direction, score, reason):
        """Register a trading signal from an agent."""
        with self.lock:
            self._bump(agent_name)
            signal = {
                'ts': dt.datetime.now(dt.timezone.utc).isoformat(),
                'agent': agent_name,
                'symbol': symbol,
                'direction': direction,
                'score': score,
                'reason': reason,
                'status': 'pending',
            }
            self.state['metrics']['signals'] += 1
            self.state['consensus'].append(signal)
            # Keep last 500 signals
            if len(self.state['consensus']) > 500:
                self.state['consensus'] = self.state['consensus'][-500:]
            self._save_state()
            self._save_agents()
            self._append_decision(signal)
            return signal
    
    def record_entry(self, symbol, side, price, quantity, agent_name, risk_usd):
        """Record a trade entry in swarm state."""
        with self.lock:
            self._bump(agent_name)
            entry = {
                'ts': dt.datetime.now(dt.timezone.utc).isoformat(),
                'symbol': symbol,
                'side': side,
                'price': price,
                'quantity': quantity,
                'agent': agent_name,
                'risk_usd': risk_usd,
                'status': 'open',
            }
            self.state['metrics']['entries'] += 1
            self.state.setdefault('open_positions', {})[symbol] = entry
            self._save_state()
            self._save_agents()
            self._append_decision({'ts': entry['ts'], 'agent': agent_name, 'action': 'open', 'symbol': symbol, 'side': side, 'price': price})
            return entry
    
    def record_exit(self, symbol, exit_price, reason):
        """Record a trade exit."""
        with self.lock:
            pos = self.state.get('open_positions', {}).pop(symbol, None)
            if pos:
                self._bump(pos['agent'])
                pnl = (exit_price - pos['price']) * pos['quantity'] if pos['side'] == 'BUY' else (pos['price'] - exit_price) * pos['quantity']
                exit_rec = {
                    'ts': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'symbol': symbol,
                    'side': pos['side'],
                    'entry_price': pos['price'],
                    'exit_price': exit_price,
                    'pnl': round(pnl, 4),
                    'reason': reason,
                    'agent': pos['agent'],
                }
                self.state['metrics']['exits'] += 1
                self.state.setdefault('closed_positions', []).append(exit_rec)
                self._save_state()
                self._save_agents()
                self._append_decision({'ts': exit_rec['ts'], 'agent': pos['agent'], 'action': 'close', 'symbol': symbol, 'pnl': pnl, 'reason': reason})
                return exit_rec
            return None
    
    def record_rejection(self, agent_name, symbol, reason):
        """Record a signal rejection."""
        with self.lock:
            self._bump(agent_name)
            self.state['metrics']['rejections'] += 1
            self._save_state()
            self._save_agents()
            self._append_decision({'ts': dt.datetime.now(dt.timezone.utc).isoformat(), 'agent': agent_name, 'action': 'reject', 'symbol': symbol, 'reason': reason})

    def record_event(self, agent_name, action, symbol, reason):
        """Record a non-trade swarm observation (whale, news, surge, sentiment, wall)."""
        with self.lock:
            self._bump(agent_name)
            rec = {
                'ts': dt.datetime.now(dt.timezone.utc).isoformat(),
                'agent': agent_name,
                'action': action,
                'symbol': symbol,
                'reason': reason,
            }
            self.state['metrics']['events'] = self.state['metrics'].get('events', 0) + 1
            self._save_state()
            self._save_agents()
            self._append_decision(rec)
            return rec
    
    def _append_decision(self, record):
        try:
            with open(DECISIONS_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, default=str) + '\n')
        except Exception:
            pass
    
    def get_status(self):
        """Get full swarm status for dashboard."""
        with self.lock:
            agent_status = {}
            for name, info in self.agents.items():
                agent_status[name] = {
                    'role': info['role'],
                    'status': 'online' if self.is_alive(name) else 'offline',
                    'last_hb': info.get('last_hb', 0),
                    'tasks': info.get('tasks', 0),
                    'skills': info.get('skills', []),
                }
            return {
                'agents': agent_status,
                'metrics': self.state.get('metrics', {}),
                'open_positions': self.state.get('open_positions', {}),
                'recent_signals': self.state.get('consensus', [])[-10:],
                'target_reached': self.state.get('target_reached', False),
            }

# Global singleton
swarm = SwarmCoordinator()

def get_swarm():
    return swarm
