// Binance Hunter Dashboard - Enhanced
// Extracted from inline script and enhanced with new features

const $ = i => document.getElementById(i);
const AGCOL = { coordinator: '#F0B90B', scanner: '#2DD4BF', analyst: '#A78BFA', newsdesk: '#38BDF8',
  quant: '#E879F9', whale: '#22D3EE', risk_guard: '#FB923C', executor: '#0ECB81',
  portfolio: '#60A5FA', dashboard: '#F472B6' };
const AGORDER = ['coordinator', 'scanner', 'analyst', 'newsdesk', 'quant', 'whale', 'risk_guard',
  'executor', 'portfolio', 'dashboard'];
const TF_LIMIT = { '1m': 240, '5m': 240, '15m': 240, '1h': 300, '4h': 300, '1d': 300 };
const LVCOL = { fib: '#F0B90B', fibe: '#2DD4BF', gann: '#0ECB81', gann8: '#93C5FD', sq9: '#525C66' };
const SRCPANEL = { news: 'p_news', trending: 'p_feeds', fng: 'p_feeds', futures: 'p_feeds', altfins: 'p_altfins' };

let STATE = {}, SW = {}, FEEDS = {}, PP = {}, DECS = [], SEL = null, TF = '1m', prevPx = {};
let AUTO_REFRESH = true;
let tickIntervalId = null;
let chart = null, cs = null, vs = null, curChartSym = null, curBookSym = null, curFlowSym = null;
let TA = null, PINS = [], AGFLT = null, GATEFLT = null;
let TZ = { off: 0, name: 'UTC', label: 'UTC', abbr: 'UTC' };

// ============ NEW: Equity curve tracking ============
let equityHistory = []; // [{ts, balance, pnl_today}]
let equityChart = null;

// ============ NEW: Theme handling ============
function getTheme() { return localStorage.getItem('bh-theme') || 'dark'; }
function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('bh-theme', theme);
  updateThemeToggle();
}
function updateThemeToggle() {
  const btn = $('themeToggle');
  if (btn) btn.textContent = getTheme() === 'dark' ? '☀️ Light' : '🌙 Dark';
}

// ============ NEW: Modal/confirmation ============
function showModal(title, message, onConfirm) {
  let overlay = document.getElementById('modalOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'modalOverlay';
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal">
        <h3 id="modalTitle"></h3>
        <p id="modalMessage"></p>
        <div class="modal-actions">
          <button class="modal-btn cancel">Cancel</button>
          <button class="modal-btn confirm">Confirm</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
  }
  overlay.querySelector('#modalTitle').textContent = title;
  overlay.querySelector('#modalMessage').textContent = message;
  overlay.classList.add('on');
  const cleanup = () => { overlay.classList.remove('on'); overlay.removeEventListener('click', overlayHandler); };
  const overlayHandler = e => { if (e.target === overlay) cleanup(); };
  overlay.addEventListener('click', overlayHandler);
  overlay.querySelector('.cancel').onclick = cleanup;
  overlay.querySelector('.confirm').onclick = () => { cleanup(); if (onConfirm) onConfirm(); };
}

function showToast(msg) {
  const t = $('toast');
  if (!t) return;
  t.innerHTML = msg;
  t.classList.add('on');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('on'), 2800);
}

function flash(id) {
  const e = $(id);
  if (!e) return;
  e.classList.remove('flash');
  void e.offsetWidth;
  e.classList.add('flash');
}

function jump(id, msg) {
  const e = $(id);
  if (!e) return;
  e.scrollIntoView({ behavior: 'smooth', block: 'center' });
  flash(id);
  if (msg) showToast(msg);
}

// ============ Utility functions ============
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const px = v => { v = +v; if (!v) return '—'; if (v >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (v >= 1) return v.toFixed(4); if (v >= 0.01) return v.toFixed(6); return v.toPrecision(4); };
const fv = v => { v = +v; if (!v) return '—'; const a = Math.abs(v); if (a >= 1e12) return (v / 1e12).toFixed(2) + 'T';
  if (a >= 1e9) return (v / 1e9).toFixed(2) + 'B'; if (a >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(1) + 'K'; return v.toFixed(0); };
const sg = v => (+v >= 0 ? 'up' : 'dn');
const sx = v => (+v >= 0 ? '+' : '') + (+v).toFixed(2);
const esc = s => String(s ?? '—').replace(/[<>&"]/g, c => ({ '<': '<', '>': '>', '&': '&', '"': '"' }[c]));
const symc = s => String(s || '').replace('USDT', '');
const clockStr = () => new Date(Date.now() + TZ.off * 3600000).toISOString().slice(11, 19);
const tsx = sec => Math.floor(+sec) + Math.round(TZ.off * 3600);
const hhmm = ts => { if (!ts) return '—'; const d = new Date(+ts < 1e12 ? +ts * 1000 : +ts); return new Date(d.getTime() + TZ.off * 3600000).toISOString().slice(11, 19); };
function scorebar(s) { const c = s >= 80 ? '#0ECB81' : s >= 60 ? '#F0B90B' : '#3A4650';
  return `<span class="scorebar"><i style="width:${clamp(s, 0, 100)}%;background:${c}"></i><b>${s}</b></span>`; }
function spark(arr, col, w = 70, h = 16) {
  if (!arr || arr.length < 2) return '<span class="dim2">—</span>';
  const mn = Math.min(...arr), mx = Math.max(...arr), r = (mx - mn) || 1;
  return `<svg width=${w} height=${h}><polyline fill=none stroke="${col}" stroke-width=1.2 points="${arr.map((v, i) => `${i / (arr.length - 1) * w},${h - (v - mn) / r * (h - 3) - 1.5}`).join(' ')}"/></svg>`; }

const TF_SEC = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400 };
function tickCandle() {
  const el = $('candleT'); if (!el) return;
  const span = TF_SEC[TF] || 60, now = Date.now() / 1000;
  const open = Math.floor(now / span) * span, next = open + span;
  const left = Math.max(0, next - now);
  const hh = Math.floor(left / 3600), mm = Math.floor((left % 3600) / 60), ss = Math.floor(left % 60);
  const txt = hh ? `${hh}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
    : `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
  const b = el.querySelector('b'); if (b) b.textContent = TF.toUpperCase();
  const l = $('candleL'); if (l) l.textContent = txt;
  const bar = el.querySelector('.bar i');
  if (bar) bar.style.width = (((now - open) / span) * 100).toFixed(1) + '%';
  el.classList.toggle('closing', left <= span * 0.15);
  el.title = `${TF} candle open ${hhmm(open)} ${TZ.abbr} · close ${hhmm(next)} · ${txt} left`;
}

// ============ Gates ============
const GATES = [
  { k: 'order_flow_score', t: '>=', v: 80, lab: 'Order-flow score' },
  { k: 'volume_ratio', t: '>=', v: 3.0, lab: 'Volume ratio (1m)' },
  { k: 'momentum_5m', t: 'abs', v: 3.0, lab: '5m momentum' },
  { k: 'spread_pct', t: '<=', v: 0.30, gt: 0, lab: 'Spread' },
  { k: 'bid_liquidity', t: '>=', v: 50000, lab: 'Bid depth' },
  { k: 'ask_liquidity', t: '>=', v: 50000, lab: 'Ask depth' },
  { k: 'imbalance', t: 'abs', v: 0.60, lab: 'Book imbalance' },
];
function gok(g, x) { const v = +x[g.k] || 0;
  if (g.t === '>=') return v >= g.v;
  if (g.t === '<=') return (g.gt ? v > 0 : true) && v <= g.v;
  return Math.abs(v) >= g.v; }
function gpass(x) { let n = 0; for (const g of GATES) if (gok(g, x)) n++; return n; }

// ============ NEW: Equity curve rendering ============
function recordEquityPoint(balance, pnl_today) {
  equityHistory.push({ ts: Date.now(), balance, pnl_today });
  if (equityHistory.length > 200) equityHistory.shift();
}
function renderEquityCurve() {
  const canvas = $('equityCanvas');
  if (!canvas || equityHistory.length < 2) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.clientWidth;
  const h = canvas.height = canvas.clientHeight;
  if (!w || !h) return;

  ctx.clearRect(0, 0, w, h);

  const balances = equityHistory.map(p => p.balance);
  const mn = Math.min(...balances), mx = Math.max(...balances);
  const range = mx - mn || 1;

  // Draw grid
  ctx.strokeStyle = '#161B1F';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = (i / 4) * h;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }

  // Draw equity line
  const isDark = getTheme() === 'dark';
  const upColor = isDark ? '#0ECB81' : '#0D945A';
  const dnColor = isDark ? '#F6465D' : '#E03E3E';
  const goldColor = isDark ? '#F0B90B' : '#D4A00A';

  ctx.beginPath();
  equityHistory.forEach((p, i) => {
    const x = (i / (equityHistory.length - 1)) * w;
    const y = h - ((p.balance - mn) / range) * h;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = goldColor;
  ctx.lineWidth = 2;
  ctx.stroke();

  // Draw peak line
  const peak = Math.max(...balances);
  const peakY = h - ((peak - mn) / range) * h;
  ctx.setLineDash([5, 5]);
  ctx.beginPath(); ctx.moveTo(0, peakY); ctx.lineTo(w, peakY); ctx.stroke();
  ctx.setLineDash([]);

  // Draw current price dot
  const last = equityHistory[equityHistory.length - 1];
  const lastX = w, lastY = h - ((last.balance - mn) / range) * h;
  ctx.beginPath(); ctx.arc(lastX, lastY, 5, 0, Math.PI * 2); ctx.fillStyle = last.balance >= equityHistory[0].balance ? upColor : dnColor; ctx.fill();
  ctx.strokeStyle = '#0A0C0F'; ctx.lineWidth = 2; ctx.stroke();

  // Stats
  const totalPnl = last.balance - equityHistory[0].balance;
  const totalPnlPct = equityHistory[0].balance ? (totalPnl / equityHistory[0].balance * 100) : 0;
  const drawdown = peak > 0 ? ((peak - last.balance) / peak * 100) : 0;

  const statsEl = $('equityStats');
  if (statsEl) {
    statsEl.innerHTML = `
      <div class="equity-stat"><span class="l">Equity</span><span class="v mono">$${last.balance.toFixed(2)}</span></div>
      <div class="equity-stat"><span class="l">P&L</span><span class="v mono ${totalPnl >= 0 ? 'up' : 'dn'}">${totalPnl >= 0 ? '+' : ''}$${totalPnl.toFixed(2)} (${totalPnlPct.toFixed(2)}%)</span></div>
      <div class="equity-stat"><span class="l">Peak</span><span class="v mono">$${peak.toFixed(2)}</span></div>
      <div class="equity-stat"><span class="l">Drawdown</span><span class="v mono ${drawdown > 10 ? 'dn' : ''}">${drawdown.toFixed(2)}%</span></div>
    `;
  }
}

// ============ Render functions ============
function renderHead(s) {
  $('kBal').textContent = '$' + (+s.balance).toFixed(2);
  $('kTgt').textContent = '$' + (+s.target).toFixed(2);
  const p = +s.pnl_today || 0; $('kPnl').textContent = (p >= 0 ? '+$' : '-$') + Math.abs(p).toFixed(4); $('kPnl').className = 'v ' + sg(p);
  $('kPos').textContent = (s.positions || 0) + ' / 3';
  $('kTr').textContent = s.trades_today ?? '—';
  $('kSw').textContent = (s.swept || 0).toLocaleString();
  $('kCd').textContent = s.candidates ?? '—';
  const pill = $('pill'), on = !!s.running;
  pill.className = 'pill ' + (on ? 'on' : 'off'); $('pillTxt').textContent = on ? 'Hunting' : 'Paused';
  $('btnToggle').textContent = on ? 'Pause' : 'Resume';
  const exc = [];
  if (s.pegged_excluded) exc.push(`${s.pegged_excluded} pegged`);
  if (s.dead_excluded) exc.push(`${s.dead_excluded} dead`);
  if (s.catalyst_entries) exc.push(`${s.catalyst_entries} catalyst entries`);
  if (s.prepump_entries) exc.push(`${s.prepump_entries} pre-pump entries`);
  $('acct').innerHTML = `SPOT · USDT · ${esc(s.trading_symbols || 0)} TRADING SYMBOLS` +
    (exc.length ? `<br><span class="dim2">excluded: ${esc(exc.join(' · '))}</span>` : '');
  if (s.tz_offset !== undefined) {
    TZ.off = +s.tz_offset || 0; TZ.name = s.tz || 'UTC';
    TZ.abbr = `${s.tz_label || s.tz || 'UTC'} ${s.tz_offset_str || ''}`.trim();
    const b = $('clkTz'); if (b) { b.textContent = TZ.abbr; b.title = `hunter timezone ${s.tz || 'UTC'} (UTC${s.tz_offset_str || ''})`; }
    const tzc = $('chartTz'); if (tzc) { tzc.textContent = 'TZ ' + TZ.abbr; tzc.title = `chart axis + stamps read in ${s.tz || 'UTC'} (UTC${s.tz_offset_str || ''})`; }
  }
  $('clk').textContent = clockStr();
  // EST clock (UTC-5)
  const estMs = Date.now() - 5 * 3600000;
  const est = new Date(estMs).toISOString().slice(11, 19);
  $('clkEst').textContent = est;

  // Record equity point for curve
  recordEquityPoint(+s.balance, +s.pnl_today || 0);
  renderEquityCurve();
}

function renderAgents(sw) {
  SW = sw || SW; const A = SW.agents || {}; const keys = Object.keys(A);
  const on = keys.filter(k => A[k].status === 'online').length;
  $('agMeta').innerHTML = `<b>${on}</b>/${keys.length} live`;
  if (!keys.length) { $('agents').innerHTML = '<div class="empty">coordinator offline</div>'; return; }
  const order = AGORDER.filter(k => keys.includes(k)).concat(keys.filter(k => !AGORDER.includes(k)));
  $('agents').innerHTML = order.map(k => {
    const a = A[k] || {}, alive = a.status === 'online', col = AGCOL[k] || '#7C8792';
    const pulse = (prevPx['hb_' + k] !== a.last_hb); prevPx['hb_' + k] = a.last_hb;
    const sk = (a.skills || []);
    return `<div class="agent clk ${alive ? 'on' : ''} ${AGFLT === k ? 'sel' : ''}" data-ag="${k}"
      title="${sk.length ? 'project skills: ' + esc(sk.join(', ')) : 'no project skills loaded'}">
      <span class="nd ${pulse ? 'p' : ''}" style="background:${alive ? col : '#525C66'}"></span>
      <div><div class="nm" style="color:${alive ? col : ''}">${esc(a.role || k)}</div>
      <div class="sub">${a.tasks || 0} tasks · ${esc(k)}${sk.length ? ' · <span class="sk">' + esc(sk.join(' · ')) + '</span>' : ''}</div></div>
      <span class="st">${alive ? 'live' : 'off'}</span></div>`;
  }).join('');
  [...$('agents').querySelectorAll('[data-ag]')].forEach(el => el.onclick = () => {
    AGFLT = (AGFLT === el.dataset.ag) ? null : el.dataset.ag; renderAgents(SW); renderDecisions();
    toast(AGFLT ? `<b>filter</b> decision board → ${esc(AGFLT)}` : 'decision board filter cleared');
  });
  const m = SW.metrics || {};
  $('agbox').innerHTML =
    `<div class="clk" data-jump="p_dec"><div class="v">${m.signals || 0}</div><div class="l">Signals</div></div>
     <div class="clk" data-jump="p_dec"><div class="v up">${m.entries || 0}</div><div class="l">Entries</div></div>
     <div class="clk" data-jump="p_dec"><div class="v">${m.exits || 0}</div><div class="l">Exits</div></div>
     <div class="clk" data-jump="p_dec"><div class="v dim">${m.rejections || 0}</div><div class="l">Rejected</div></div>`;
  [...$('agbox').querySelectorAll('[data-jump]')].forEach(el => el.onclick = () => jump(el.dataset.jump));
  $('kSig').textContent = (SW.metrics || {}).signals || 0;
}

function renderShort(w) {
  let rows = (w || []).slice();
  if (GATEFLT !== null) rows = rows.filter(x => gok(GATES[GATEFLT], x));
  if (!rows.length) {
    $('rows').innerHTML = `<tr><td colspan="12" class="empty">${
      GATEFLT !== null ? 'no candidate passes ' + esc(GATES[GATEFLT].lab) + ' — click the gate again to clear' : 'no candidates yet — sweeping…'}</td></tr>`;
    return;
  }
  $('rows').innerHTML = rows.map(x => {
    const ch = +x.price_change_percent || 0, m5 = +x.momentum_5m || 0, sc = +x.order_flow_score || 0, gp = gpass(x);
    const br = Math.round((+x.buy_ratio || 0) * 100), sr = 100 - br;
    const liq = Math.min(+x.bid_liquidity || 0, +x.ask_liquidity || 0);
    const hist = (prevPx[x.symbol] || []).concat(+x.current_price); if (hist.length > 16) hist.shift(); prevPx[x.symbol] = hist;
    const gcols = GATES.map(g => `<i class="gate ${gok(g, x) ? 'on' : ((+x[g.k] || 0) ? 'half' : '')}"></i>`).join('');
    const t = x.ta || {};
    const chips = [];
    // SG — strong structure (order-flow score ≥ 80)
    if (+x.order_flow_score >= 80) chips.push('<span class="chip g" title="Strong structure · order-flow score ≥80">SG</span>');
    // LG — large volume (volume ratio ≥ 5×)
    if (+x.volume_ratio >= 5.0) chips.push('<span class="chip g" title="Large volume · ≥5× baseline">LG</span>');
    if (t.bias) chips.push(`<span class="chip ${t.bias === 'LONG' ? 'g' : t.bias === 'SHORT' ? 'r' : 't'}" title="Fib/Gann ${t.score}/100">${t.bias[0]}${t.bias === 'NEUTRAL' ? '' : 'G'}</span>`);
    if (t.golden) chips.push('<span class="chip t" title="Price in Fib golden pocket 0.382–0.618">GP</span>');
    // fib/gann — any Fib or Gann level present
    if (t.fib_levels || t.gann_levels || t.sq9_levels) chips.push('<span class="chip t" title="Fib / Gann levels detected">fib/gann</span>');
    // struct — swing structure detected
    if (t.structure_detected) chips.push('<span class="chip t" title="Swing structure detected">struct</span>');
    // N / N2 / N3 / N12 — news catalyst strength
    if (+x.catalyst > 0) {
      const n = Math.min(Math.round(+x.catalyst), 12);
      chips.push(`<span class="chip n" title="News/social catalyst strength">${n >= 12 ? 'N12' : n >= 3 ? 'N' + n : 'N'}</span>`);
    }
    // whale- — whale activity (imbalance ≥ 0.7)
    if (Math.abs(+x.imbalance || 0) >= 0.7) chips.push('<span class="chip r" title="Whale imbalance ≥0.7">whale-</span>');
    // trendin — trending in (positive 5m momentum)
    if (+x.momentum_5m > 1.0) chips.push('<span class="chip g" title="Trending in · 5m momentum >1%">trendin</span>');
    (x.feed_flags || []).slice(0, 2).forEach(f => chips.push(`<span class="chip" title="${esc(f)}">${esc(f.slice(0, 7))}</span>`));
    return `<tr data-sym="${x.symbol}" class="${SEL === x.symbol ? 'sel' : ''}">
      <td><div class="symc"><span class="dot ${sc >= 80 ? 'hot' : ''}"></span>
        <b>${symc(x.symbol)}</b><span class="q">/USDT</span>${chips.join('')}</div></td>
      <td class="mono" data-lp="${x.symbol}">${px(x.current_price)}</td>
      <td class="mono ${sg(ch)}" data-lc="${x.symbol}">${sx(ch)}%</td>
      <td class="mono ${sg(m5)}">${sx(m5)}%</td>
      <td class="mono">${(+x.volume_ratio || 0).toFixed(2)}×</td>
      <td class="mono"><span class="up">${br}</span><span class="dim2">/</span><span class="dn">${sr}</span></td>
      <td class="mono ${Math.abs(+x.imbalance || 0) >= .6 ? 'up' : 'dim'}">${(+x.imbalance || 0).toFixed(2)}</td>
      <td class="mono dim">${(+x.spread_pct || 0).toFixed(2)}%</td>
      <td class="mono dim">${fv(liq)}</td>
      <td>${scorebar(sc)}</td>
      <td><span class="gates" title="${gp}/${GATES.length}">${gcols}</span></td>
      <td>${spark(hist, ch >= 0 ? '#0ECB81' : '#F6465D')}</td></tr>`;
  }).join('');
  [...$('rows').querySelectorAll('tr')].forEach(t => t.onclick = () => selectCoin(t.dataset.sym));
  if ($('coinMeta')) $('coinMeta').textContent = `index ready · ${w ? w.length : 0} symbols`;
  const best = w && w[0];
  if (!best) { $('gates').innerHTML = '<div class="empty">no candidate</div>'; $('gBest').textContent = '—'; return; }
  const t = best.ta || {};
  $('gates').innerHTML = GATES.map((g, i) => {
    const v = +best[g.k] || 0, ok = gok(g, best);
    const disp = (g.k.includes('liq') ? fv(v) : (g.t === 'abs' ? Math.abs(v).toFixed(2) : v));
    const need = (g.t === '>=' ? ('≥ ' + (g.k.includes('liq') ? fv(g.v) : g.v)) : g.t === '<=' ? ('≤ ' + g.v) : ('|·| ≥ ' + g.v));
    return `<div class="gr clk ${GATEFLT === i ? 'sel' : ''}" data-gate="${i}" title="click to show only candidates passing this gate">
      <span class="m ${ok ? 'ok' : ''}">${ok ? '✓' : '✕'}</span>
      <span class="k">${g.lab}</span><span class="v ${ok ? 'up' : 'dn'}">${disp} <span class="dim2">${need}</span></span></div>`;
  }).join('');
  [...$('gates').querySelectorAll('[data-gate]')].forEach(el => el.onclick = () => {
    const i = +el.dataset.gate; GATEFLT = (GATEFLT === i) ? null : i; renderShort(STATE.watchlist || []);
    toast(GATEFLT !== null ? `<b>gate filter</b> ${esc(GATES[i].lab)} — click again to clear` : 'gate filter cleared');
  });
  const gp = gpass(best);
  $('gBest').innerHTML = `${esc(best.symbol)} <span class="${gp >= 7 ? 'up' : 'dim'}">${gp}/7</span>`;
}

function renderMarket(mk) { if (!$('mkRows')) return;
  if (!mk || !mk.length) { $('mkRows').innerHTML = '<tr><td colspan="6" class="empty">—</td></tr>'; return; }
  $('mkRows').innerHTML = mk.map((r, i) => { const ch = +r.price_change_percent || 0;
    return `<tr data-sym="${r.symbol}" class="${SEL === r.symbol ? 'sel' : ''}">
      <td class="dim2">${i + 1}</td>
      <td><div class="symc"><b>${symc(r.symbol)}</b><span class="q">/USDT</span></div></td>
      <td class="mono" data-lp="${r.symbol}">${px(r.current_price)}</td>
      <td class="mono ${sg(ch)}" data-lc="${r.symbol}">${sx(ch)}%</td>
      <td class="mono dim">${fv(r.volume_24h)}</td>
      <td class="mono dim2">${(r.trades_24h || 0).toLocaleString()}</td></tr>`;
  }).join('');
  [...$('mkRows').querySelectorAll('tr')].forEach(t => t.onclick = () => selectCoin(t.dataset.sym));
}

function renderTicker(mk) {
  const top = (mk || []).slice(0, 40);
  $('ticker').innerHTML = top.map(r => { const ch = +r.price_change_percent || 0;
    return `<span class="tk" data-sym="${r.symbol}" style="cursor:pointer">` +
      `<span style="color:${ch >= 0 ? '#0ECB81' : '#F6465D'}">■</span> <b>${symc(r.symbol)}</b> <span data-lp="${r.symbol}">${px(r.current_price)}</span> ` +
      `<span class="${sg(ch)}" data-lc="${r.symbol}">${sx(ch)}%</span></span>&nbsp;&nbsp;&nbsp;`;
  }).join('') || 'sweeping…';
  [...$('ticker').querySelectorAll('.tk')].forEach(el => el.onclick = () => selectCoin(el.dataset.sym));
}

function renderPositions(p) { if (!$('posRows')) return;
  const rows = p || [];
  if (!rows.length) { $('posRows').innerHTML = '<tr><td colspan="10" class="empty">no open positions</td></tr>'; return; }
  $('posRows').innerHTML = rows.map(x => {
    const pl = x.plan || {};
    const plStr = (pl.stop || pl.tp2) ? `<span class="dn mono">SL ${px(pl.stop)}</span> · <span class="up mono">TP ${px(pl.tp2)}</span>` : '<span class="dim2">market · atr</span>';
    const heldMin = x.timestamp ? Math.max(1, Math.floor((Date.now() / 1000 - x.timestamp) / 60)) : 0;
    return `<tr data-sym="${x.symbol}" class="${SEL === x.symbol ? 'sel' : ''}">
      <td><div class="symc"><b>${symc(x.symbol)}</b><span class="q">/USDT</span></div></td>
      <td class="${x.side === 'BUY' ? 'up' : 'dn'}">${esc(x.side)}</td>
      <td class="mono">${x.quantity}</td><td class="mono">${px(x.entry_price)}</td>
      <td class="mono">${x.order_flow_score || '—'}</td><td class="mono">${x.volume_ratio || '—'}</td>
      <td><span class="tag ${x.entry_type === 'news-catalyst' ? 'y' : ''}">${esc(x.entry_type || 'order-flow')}</span></td>
      <td><span class="tag">${esc(x.hunt_tf || '1m')}</span></td>
      <td style="font-size:10.5px">${plStr}</td>
      <td><span class="tag y">${esc(x.status || 'OPEN')}</span><span class="pos-age">${heldMin}m</span></td></tr>`;
  }).join('');
  [...$('posRows').querySelectorAll('tr')].forEach(t => t.onclick = () => selectCoin(t.dataset.sym));
}

async function renderFollow() {
  const b = $('fwBody'); if (!b) return;
  let d = null; try { d = await (await fetch('/api/signals')).json() } catch (e) { return; }
  if (!d) return; STATE.sig = d;
  const seen = new Set(), uniq = (d.follow || []).filter(x => { if (seen.has(x.symbol)) return false; seen.add(x.symbol); return true; });
  const rows = uniq;
  const st = $('fwStats');
  if (st) st.innerHTML =
    `<div><div class="v">${d.total == null ? '—' : d.total}</div><div class="l">tracked</div></div>` +
    `<div><div class="v">${d.open == null ? '—' : d.open}</div><div class="l">open</div></div>` +
    `<div><div class="v">${d.win_rate == null ? '—' : (+d.win_rate).toFixed(1) + '%'}</div><div class="l">win %</div></div>` +
    `<div><div class="v">${d.profit_factor == null ? '—' : (+d.profit_factor).toFixed(2)}</div><div class="l">PF</div></div>`;
  if ($('fwMeta')) $('fwMeta').textContent = `${d.closed || 0} closed · avg ${sx(d.avg_ret || 0)}% · exp ${sx(d.expectancy || 0)}%`;
  b.innerHTML = rows.length
    ? `<div class="fw dim2" style="border-bottom:1px solid var(--ln)"><span>SYMBOL</span><span>TYPE</span><span>SCORE</span><span>SL / TP2</span><span>AGE</span></div>` +
      rows.slice(0, 20).map(x => `<div class="fw clk" data-sym="${esc(x.symbol)}">
        <span class="sy">${symc(x.symbol)}</span>
        <span><span class="tag">${esc(x.entry_type || x.kind || 'signal')}</span> <span class="dim2">${esc(x.tf || '')}</span></span>
        <span class="mono">${x.score == null ? '—' : x.score}</span>
        <span style="font-size:10px"><span class="dn mono">${px(x.stop)}</span> / <span class="up mono">${px(x.tp2)}</span></span>
        <span class="mono ${x.status === 'OPEN' ? 'up' : 'dim2'}">${x.status === 'OPEN' ? Math.round(x.age_min || 0) + 'm' : esc(x.outcome || '—')}</span></div>`).join('')
    : '<div class="empty">no signals tracked yet</div>';
  [...b.querySelectorAll('[data-sym]')].forEach(el => el.onclick = () => selectCoin(el.dataset.sym));
}

function coinFromText(txt) {
  const uni = new Set(); [...(STATE.watchlist || []), ...(STATE.market || [])].forEach(r => uni.add(r.symbol));
  for (const sym of uni) { const b = symc(sym); if (b.length < 3) continue;
    if (new RegExp('\\$' + b + '\\b').test(txt) || new RegExp('\\b' + b + '\\b').test(txt)) return sym; }
  return '';
}

function renderWhales(f) { if (!$('whBody')) return;
  const w = (f.whales || []);
  $('whBody').innerHTML = w.length ? w.slice(0, 20).map(x => `<div class="fr clk" data-sym="${esc(x.symbol)}" data-px="${x.price}">
    <span class="s ${x.side === 'BUY' ? 'up' : 'dn'}">${esc(x.side)}</span><span><b>${symc(x.symbol)}</b> <span class="dim2">@ ${px(x.price)}</span></span><span class="q">$${fv(x.notional)}</span></div>`).join('') : '<div class="empty">no block trades yet</div>';
  [...$('whBody').querySelectorAll('[data-sym]')].forEach(el => el.onclick = ev => { if (ev.shiftKey) { pinLevel(+el.dataset.px, 'whale ' + symc(el.dataset.sym), '#2DD4BF'); return } selectCoin(el.dataset.sym); });
  const walls = (f.walls || []);
  if (walls.length) $('whBody').insertAdjacentHTML('afterbegin', `<div class="secttl">Standing walls</div>` + walls.slice(0, 8).map(x => `<div class="fr clk" data-sym="${esc(x.symbol)}" data-px="${x.price}"><span class="s ${x.side === 'BID' ? 'up' : 'dn'}">${esc(x.side)}</span><span><b>${symc(x.symbol)}</b> <span class="dim2">@ ${px(x.price)}</span></span><span class="q">$${fv(x.notional)}</span></div>`).join(''));
}

function renderSurge(f) { if (!$('vsBody')) return;
  const rows = (f.volume_surge || []);
  $('vsBody').innerHTML = rows.length ? rows.slice(0, 22).map(r => `<div class="fr clk" data-sym="${esc(r.symbol)}"><span class="s gold">${(+r.volume_ratio || 0).toFixed(1)}×</span><span><b>${symc(r.symbol)}</b> <span class="dim2">${px(r.price)}</span></span><span class="q"><span class="${sg(r.momentum_5m)}">${sx(r.momentum_5m || 0)}%</span> · ${r.score || 0}</span></div>`).join('') : '<div class="empty">no surge detected</div>';
  [...$('vsBody').querySelectorAll('[data-sym]')].forEach(el => el.onclick = () => selectCoin(el.dataset.sym));
}

function renderCatches(f) { if (!$('cgBody')) return;
  const rows = (f.catches || []);
  $('cgBody').innerHTML = rows.length ? rows.slice(0, 22).map(r => `<div class="fr clk" data-sym="${esc(r.symbol || '')}">
    <span class="s" style="color:${AGCOL[r.agent] || '#7C8792'}">${esc(r.kind || r.agent)}</span><span>${r.symbol ? `<b>${symc(r.symbol)}</b> ` : ''}<span class="dim2">${esc((r.detail || '').slice(0, 52))}</span></span><span class="q dim2">${hhmm(r.ts)}</span></div>`).join('') : '<div class="empty">nothing caught yet</div>';
  [...$('cgBody').querySelectorAll('[data-sym]')].forEach(el => el.onclick = () => { if (el.dataset.sym) selectCoin(el.dataset.sym); else toast('agent note — no symbol'); });
}

async function renderDecisions() {
  const b = $('decisions'); if (!b) return;
  let d = null; try { d = await (await fetch('/api/decisions')).json() } catch (e) { return; }
  if (!d) return; STATE.dec = d;
  const rows = (d.decisions || []).slice(0, 14);
  b.innerHTML = rows.length
    ? `<div class="fw dim2" style="border-bottom:1px solid var(--ln)"><span>SYMBOL</span><span>ACTION</span><span>SCORE</span><span>REASON</span></div>` +
      rows.map(x => `<div class="fw clk" data-sym="${esc(x.symbol || '')}">
        <span class="sy">${symc(x.symbol || '')}</span>
        <span class="tag">${esc(x.action || '—')}</span>
        <span class="mono">${x.score == null ? '—' : x.score}</span>
        <span class="dim2">${esc((x.reason || '').slice(0, 44))}</span></div>`).join('')
    : '<div class="empty">no decisions yet</div>';
  [...b.querySelectorAll('[data-sym]')].forEach(el => el.onclick = () => selectCoin(el.dataset.sym));
}

function ppColor(v) { v = +v || 0; return v >= 70 ? '#0ECB81' : v >= 50 ? '#F0B90B' : v >= 35 ? '#FB923C' : '#7C8792'; }
function renderPrepump(d) {
  const box = $('ppRows'); if (!box) return; PP = d || {};
  const rows = (d && d.coiled) || [], moving = (d && d.moving_now) || [];
  if ($('ppMeta')) $('ppMeta').textContent = `${rows.length} scanned · ${d && d.count_coiled || 0} coiled · ${moving.length} moving · gate ${d && d.threshold != null ? d.threshold : '—'}`;
  if (!rows.length) { box.innerHTML = `<tr><td colspan="8" class="empty">no coins coiling right now — waiting for the next squeeze</td></tr>`; return; }
  box.innerHTML = rows.slice(0, 24).map(r => {
    const rat = Math.round(+r.rating || 0), c = ppColor(rat), dir = (r.direction || 'BUY') === 'SELL' ? 's' : 'b';
    const why = (r.reasons || []).slice(0, 2).join(' · ') || 'structure building';
    const ch = +r.change || 0, coiled = !!r.coiled;
    return `<tr data-sym="${esc(r.symbol)}" class="${coiled ? 'coiled' : ''} ${SEL === r.symbol ? 'sel' : ''}">
      <td><span class="sym">${symc(r.symbol)}</span></td>
      <td><span class="dir ${dir}">${esc(r.direction || 'BUY')}</span>${coiled ? '<span class="dir b">COILED</span>' : ''}</td>
      <td><span class="sc" style="color:${c}">${rat}</span></td>
      <td>${Math.round(+r.score || 0)}</td>
      <td>${Math.round((+r.buy_ratio || 0) * 100)}%</td>
      <td class="${sg(ch)}">${sx(ch)}%</td>
      <td class="dim2" title="${esc((r.reasons || []).join(' · '))}">${esc(why)}</td>
      <td class="${coiled ? 'coiled' : 'dim'}">${coiled ? 'COILED' : 'building'}</td>
    </tr>`;
  }).join('');
  [...box.querySelectorAll('tr[data-sym]')].forEach(el => el.onclick = () => selectCoin(el.dataset.sym));
}

function renderMovers(mk) {
  const b = $('mvBody'); if (!b) return;
  const rows = (mk || []).filter(r => Math.abs(+r.price_change_percent || 0) > 0)
    .sort((a, c) => (+c.price_change_percent || 0) - (+a.price_change_percent || 0));
  if ($('mvMeta')) $('mvMeta').textContent = rows.length ? `${rows.length} swept · gainers / losers` : '—';
  if (!rows.length) { b.innerHTML = '<div class="empty">no movers yet</div>'; return; }
  const top = rows.slice(0, 9), bot = rows.slice(-5).reverse();
  const line = r => { const ch = +r.price_change_percent || 0; return `<div class="fr clk" data-sym="${esc(r.symbol)}"><span class="s ${sg(ch)}">${sx(ch)}%</span><span><b>${symc(r.symbol)}</b> <span class="dim2">${px(r.current_price)}</span></span><span class="q dim2">${fv(r.volume_24h)}</span></div>`; };
  b.innerHTML = '<div class="secttl">Gainers</div>' + top.map(line).join('') + '<div class="secttl">Losers</div>' + bot.map(line).join('');
  [...b.querySelectorAll('[data-sym]')].forEach(el => el.onclick = () => selectCoin(el.dataset.sym));
}

function renderAltfins() {
  const a = STATE.altfins, b = $('afBody');
  if (!b) return;
  if (!a || !a.available) { b.innerHTML = '<div class="empty">AltFins offline — pattern feed needs a key</div>'; return; }
  const rows = (a.rows || []).slice(0, 24);
  b.innerHTML = rows.length ? rows.map(x => `<div class="fr clk" data-sym="${esc(x.symbol)}"
      style="display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid #141A1F">
    <span class="sy">${symc(x.symbol)}</span>
    <span class="dim2">${esc(x.pattern || '')}</span>
    <span class="q mono">${x.score != null ? +x.score : '—'}</span></div>`).join('') : '<div class="empty">no AltFins patterns</div>';
  [...b.querySelectorAll('[data-sym]')].forEach(el => el.onclick = () => selectCoin(el.dataset.sym));
}

function renderFeeds(f) {
  FEEDS = f || {};
  const cats = f.catalysts || [], heads = f.headlines || [];
  let h = '';
  if (cats.length) {
    h += '<div class="secttl">Keyword catalysts — mapped to coins (click → load coin)</div>';
    h += cats.slice(0, 14).map(c => `<div class="cat" data-sym="${esc(c.symbol)}" data-url="${esc(c.url || '')}" title="shift-click → open source">
      <span class="tag ${c.dir === 'BULL' ? 'g' : 'r'}">${esc(c.dir)}</span>
      <span class="symc"><b>${symc(c.symbol)}</b></span>
      <span class="tt">${esc(c.source)} · ${esc(c.title)}</span></div>`).join('');
  }
  h += '<div class="secttl">Official · news · social feeds (click → open source)</div>';
  h += heads.length ? heads.slice(0, 26).map(n => `<div class="headline ${esc(n.kind || 'news')}" data-url="${esc(n.url || '')}" data-title="${esc(n.title || '')}">
    <span class="sr">${esc(n.kind || '')} · ${esc(n.source || '')} <span class="tm">${hhmm(n.ts)}</span></span>
    <span class="tt">${esc(n.title)}</span></div>`).join('') : '<div class="empty">no headlines — feeds warming up</div>';
  $('catBody').innerHTML = h;
  [...$('catBody').querySelectorAll('.cat')].forEach(el => el.onclick = ev => {
    const s = el.dataset.sym; if (ev.shiftKey && el.dataset.url) { window.open(el.dataset.url, '_blank'); return; }
    if (s) selectCoin(s); if (el.dataset.url) window.open(el.dataset.url, '_blank'); });
  [...$('catBody').querySelectorAll('.headline')].forEach(el => el.onclick = ev => {
    const u = el.dataset.url; const hit = coinFromText(el.dataset.title || '');
    if (u) window.open(u, '_blank'); if (hit) selectCoin(hit); else if (!u) toast('no link and no matched coin');
    else if (!hit) toast('source opened — no coin matched by keyword engine'); });
  const tr = f.trending || [], fng = f.fng || {}, fut = f.futures || {}, src = f.sources || [];
  let s2 = '';
  if (fng && fng.value !== undefined) s2 += `<div class="fngbox"><span class="fngv">${fng.value}</span><span class="fngl">${esc(fng.label)}</span><span class="grow"></span><span class="dim2" style="font-size:9px">FEAR & GREED</span></div>`;
  if (tr.length) { s2 += '<div class="secttl">CoinGecko trending (click → load coin)</div>';
    s2 += tr.map((t, i) => `<div class="fr clk" data-sym="${esc(t.symbol)}USDT"><span class="s">#${t.rank || i + 1}</span><span><b>${esc(t.symbol)}</b> <span class="dim2">${esc((t.name || '').slice(0, 18))}</span></span><span class="q ${sg(t.chg24h)}">${t.chg24h == null ? '—' : sx(t.chg24h) + '%'}</span></div>`).join(''); }
  const fk = Object.keys(fut);
  if (fk.length) { s2 += '<div class="secttl">Binance USD-M futures · OI / funding</div>';
    s2 += fk.map(k => { const r = fut[k] || {}; return `<div class="fr clk" data-sym="${esc(k)}"><span class="s">${symc(k)}</span><span class="dim2">OI ${fv(r.oi_usd)} <span class="${sg(r.oi_chg_pct)}">${sx(r.oi_chg_pct || 0)}%</span></span><span class="q">fund ${(+(r.funding || 0)).toFixed(4)}%</span></div>` }).join(''); }
  if (src.length) { const nok = src.filter(x => x.status === 'ok').length;
    s2 += '<div class="secttl">Source health — last fetch result (click → jump to the panel)</div>';
    s2 += src.map(x => `<div class="fr clk" data-jump="${SRCPANEL[x.kind] || ''}" title="${esc(x.name)} — ${esc(x.status)}${x.note ? ' · ' + esc(x.note) : ''}"><span class="dot" style="width:6px;height:6px;border-radius:50%;background:${x.status === 'ok' ? '#0ECB81' : '#525C66'}"></span><span>${esc(x.name)} <span class="dim2" style="font-size:9px">${esc(x.note || '')}</span></span><span class="q ${x.status === 'ok' ? 'up' : 'dim2'}">${esc(x.status)}</span></div>`).join(''); }
  $('feedBody').innerHTML = s2 || '<div class="empty">no feeds</div>';
  [...$('feedBody').querySelectorAll('[data-sym]')].forEach(el => el.onclick = () => selectCoin(el.dataset.sym));
  [...$('feedBody').querySelectorAll('[data-jump]')].forEach(el => el.onclick = () => { if (el.dataset.jump) jump(el.dataset.jump); else toast('no panel mapped for this source'); });
  renderWhales(f); renderSurge(f); renderCatches(f);
}

function renderTA(ta) {
  TA = ta || null;
  if (!TA || !TA.levels) { $('taLevels').innerHTML = '<div class="empty">no swing structure in this window</div>'; return; }
  const t = TA, f = t.fib || {}, g = t.gann || {}, n = t.nearest || {};
  const price = +t.price || 0;
  const rows = (t.levels || []).slice().sort((a, b) => b.price - a.price);
  $('taLevels').innerHTML = rows.map(l => { const d = price ? ((l.price - price) / price * 100) : 0; const on = PINS.some(p => Math.abs(p.price - l.price) < 1e-12);
    return `<div class="lv k-${esc(l.kind)} ${on ? 'pinned' : ''}" data-px="${l.price}" data-lab="${esc(l.label)}" data-kind="${esc(l.kind)}"><span class="k">${esc(l.label)}</span><span class="dim2" style="text-align:center">${on ? 'pinned' : ''}</span><span class="p">${px(l.price)} <span class="dim2">${d >= 0 ? '+' : ''}${d.toFixed(2)}%</span></span></div>`;
  }).join('');
  [...$('taLevels').querySelectorAll('.lv')].forEach(el => el.onclick = () => {
    const p = +el.dataset.px, lab = el.dataset.lab, kind = el.dataset.kind;
    const i = PINS.findIndex(x => Math.abs(x.price - p) < 1e-12);
    if (i >= 0) PINS.splice(i, 1); else PINS.push({ price: p, label: lab, color: LVCOL[kind] || '#F0B90B' });
    drawPins(); renderTA(TA); toast(i >= 0 ? `unpinned <b>${esc(lab)}</b>` : `pinned <b>${esc(lab)}</b> @ ${px(p)} on the chart`);
  });
}

function drawPins() {
  if (!SEL || !TA || !window.TradingView) return;
  // Pinning on TradingView widget is not directly supported without widget API
  // This is a placeholder for future widget-level drawing
}

async function loadTA(sym) {
  if (!sym) return;
  try {
    const d = await (await fetch('/api/ta/' + sym + '?interval=' + TF + '&limit=' + TF_LIMIT[TF])).json();
    renderTA(d);
  } catch (e) { $('taLevels').innerHTML = '<div class="empty">TA load failed</div>'; }
}

/* Order book / flow */
function drawBook(B, A) {
  if (!B.length && !A.length) { $('obBody').innerHTML = '<div class="empty">no depth — illiquid (excluded by gate)</div>'; return; }
  const mx = Math.max(...[...B, ...A].map(x => x.q), 1);
  const mid = B.length && A.length ? (B[0].p + A[0].p) / 2 : (B[0] ? B[0].p : A[0].p);
  const spr = B.length && A.length ? ((A[0].p - B[0].p) / mid * 100) : 0;
  const rw = (x, side) => `<div class="rw ${side} clk" data-px="${x.p}" title="click → pin this level on the chart"><i style="width:${(x.q / mx * 100).toFixed(1)}%"></i><span>${px(x.p)}</span><span>${(+x.q).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span></div>`;
  $('obBody').innerHTML = `<div class="hd"><span>Price</span><span>Size</span></div>${A.slice(0, 9).reverse().map(a => rw(a, 'ask')).join('')}<div class="mid">${px(mid)} <span class="dim2" style="font-size:9px">spread ${spr.toFixed(3)}%</span></div>${B.slice(0, 9).map(b => rw(b, 'bid')).join('')}`;
  [...$('obBody').querySelectorAll('[data-px]')].forEach(el => el.onclick = () => { pinLevel(+el.dataset.px, 'book', '#93C5FD'); toast(`pinned book level <b>${px(el.dataset.px)}</b>`); });
}

async function loadBook() {
  if (!SEL) return; if (curBookSym !== SEL) { $('obSymT').textContent = SEL; curBookSym = SEL; }
  if (WSFLAG.tape) return;
  try {
    const d = await (await fetch('/api/orderbook/' + SEL)).json();
    drawBook((d.bids || []).map(x => ({ p: +x.p, q: +x.q })), (d.asks || []).map(x => ({ p: +x.p, q: +x.q })));
  } catch (e) { $('obBody').innerHTML = '<div class="empty">unavailable</div>'; }
}

function drawFlow(T) {
  if (!T.length) { $('flBody').innerHTML = '<div class="empty">no trades</div>'; return; }
  let bv = 0, sv = 0; T.forEach(x => { const u = x.p * x.q; if (x.m) sv += u; else bv += u; });
  const tot = bv + sv || 1, bp = bv / tot * 100, delta = bv - sv;
  const rows = T.slice(-18).reverse().map(x => { const sell = x.m; return `<div class="fr clk" data-px="${x.p}"><span class="s ${sell ? 'dn' : 'up'}">${sell ? 'SELL' : 'BUY'}</span><span>${px(x.p)}</span><span class="q">${(+x.q).toLocaleString(undefined, { maximumFractionDigits: 2 })} <span class="dim2">${hhmm(x.t)}</span></span></div>` }).join('');
  $('flBody').innerHTML = rows + `<div class="sum"><span>Buy <b class="up">$${fv(bv)}</b> <span class="dim2">${bp.toFixed(0)}%</span></span><span>Sell <b class="dn">$${fv(sv)}</b></span><span>Δ <b class="${delta >= 0 ? 'up' : 'dn'}">${delta >= 0 ? '+' : '-'}$${fv(Math.abs(delta))}</b></span></div>`;
  [...$('flBody').querySelectorAll('[data-px]')].forEach(el => el.onclick = () => { pinLevel(+el.dataset.px, 'tape', '#2DD4BF'); toast(`pinned tape level <b>${px(el.dataset.px)}</b>`); });
}

async function loadFlow() {
  if (!SEL) return; if (WSFLAG.tape) return;
  try {
    const d = await (await fetch('/api/recent/' + SEL)).json();
    drawFlow((d.trades || []).map(x => ({ p: +x.p, q: +x.q, m: !!x.m, t: x.t })));
  } catch (e) { $('flBody').innerHTML = '<div class="empty">unavailable</div>'; }
}

/* WebSocket */
const WS_BASE = 'wss://stream.binance.com:9443'; const LIVE = { px: {} }; const WSFLAG = { market: false, tape: false };
let wsMarket = null, wsSym = null; let wsSymKey = null; let depthPending = null, depthTimer = null, flowTimer = null; const TAPE = { sym: null, rows: [] };
function wsBadge() {}

function wsMarketConnect() {
  try { if (wsMarket) wsMarket.close() } catch (e) { };
  try { wsMarket = new WebSocket(WS_BASE + '/ws/!miniTicker@arr') } catch (e) { return; }
  wsMarket.onopen = () => { WSFLAG.market = true; wsBadge(); };
  wsMarket.onerror = () => { };
  wsMarket.onclose = () => { WSFLAG.market = false; wsBadge(); setTimeout(wsMarketConnect, 4000); };
  wsMarket.onmessage = ev => {
    let a; try { a = JSON.parse(ev.data) } catch (e) { return; }
    if (!Array.isArray(a)) return;
    for (let i = 0; i < a.length; i++) {
      const t = a[i], s = t.s; if (!s || s.slice(-4) !== 'USDT') continue;
      const o = +t.o || 0, c = +t.c || 0;
      LIVE.px[s] = { c: c, o: o, h: +t.h || 0, l: +t.l || 0, q: +t.q || 0, chg: o ? (c - o) / o * 100 : 0 };
    }
  };
}

function symbolStream(sym) {
  if (!sym) return; if (wsSymKey === sym && wsSym && wsSym.readyState === 1) return; wsSymKey = sym; TAPE.sym = null; TAPE.rows = [];
  try { if (wsSym) wsSym.close() } catch (e) { };
  const l = sym.toLowerCase();
  try { wsSym = new WebSocket(WS_BASE + '/stream?streams=' + l + '@depth20@100ms/' + l + '@aggTrade') } catch (e) { return; }
  wsSym.onopen = () => { WSFLAG.tape = true; wsBadge(); };
  wsSym.onerror = () => { };
  wsSym.onclose = () => { WSFLAG.tape = false; wsBadge(); if (SEL === sym && wsSymKey === sym) setTimeout(() => symbolStream(sym), 4000); };
  wsSym.onmessage = ev => {
    let m; try { m = JSON.parse(ev.data) } catch (e) { return; }
    const st = m.stream || '', d = m.data; if (!d || wsSymKey !== SEL) return;
    if (st.indexOf('@depth') >= 0) onDepth(d); else if (st.indexOf('aggTrade') >= 0) onAggTrade(d);
  };
}

function onDepth(d) {
  depthPending = { B: (d.bids || []).map(x => ({ p: +x[0], q: +x[1] })), A: (d.asks || []).map(x => ({ p: +x[0], q: +x[1] })) };
  if (depthTimer) return; depthTimer = setTimeout(() => { depthTimer = null; const p = depthPending; depthPending = null; if (p) drawBook(p.B, p.A); }, 220);
}

function onAggTrade(d) {
  if (TAPE.sym !== SEL) { TAPE.sym = SEL; TAPE.rows = []; }
  TAPE.rows.push({ p: +d.p, q: +d.q, m: !!d.m, t: +d.T });
  if (TAPE.rows.length > 160) TAPE.rows.shift();
  if (flowTimer) return; flowTimer = setTimeout(() => { flowTimer = null; drawFlow(TAPE.rows); }, 260);
}

function patchLive() {
  if (!WSFLAG.market) return; const L = LIVE.px;
  for (const el of document.querySelectorAll('[data-lp]')) {
    const r = L[el.dataset.lp]; if (!r) continue; const txt = px(r.c);
    if (el.textContent !== txt) { const was = +el.dataset.last || 0; el.textContent = txt; el.dataset.last = r.c;
      if (was && r.c !== was) { el.classList.remove('tick-up', 'tick-dn'); void el.offsetWidth; el.classList.add(r.c > was ? 'tick-up' : 'tick-dn'); clearTimeout(el._tt); el._tt = setTimeout(() => el.classList.remove('tick-up', 'tick-dn'), 480); }
    }
  }
  for (const el of document.querySelectorAll('[data-lc]')) {
    const r = L[el.dataset.lc]; if (!r) continue; const t = sx(r.chg) + '%';
    if (el.textContent !== t) { el.textContent = t; el.classList.toggle('up', r.chg >= 0); el.classList.toggle('dn', r.chg < 0); }
  }
}

/* TradingView */
let CHART_SRC = 'tradingview', tvLoading = false; const TVINT = { '1m': '1', '5m': '5', '15m': '15', '1h': '60', '4h': '240', '1d': 'D' };
function setSrc(src) {
  CHART_SRC = src; [...document.querySelectorAll('#srcbar button')].forEach(b => b.classList.toggle('on', b.dataset.src === src));
  $('chartBox').style.display = (src === 'binance') ? '' : 'none'; $('tvBox').style.display = (src === 'tradingview') ? '' : 'none';
  if (!SEL) return; if (src === 'tradingview') initTV(SEL);
}

function initTV(sym) {
  const box = $('tvBox'); if (!box) return;
  box.style.display = ''; box.style.height = '100%';
  const build = () => {
    box.innerHTML = '<div id="tvchart" style="height:100%;width:100%"></div>';
    try {
      new TradingView.widget({
        container_id: 'tvchart', autosize: true, symbol: 'BINANCE:' + sym, interval: TVINT[TF] || '1',
        timezone: (TZ.name || 'Etc/UTC'), theme: getTheme(), style: '1', locale: 'en',
        toolbar_bg: '#0F1316', enable_publishing: false, allow_symbol_change: true,
        hide_side_toolbar: false, hide_top_toolbar: false, withdateranges: true,
        details: false, save_image: false, studies: [],
        backgroundColor: getTheme() === 'dark' ? 'rgba(10,12,15,1)' : 'rgba(255,255,255,1)',
        gridColor: getTheme() === 'dark' ? 'rgba(19,26,30,1)' : 'rgba(220,224,228,1)'
      });
    } catch (e) { toast('TradingView widget error: ' + esc(e.message)); }
  };
  if (window.TradingView) { build(); return; }
  if (tvLoading) return; tvLoading = true;
  const s = document.createElement('script'); s.src = 'https://s3.tradingview.com/tv.js';
  s.onload = () => { tvLoading = false; if (CHART_SRC === 'tradingview' && SEL) build(); };
  s.onerror = () => { tvLoading = false; toast('TradingView feed blocked — switched to <b>BINANCE LIVE</b>'); setSrc('binance'); };
  document.head.appendChild(s);
}

function planFor(sym) {
  const w = (STATE.watchlist || []).find(r => r.symbol === sym);
  if (w && w.plan) return { plan: w.plan, row: w };
  const p = (STATE.plans || []).find(x => x && x.symbol === sym);
  if (p) return { plan: p.plan || p, row: p };
  return null;
}

function renderPlan(sym) {
  const g = $('plGrid'); if (!g) return;
  const hit = sym ? planFor(sym) : null;
  const p = hit && hit.plan, r = hit && hit.row;
  if (!p) {
    if ($('plMeta')) $('plMeta').textContent = sym ? sym + ' · no plan' : 'select a coin';
    g.innerHTML = `<div class="pc wide"><div class="k">plan</div><div class="v dim2">${sym ? 'no live plan for this coin yet' : 'select a coin — every hunt prints its own plan'}</div></div>`;
    if ($('plRr')) $('plRr').innerHTML = '<i style="width:0%"></i>';
    if ($('plRrV')) $('plRrV').textContent = '—';
    if ($('plWhy')) $('plWhy').innerHTML = '<div class="empty">no live plan</div>';
    return;
  }
  const cells = [
    ['entry', px(p.entry), p.entry_src || ''],
    ['stop', px(p.stop), p.stop_src || ''],
    ['tp1', px(p.tp1), '1R'],
    ['tp2', px(p.tp2), '2R'],
    ['tp3', px(p.tp3), '3R'],
    ['trail arm', px(p.trail_arm), ''],
    ['trail dist', px(p.trail_dist), ''],
    ['size', (+p.qty || 0).toPrecision(4), 'qty'],
    ['notional', '$' + (+p.notional || 0).toFixed(2), ''],
    ['atr', px(p.atr), ''],
    ['risk', (+p.risk_pct || 0).toFixed(2) + '%', 'of equity'],
    ['tf', p.tf || '1m', p.valid ? 'valid' : 'stale'],
  ];
  g.innerHTML = cells.map(([k, v, s]) => `<div class="pc"><div class="k">${esc(k)}</div><div class="v mono">${esc(String(v == null ? '—' : v))}</div><div class="k dim2" style="margin-top:1px">${esc(s || '')}</div></div>`).join('');

  // ============ NEW: Buy/Sell buttons ============
  const btnRow = document.createElement('div');
  btnRow.className = 'pc wide';
  btnRow.style.paddingTop = '8px';
  btnRow.innerHTML = `
    <div class="k">actions</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="plan-btn buy" data-action="buy" data-sym="${sym}">BUY</button>
      <button class="plan-btn sell" data-action="sell" data-sym="${sym}">SELL</button>
    </div>`;
  g.appendChild(btnRow);
  btnRow.querySelectorAll('button').forEach(btn => btn.onclick = () => {
    const action = btn.dataset.action, symbol = btn.dataset.sym;
    const side = action === 'buy' ? 'BUY' : 'SELL';
    showModal(`Confirm ${side} ${symbol}`, `Place a market ${side} order for ${symbol}?\nThis will send a real order if live mode is enabled.`, async () => {
      try {
        const res = await fetch('/enter', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, reason: `manual ${side.toLowerCase()}` }) });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        showToast(`<b>${side} ${symbol}</b> ${data.message || 'submitted'}`);
        tick(); // refresh
      } catch (e) { showToast(`<b>Error:</b> ${esc(e.message)}`); }
    });
  });

  const rr = +p.rr || 0;
  if ($('plRr')) $('plRr').innerHTML = `<i style="width:${clamp(rr / 3 * 100, 0, 100)}%"></i>`;
  if ($('plRrV')) $('plRrV').textContent = rr ? rr.toFixed(2) + 'R' : '—';
  if ($('plMeta')) $('plMeta').textContent = `${sym} · ${p.tf || '1m'} · ${p.valid ? 'valid' : 'stale'}`;
  const why = ((r && r.boost_whys) || []).concat(((r && r.prepump && r.prepump.reasons) || [])).slice(0, 8);
  const st = (r && r.struct && r.struct.reasons) || [];
  if ($('plWhy')) {
    const all = why.concat(st).slice(0, 10);
    $('plWhy').innerHTML = all.length ? all.map(w => `<div class="fr"><span class="s gold">·</span><span>${esc(String(w))}</span></div>`).join('') : '<div class="empty">no confluence notes</div>';
  }
}

function selectCoin(sym) { if (!sym) return; SEL = sym; [...document.querySelectorAll('[data-sym]')].forEach(t => t.classList.toggle('sel', t.dataset.sym === sym)); initTV(sym); loadTA(sym); loadBook(); loadFlow(); renderPlan(sym); symbolStream(sym); }

function R(f) { try { f() } catch (e) { console.warn('render', e && e.message) } }

async function tick() {
  try {
    const [sR, swR] = await Promise.all([fetch('/api/status'), fetch('/api/swarm')]);
    STATE = await sR.json();
    let sw = {}; try { sw = await swR.json() } catch (e) { }
    R(() => renderHead(STATE));
    R(() => renderAgents(sw));
    R(() => renderShort(STATE.watchlist || []));
    if (!_autoSel && STATE.watchlist && STATE.watchlist.length) { _autoSel = true; const first = STATE.watchlist[0].symbol; selectCoin(first); wsMarketConnect(); symbolStream(first); }
    R(() => renderMarket(STATE.market || []));
    R(() => renderTicker(STATE.market || []));
    R(() => renderPositions(STATE.positions_detail || []));
    R(renderFollow);
    R(renderAltfins);
    R(() => renderMovers(STATE.market || []));
  } catch (e) { console.error('tick error', e); }
}

async function feedsTick() {
  try {
    const [fR, pR] = await Promise.all([fetch('/api/feeds'), fetch('/api/prepump')]);
    const f = await fR.json(); R(() => renderFeeds(f));
    try { renderPrepump(await pR.json()) } catch (e) { }
  } catch (e) { console.error('feedsTick error', e); }
}

/* Coin search */
function searchInitUI() {
  const q = $('coinQ'); if (!q) return;
  q.oninput = () => {
    const v = q.value.toLowerCase().trim();
    // filter table rows
    document.querySelectorAll('#rows tr[data-sym]').forEach(el => {
      const sym = el.getAttribute('data-sym') || ''; el.style.display = (!v || sym.toLowerCase().includes(v)) ? '' : 'none';
    });
    // filter pre-pump rows
    document.querySelectorAll('#ppRows tr[data-sym]').forEach(el => {
      const sym = el.getAttribute('data-sym') || ''; el.style.display = (!v || sym.toLowerCase().includes(v)) ? '' : 'none';
    });
    // filter ticker
    document.querySelectorAll('#ticker .tk').forEach(el => {
      const sym = el.getAttribute('data-sym') || ''; el.style.display = (!v || sym.toLowerCase().includes(v)) ? '' : 'none';
    });
    // filter movers
    document.querySelectorAll('#mvBody .fr[data-sym]').forEach(el => {
      const sym = el.getAttribute('data-sym') || ''; el.style.display = (!v || sym.toLowerCase().includes(v)) ? '' : 'none';
    });
  };
  q.onkeydown = ev => { if (ev.key === 'Enter') { const s = q.value.trim().toUpperCase(); if (s) { q.value = ''; selectCoin(s.endsWith('USDT') ? s : s + 'USDT'); } ev.preventDefault(); } };
}

let _autoSel = false;

function TFINIT() {
  var tfBtns = $('tfbar').querySelectorAll('button');
  tfBtns.forEach(function (b) {
    b.onclick = function () { TF = b.dataset.tf; tfBtns.forEach(function (x) { x.classList.toggle('on', x === b); }); PINS = []; drawPins(); tickCandle(); if ($('chartTfNote')) $('chartTfNote').textContent = TF; if (SEL) initTV(SEL); };
  });
  var srcBtns = $('srcbar').querySelectorAll('button');
  srcBtns.forEach(function (b) { b.onclick = function () { setSrc(b.dataset.src); }; });
  // NEW: Theme toggle
  const themeBtn = $('themeToggle');
  if (themeBtn) themeBtn.onclick = () => { setTheme(getTheme() === 'dark' ? 'light' : 'dark'); };
}

function pinLevel(px, source, color) {
  PINS.push({ price: px, label: source + ' ' + px, color: color }); drawPins();
}

function drawPins() {
  // Placeholder - TradingView widget doesn't expose drawing API easily
  // This would need widget.save() / widget.load() or charting library integration
}

function buildKPIStrip() {
  // Add equity panel to KPI row if not present
  if (!$('equityCanvas') && $('kpis')) {
    const equityPanel = document.createElement('div');
    equityPanel.className = 'kpi equity-panel';
    equityPanel.innerHTML = `
      <canvas class="equity-canvas" id="equityCanvas" style="height:60px"></canvas>
      <div class="equity-stats" id="equityStats"></div>
    `;
    $('kpis').appendChild(equityPanel);
  }
}

function buildKillSwitch() {
  // Replace the pause/resume button with a more prominent kill switch
  const btn = $('btnToggle');
  if (btn) {
    btn.classList.add('kill-switch');
    btn.setAttribute('data-action', 'toggle');
    // Keep existing onclick handler
  }
}

// ============ INITIALIZATION ============
function init() {
  buildKPIStrip();
  buildKillSwitch();
  searchInitUI();
  TFINIT();
  setTheme(getTheme());

  $('btnToggle').onclick = async () => {
    try { await fetch('/toggle', { method: 'POST' }); tick(); } catch (e) { }
  };
  $('btnAutoRefresh').onclick = () => {
    AUTO_REFRESH = !AUTO_REFRESH;
    const btn = $('btnAutoRefresh');
    if (AUTO_REFRESH) {
      btn.classList.add('gold');
      btn.textContent = '🔄 Live';
      if (!tickIntervalId) tickIntervalId = setInterval(tick, 2000);
      showToast('auto-refresh on');
    } else {
      btn.classList.remove('gold');
      btn.textContent = '⏸ Paused';
      if (tickIntervalId) { clearInterval(tickIntervalId); tickIntervalId = null; }
      showToast('auto-refresh paused');
    }
  };
  ($('tgTest') || {}).onclick = async () => {
    try { const r = await (await fetch('/api/notify?test=1')).json(); showToast(r.sent ? '<b>Telegram</b> test card sent' : 'Telegram test failed: <b>' + esc(r.last_error || 'not linked') + '</b>'); tick(); } catch (e) { }
  };
  ($('tgDisc') || {}).onclick = async () => {
    try { const r = await (await fetch('/api/notify?discover=1')).json(); showToast(r.chat ? `chat discovered: <b>${esc(r.chat)}</b>` : 'no chat yet — send the bot any message first'); tick(); } catch (e) { }
  };
  $('taClear').onclick = () => { PINS = []; drawPins(); renderTA(TA); showToast('chart levels cleared'); };
  $('taPin').onclick = () => { if (!TA || !TA.levels) { showToast('nothing to pin'); return } PINS = (TA.levels || []).map(l => ({ price: l.price, label: l.label, color: LVCOL[l.kind] || '#F0B90B' })); drawPins(); renderTA(TA); showToast(`pinned <b>${PINS.length}</b> Fib/Gann levels`); };
  $('fwBack').onclick = async () => {
    if (!SEL) { showToast('select a coin first'); return; }
    const btn = $('fwBack');
    const old = btn.textContent;
    btn.textContent = 'running…';
    try {
      const r = await (await fetch('/api/backtest/' + SEL + '?fresh=1')).json();
      if (r.error) { showToast(`backtest <b>${SEL}</b>: ${esc(r.error)}`); return; }
      const win = r.win_rate != null ? (+r.win_rate).toFixed(1) + '%' : '—';
      const pf = r.profit_factor != null ? (+r.profit_factor).toFixed(2) : '—';
      const exp = r.expectancy != null ? (+r.expectancy).toFixed(2) : '—';
      showToast(`<b>Backtest ${SEL}</b> · win ${win} · PF ${pf} · exp ${exp}%`);
    } catch (e) { showToast(`backtest error: ${esc(e.message)}`); }
    btn.textContent = old;
  };

  tick();
  renderDecisions();
  feedsTick();
  wsMarketConnect();

  setInterval(patchLive, 220);
  tickIntervalId = setInterval(tick, 2000);        // 2s tick (was 5s)
  setInterval(feedsTick, 10000);
  setInterval(renderDecisions, 8000);
  setInterval(() => { if (SEL) { loadBook(); loadFlow(); } }, 6000);
  setInterval(() => { if (SEL) renderPlan(SEL); }, 15000);
  setInterval(() => { if (SEL) { loadBook(); loadFlow(); loadTA(SEL); } }, 12000);
  setInterval(() => { $('clk').textContent = clockStr(); const estMs = Date.now() - 5 * 3600000; $('clkEst').textContent = new Date(estMs).toISOString().slice(11, 19); tickCandle(); }, 1000);

  tickCandle();
  searchInitUI();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}