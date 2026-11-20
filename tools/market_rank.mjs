#!/usr/bin/env node
// market_rank.mjs — Binance Web3 "market rank" monster tool.
//
// Vendored from the crypto-market-rank skill (binance-web3/3.0 public bapi
// endpoints) with the Windows dispatch bug fixed: the upstream CLI compares
// import.meta.url with `file://${process.argv[1]}`, which on Windows is
// `file:///C:/…` vs `file://C:\…` — never equal, so it printed nothing and
// exited 0. This copy always dispatches.
//
// Usage:  node market_rank.mjs <command> '<json_params>'
//         node market_rank.mjs <command> '<json_params>' --compact   (one-line JSON)
//
// Commands:
//   social-hype         social buzz leaderboard (sentiment + summary)   [56|8453|CT_501]
//   token-rank          unified rank (Trending 10 / TopSearch 11 / Alpha 20 / Stock 40)
//   smart-money-inflow  tokens by smart-money net inflow                [56|CT_501|8453]
//   meme-rank           top Pulse launchpad meme tokens (breakout score) [56]
//   address-pnl-rank    top trader PnL leaderboard
//
// Zero dependency, Node >= 18.

const TIMEOUT_MS = 15000;
const UA = { 'Accept-Encoding': 'identity', 'User-Agent': 'binance-web3/3.0 (Skill)' };

const qs = (p) => Object.entries(p)
  .filter(([, v]) => v != null)
  .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
  .join('&');

async function call({ url, method = 'GET', body, headers = {} }) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  const opts = { method, headers: { ...UA, ...headers }, signal: ctrl.signal };
  if (method === 'POST') {
    opts.headers['content-type'] = 'application/json';
    opts.body = JSON.stringify(body || {});
  }
  let res;
  try { res = await fetch(url, opts); }
  catch { clearTimeout(timer); throw Object.assign(new Error('Network request failed'), { exitCode: 3 }); }
  clearTimeout(timer);
  const data = await res.json();
  if (res.status >= 400) throw Object.assign(new Error(`HTTP ${res.status}`), { exitCode: 1, body: data });
  return data;
}

const CHAINS = {
  'social-hype':        new Set(['56', '8453', 'CT_501']),
  'token-rank':         new Set(['56', '8453', 'CT_501', '1']),
  'smart-money-inflow': new Set(['56', 'CT_501', '8453']),
  'meme-rank':          new Set(['56']),
  'address-pnl-rank':   new Set(['56', 'CT_501', '8453', '1']),
};

function validateChainId(cmd, chainId) {
  const allowed = CHAINS[cmd];
  if (!allowed) return;
  const id = String(chainId ?? '');
  if (!allowed.has(id)) {
    const supported = [...allowed].map((c) => `"${c}"`).join(', ');
    throw Object.assign(new Error(`${cmd}: unsupported chainId "${chainId}". Supported: ${supported}`), { exitCode: 1 });
  }
}

const COMMANDS = {
  'social-hype': (p) => {
    validateChainId('social-hype', p.chainId);
    return { url: `https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/social/hype/rank/leaderboard/ai?${qs(p)}` };
  },
  'token-rank': (p) => {
    validateChainId('token-rank', p.chainId);
    const SHARED = { countMin: 10, launchTimeMin: 15, liquidityMin: 5000, uniqueTraderMin: 10, volumeMin: 10000 };
    const rankType = p.rankType ?? 10;
    let body = { ...p };
    if (rankType === 10) body = { ...SHARED, tagFilter: [1, 2, 3], ...p };
    else if (rankType === 20) body = { ...SHARED, ...p };
    return { url: 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/unified/rank/list/ai', method: 'POST', body };
  },
  'smart-money-inflow': (p) => {
    validateChainId('smart-money-inflow', p.chainId);
    return { url: 'https://web3.binance.com/bapi/defi/v1/public/wallet-direct/tracker/wallet/token/inflow/rank/query/ai', method: 'POST', body: { ...p, tagType: p.tagType ?? 2 } };
  },
  'meme-rank': (p) => {
    validateChainId('meme-rank', p.chainId);
    return { url: `https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/exclusive/rank/list/ai?${qs(p)}` };
  },
  'address-pnl-rank': (p) => {
    validateChainId('address-pnl-rank', p.chainId);
    return { url: `https://web3.binance.com/bapi/defi/v1/public/wallet-direct/market/leaderboard/query/ai?${qs(p)}` };
  },
};

export { COMMANDS, call, qs, CHAINS, validateChainId };

const args = process.argv.slice(2);
const compact = args.includes('--compact');

// --params-file <path> sidesteps shells (notably PowerShell) that strip the
// double quotes out of an inline JSON argument before a native command sees it.
let paramsFile = null;
const pfIdx = args.indexOf('--params-file');
if (pfIdx !== -1) { paramsFile = args[pfIdx + 1]; args.splice(pfIdx, 2); }

const positional = args.filter((a) => a !== '--compact');
const [cmd, paramsStr] = positional;

if (!cmd || cmd === '--help' || cmd === '-h') {
  console.log("Usage: node market_rank.mjs <command> '<json_params>' [--compact] [--params-file <path>]\n\nCommands:");
  for (const name of Object.keys(COMMANDS)) console.log(`  ${name}`);
  process.exit(0);
}

const builder = COMMANDS[cmd];
if (!builder) { console.error(`Unknown command: ${cmd}`); process.exit(1); }

let params = {};
if (paramsFile) {
  try {
    const { readFileSync } = await import('node:fs');
    params = JSON.parse(readFileSync(paramsFile, 'utf8').replace(/^\uFEFF/, ''));
  } catch (e) { console.error('Invalid params file: ' + e.message); process.exit(1); }
} else if (paramsStr) {
  try { params = JSON.parse(paramsStr); }
  catch { console.error('Invalid JSON params'); process.exit(1); }
}

try {
  const result = await call(builder(params));
  console.log(compact ? JSON.stringify(result) : JSON.stringify(result, null, 2));
} catch (err) {
  console.error(err.message);
  if (err.body) console.log(JSON.stringify(err.body));
  process.exit(err.exitCode || 1);
}
