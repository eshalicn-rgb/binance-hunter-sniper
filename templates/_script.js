const $=i=>document.getElementById(i);
const AGCOL={coordinator:'#F0B90B',scanner:'#2DD4BF',analyst:'#A78BFA',newsdesk:'#38BDF8',
             quant:'#E879F9',whale:'#22D3EE',risk_guard:'#FB923C',executor:'#0ECB81',
             portfolio:'#60A5FA',dashboard:'#F472B6'};
const AGORDER=['coordinator','scanner','analyst','newsdesk','quant','whale','risk_guard',
               'executor','portfolio','dashboard'];
const TF_LIMIT={'1m':240,'5m':240,'15m':240,'1h':300,'4h':300,'1d':300};
const SRCPANEL={news:'p_news',headlines:'p_news',social:'p_news',catalysts:'p_news',
                trending:'p_feeds',sentiment:'p_feeds',derivatives:'p_feeds',
                whales:'p_whale',walls:'p_whale',volume:'p_surge',volume_surge:'p_surge'};
const LVCOL={fib:'#F0B90B',fibe:'#2DD4BF',gann:'#0ECB81',gann8:'#93C5FD',sq9:'#525C66'};
let STATE={}, SW={}, FEEDS={}, PP={}, DECS=[], SEL=null, TF='1m', prevPx={}, ALERTS={};
let chart=null, cs=null, vs=null, curChartSym=null, curBookSym=null, curFlowSym=null, curTaKey=null;
let TA=null, PINS=[], AGFLT=null, GATEFLT=null;
/* timezone — filled from /api/status so the clock, stamps and the chart axis
   all read in the hunter's timezone, not the browser's/UTC's */
let TZ={off:0,name:'UTC',label:'UTC',abbr:'UTC'};

/* ================= fmt ================= */
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const px=v=>{v=+v;if(!v)return'—';if(v>=1000)return v.toLocaleString(undefined,{maximumFractionDigits:2});
  if(v>=1)return v.toFixed(4);if(v>=0.01)return v.toFixed(6);return v.toPrecision(4)};
const fv=v=>{v=+v;if(!v)return'—';const a=Math.abs(v);if(a>=1e12)return (v/1e12).toFixed(2)+'T';
  if(a>=1e9)return(v/1e9).toFixed(2)+'B';if(a>=1e6)return(v/1e6).toFixed(2)+'M';
  if(a>=1e3)return(v/1e3).toFixed(1)+'K';return v.toFixed(0)};
const sg=v=>(+v>=0?'up':'dn');
const sx=v=>(+v>=0?'+':'')+(+v).toFixed(2);
const esc=s=>String(s??'—').replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));
const symc=s=>String(s||'').replace('USDT','');
/* every displayed time reads in the hunter's timezone (TZ.off hours from UTC) */
const clockStr=()=>new Date(Date.now()+TZ.off*3600000).toISOString().slice(11,19);
const tsx=sec=>Math.floor(+sec)+Math.round(TZ.off*3600);
const hhmm=ts=>{if(!ts)return'—';const d=new Date(+ts<1e12?+ts*1000:+ts);return new Date(d.getTime()+TZ.off*3600000).toISOString().slice(11,19)};
function scorebar(s){const c=s>=80?'#0ECB81':s>=60?'#F0B90B':'#3A4650';
  return `<span class="scorebar"><i style="width:${clamp(s,0,100)}%;background:${c}"></i><b>${s}</b></span>`}
function spark(arr,col,w=70,h=16){if(!arr||arr.length<2)return '<span class="dim2">—</span>';
  const mn=Math.min(...arr),mx=Math.max(...arr),r=(mx-mn)||1;
  return `<svg width=${w} height=${h}><polyline fill=none stroke="${col}" stroke-width=1.2 points="${arr.map((v,i)=>`${i/(arr.length-1)*w},${h-(v-mn)/r*(h-3)-1.5}`).join(' ')}"/></svg>`}
function toast(msg){const t=$('toast');if(!t)return;t.innerHTML=msg;t.classList.add('on');
  clearTimeout(toast._t);toast._t=setTimeout(()=>t.classList.remove('on'),2800)}
function flash(id){const e=$(id);if(!e)return;e.classList.remove('flash');void e.offsetWidth;e.classList.add('flash')}
function jump(id,msg){const e=$(id);if(!e)return;e.scrollIntoView({behavior:'smooth',block:'center'});flash(id);if(msg)toast(msg)}

/* ================= candle timer ================= */
/* Binance klines are epoch-UTC aligned, so the seconds left in the candle come
   from the real clock (Date.now) — never from the TZ-shifted display clock.
   TF is only ever read, so the timer self-corrects the instant the tfbar flips. */
const TF_SEC={'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400};
function tickCandle(){
  const el=$('candleT');if(!el)return;
  const span=TF_SEC[TF]||60, now=Date.now()/1000;
  const open=Math.floor(now/span)*span, next=open+span;
  const left=Math.max(0,next-now);
  const hh=Math.floor(left/3600), mm=Math.floor((left%3600)/60), ss=Math.floor(left%60);
  const txt=hh?`${hh}:${String(mm).padStart(2,'0')}:${String(ss).padStart(2,'0')}`
              :`${String(mm).padStart(2,'0')}:${String(ss).padStart(2,'0')}`;
  const b=el.querySelector('b');if(b)b.textContent=TF.toUpperCase();
  const l=$('candleL');if(l)l.textContent=txt;
  const bar=el.querySelector('.bar i');
  if(bar)bar.style.width=(((now-open)/span)*100).toFixed(1)+'%';
  el.classList.toggle('closing',left<=span*0.15);
  el.title=`${TF} candle open ${hhmm(open)} ${TZ.abbr} · close ${hhmm(next)} · ${txt} left`;
}

/* ================= gates ================= */
const GATES=[
 {k:'order_flow_score',t:'>=',v:80,lab:'Order-flow score',short:'score'},
 {k:'volume_ratio',t:'>=',v:3.0,lab:'Volume ratio (1m)',short:'vol'},
 {k:'momentum_5m',t:'abs',v:3.0,lab:'5m momentum',short:'mom'},
 {k:'spread_pct',t:'<=',v:0.30,gt:0,lab:'Spread',short:'spread'},
 {k:'bid_liquidity',t:'>=',v:50000,lab:'Bid depth',short:'bidliq'},
 {k:'ask_liquidity',t:'>=',v:50000,lab:'Ask depth',short:'askliq'},
 {k:'imbalance',t:'abs',v:0.60,lab:'Book imbalance',short:'imbal'},
 {k:'buy_ratio',t:'>=',v:0.60,lab:'Buy-side flow (bullish)',short:'buy'},
];
function gok(g,x){const v=+x[g.k]||0;
  if(g.t==='>=')return v>=g.v;
  if(g.t==='<=')return (g.gt?v>0:true)&&v<=g.v;
  return Math.abs(v)>=g.v}
function gpass(x){let n=0;for(const g of GATES)if(gok(g,x))n++;return n}
function taOk(x){const t=x.ta;if(!t)return true;
  /* long-only hunter: a SHORT Fib/Gann read always blocks, and a LONG read still
     needs buy-side flow to be a pump we can actually buy */
  if(t.bias==='SHORT')return false;
  return !(t.bias==='LONG'&&(+x.buy_ratio||0)<0.5)}

/* ================= header / kpi ================= */
function renderHead(s){
  $('kBal').textContent='$'+(+s.balance).toFixed(2);
  $('kTgt').textContent='$'+(+s.target).toFixed(2);
  const p=+s.pnl_today||0;$('kPnl').textContent=(p>=0?'+$':'-$')+Math.abs(p).toFixed(4);$('kPnl').className='v '+sg(p);
  $('kPos').textContent=(s.positions||0)+' / 3';
  $('kTr').textContent=s.trades_today??'—';
  $('kSw').textContent=(s.swept||0).toLocaleString();
  $('kCd').textContent=s.candidates??'—';
  const tot=clamp((+s.balance)/(+s.target)*100,0,100);
  $('mProg').textContent=tot.toFixed(1)+'%';
  const N=24,lit=Math.round(tot/100*N);
  $('segs').innerHTML=Array.from({length:N},(_,i)=>`<div class="seg ${i<lit?'f':''}"></div>`).join('');
  const pill=$('pill'),on=!!s.running;
  pill.className='pill '+(on?'on':'off');$('pillTxt').textContent=on?'Hunting':'Paused';
  $('btnToggle').textContent=on?'Pause':'Resume';
  $('rMode').textContent=on?'LIVE ENGINE':'IDLE';
  const exc=[];
  if(s.pegged_excluded)exc.push(`${s.pegged_excluded} pegged`);
  if(s.dead_excluded)exc.push(`${s.dead_excluded} dead`);
  if(s.catalyst_entries)exc.push(`${s.catalyst_entries} catalyst entries`);
  if(s.prepump_entries)exc.push(`${s.prepump_entries} pre-pump entries`);
  $('acct').innerHTML=`SPOT · USDT · ${esc(s.trading_symbols||0)} TRADING SYMBOLS`+
    (exc.length?`<br><span class="dim2">excluded: ${esc(exc.join(' · '))}</span>`:'');
  /* timezone straight from the engine — clock, axis and stamps all follow it */
  if(s.tz_offset!==undefined){
    const changed=(+s.tz_offset||0)!==TZ.off;
    TZ.off=+s.tz_offset||0;TZ.name=s.tz||'UTC';
    TZ.abbr=`${s.tz_label||s.tz||'UTC'} ${s.tz_offset_str||''}`.trim();
    const b=$('clkTz');if(b){b.textContent=TZ.abbr;b.title=`hunter timezone ${s.tz||'UTC'} (UTC${s.tz_offset_str||''})`}
    const tzc=$('chartTz');if(tzc){tzc.textContent='TZ '+TZ.abbr;tzc.title=`chart axis + stamps read in ${s.tz||'UTC'} (UTC${s.tz_offset_str||''})`}
    if(changed&&SEL)initTV(SEL)   // rebuild the widget in the new timezone
  }
  $('clk').textContent=clockStr();
}

/* ================= agents ================= */
function renderAgents(sw){
  SW=sw||SW;const A=SW.agents||{};const keys=Object.keys(A);
  const on=keys.filter(k=>A[k].status==='online').length;
  $('agMeta').innerHTML=`<b>${on}</b>/${keys.length} live`;
  if(!keys.length){$('agents').innerHTML='<div class="empty">coordinator offline</div>';return}
  const order=AGORDER.filter(k=>keys.includes(k)).concat(keys.filter(k=>!AGORDER.includes(k)));
  $('agents').innerHTML=order.map(k=>{const a=A[k]||{},alive=a.status==='online',col=AGCOL[k]||'#7C8792';
    const pulse=(prevPx['hb_'+k]!==a.last_hb);prevPx['hb_'+k]=a.last_hb;
    const sk=(a.skills||[]);
    return `<div class="agent clk ${alive?'on':''} ${AGFLT===k?'sel':''}" data-ag="${k}"
      title="${sk.length?'project skills: '+esc(sk.join(', ')):'no project skills loaded'}">
      <span class="nd ${pulse?'p':''}" style="background:${alive?col:'#525C66'}"></span>
      <div><div class="nm" style="color:${alive?col:''}">${esc(a.role||k)}</div>
      <div class="sub">${a.tasks||0} tasks · ${esc(k)}${sk.length?' · <span class="sk">'+esc(sk.join(' · '))+'</span>':''}</div></div>
      <span class="st">${alive?'live':'off'}</span></div>`}).join('');
  [...$('agents').querySelectorAll('[data-ag]')].forEach(el=>el.onclick=()=>{
    AGFLT=(AGFLT===el.dataset.ag)?null:el.dataset.ag;renderAgents(SW);renderDecisions();
    toast(AGFLT?`<b>filter</b> decision board → ${esc(AGFLT)}`:'decision board filter cleared')});
  const m=SW.metrics||{};
  $('agbox').innerHTML=
    `<div class="clk" data-jump="p_dec"><div class="v">${m.signals||0}</div><div class="l">Signals</div></div>
     <div class="clk" data-jump="p_pos"><div class="v up">${m.entries||0}</div><div class="l">Entries</div></div>
     <div class="clk" data-jump="p_pos"><div class="v">${m.exits||0}</div><div class="l">Exits</div></div>
     <div class="clk" data-jump="p_dec"><div class="v dim">${m.rejections||0}</div><div class="l">Rejected</div></div>`;
  [...$('agbox').querySelectorAll('[data-jump]')].forEach(el=>el.onclick=()=>jump(el.dataset.jump));
  $('kSig').textContent=(SW.metrics||{}).signals||0;
}

/* ================= shortlist ================= */
function renderShort(w){
  let rows=(w||[]).slice();
  if(GATEFLT!==null)rows=rows.filter(x=>gok(GATES[GATEFLT],x));
  $('rows').parentElement.parentElement.classList.toggle('flash',false);
  if(!rows.length){$('rows').innerHTML=`<tr><td colspan="12" class="empty">${
    GATEFLT!==null?'no candidate passes '+esc(GATES[GATEFLT].lab)+' — click the gate again to clear':'no candidates yet — sweeping…'}</td></tr>`;return}
  $('rows').innerHTML=rows.map(x=>{
    const ch=+x.price_change_percent||0,m5=+x.momentum_5m||0,sc=+x.order_flow_score||0,gp=gpass(x);
    const br=Math.round((+x.buy_ratio||0)*100),sr=100-br;
    const liq=Math.min(+x.bid_liquidity||0,+x.ask_liquidity||0);
    const hist=(prevPx[x.symbol]||[]).concat(+x.current_price);if(hist.length>16)hist.shift();prevPx[x.symbol]=hist;
    const gcols=GATES.map(g=>`<i class="gate ${gok(g,x)?'on':((+x[g.k]||0)?'half':'')}"></i>`).join('');
    const t=x.ta||{};
    const chips=[];
    if(t.bias)chips.push(`<span class="chip ${t.bias==='LONG'?'g':t.bias==='SHORT'?'r':'t'}" title="Fib/Gann ${t.score}/100">${t.bias[0]}${t.bias==='NEUTRAL'?'':'G'}</span>`);
    if(t.golden)chips.push('<span class="chip t" title="price in the Fib golden pocket 0.382–0.618">GP</span>');
    if(+x.catalyst)chips.push(`<span class="chip n" title="news/social catalyst strength">N${(+x.catalyst).toFixed(0)}</span>`);
    (x.feed_flags||[]).slice(0,2).forEach(f=>chips.push(`<span class="chip" title="${esc(f)}">${esc(f.slice(0,7))}</span>`));
    return `<tr data-sym="${x.symbol}" class="${SEL===x.symbol?'sel':''}">
      <td><div class="symc"><span class="dot ${sc>=80?'hot':''}"></span>
        <b>${symc(x.symbol)}</b><span class="q">/USDT</span>${chips.join('')}</div></td>
      <td class="mono" data-lp="${x.symbol}">${px(x.current_price)}</td>
      <td class="mono ${sg(ch)}" data-lc="${x.symbol}">${sx(ch)}%</td>
      <td class="mono ${sg(m5)}">${sx(m5)}%</td>
      <td class="mono">${(+x.volume_ratio||0).toFixed(2)}×</td>
      <td class="mono"><span class="up">${br}</span><span class="dim2">/</span><span class="dn">${sr}</span></td>
      <td class="mono ${Math.abs(+x.imbalance||0)>=.6?'up':'dim'}">${(+x.imbalance||0).toFixed(2)}</td>
      <td class="mono dim">${(+x.spread_pct||0).toFixed(2)}%</td>
      <td class="mono dim">${fv(liq)}</td>
      <td>${scorebar(sc)}</td>
      <td><span class="gates" title="${gp}/${GATES.length}">${gcols}</span></td>
      <td>${spark(hist,ch>=0?'#0ECB81':'#F6465D')}</td></tr>`}).join('');
  [...$('rows').querySelectorAll('tr')].forEach(t=>t.onclick=()=>selectCoin(t.dataset.sym));

  const best=w&&w[0];
  if(!best){$('gates').innerHTML='<div class="empty">no candidate</div>';$('gBest').textContent='—';return}
  const t=best.ta||{};
  $('gates').innerHTML=GATES.map((g,i)=>{const v=+best[g.k]||0,ok=gok(g,best);
    const disp=(g.k.includes('liq')?fv(v):(g.t==='abs'?Math.abs(v).toFixed(2):v));
    const need=(g.t==='>='?('≥ '+(g.k.includes('liq')?fv(g.v):g.v)):g.t==='<='?('≤ '+g.v):('|·| ≥ '+g.v));
    return `<div class="gr clk ${GATEFLT===i?'sel':''}" data-gate="${i}" title="click to show only candidates passing this gate">
      <span class="m ${ok?'ok':''}">${ok?'✓':'✕'}</span>
      <span class="k">${g.lab}</span><span class="v ${ok?'up':'dn'}">${disp} <span class="dim2">${need}</span></span></div>`}).join('')
    +`<div class="gr" id="grStrategy" style="border-top:1px solid var(--ln)"><span class="m ${taOk(best)?'ok':''}">${taOk(best)?'✓':'✕'}</span>
      <span class="k">Fib / Gann gate</span><span class="v ${taOk(best)?'up':'dn'}">${t.bias?esc(t.bias)+' '+t.score+'/100':'n/a'}</span></div>
     <div class="gr clk" data-jump="p_news"><span class="m ${(+best.catalyst||0)>=6?'ok':''}">${(+best.catalyst||0)>=6?'✓':'·'}</span>
      <span class="k">News catalyst (path 2)</span><span class="v ${(+best.catalyst||0)>=6?'up':'dim'}">${(+best.catalyst||0).toFixed(0)} <span class="dim2">≥ 6</span></span></div>`;
  [...$('gates').querySelectorAll('[data-gate]')].forEach(el=>el.onclick=()=>{
    const i=+el.dataset.gate;GATEFLT=(GATEFLT===i)?null:i;renderShort(STATE.watchlist||[]);
    toast(GATEFLT!==null?`<b>gate filter</b> ${esc(GATES[i].lab)} — click again to clear`:'gate filter cleared')});
  [...$('gates').querySelectorAll('[data-jump]')].forEach(el=>el.onclick=()=>jump(el.dataset.jump));
  const gp=gpass(best),gN=GATES.length;
  $('gBest').innerHTML=`${esc(best.symbol)} <span class="${gp>=gN?'up':'dim'}">${gp}/${gN}${taOk(best)?' +strat':''}</span>`;
}

/* ================= full market ================= */
function renderMarket(mk){
  $('mkMeta').innerHTML=`swept <b>${(STATE.swept||0).toLocaleString()}</b> pairs · `+
    `showing <b>${(mk||[]).length}</b> · dead ${STATE.dead_excluded||0} · pegged ${STATE.pegged_excluded||0}`;
  if(!mk||!mk.length){$('mkRows').innerHTML='<tr><td colspan="6" class="empty">—</td></tr>';return}
  $('mkRows').innerHTML=mk.map((r,i)=>{const ch=+r.price_change_percent||0;
    return `<tr data-sym="${r.symbol}" class="${SEL===r.symbol?'sel':''}">
      <td class="dim2">${i+1}</td>
      <td><div class="symc"><b>${symc(r.symbol)}</b><span class="q">/USDT</span></div></td>
      <td class="mono" data-lp="${r.symbol}">${px(r.current_price)}</td>
      <td class="mono ${sg(ch)}" data-lc="${r.symbol}">${sx(ch)}%</td>
      <td class="mono dim">${fv(r.volume_24h)}</td>
      <td class="mono dim2">${(r.trades_24h||0).toLocaleString()}</td></tr>`}).join('');
  [...$('mkRows').querySelectorAll('tr')].forEach(t=>t.onclick=()=>selectCoin(t.dataset.sym));
}

/* ================= ticker marquee (clickable) ================= */
/* NOTE: mk arrives in Binance websocket order (BTC/BNB/ETH first) — that is why
   the strip used to only ever show BTC. We lead with the followed pre-pump
   lead, then the rated radar, and only then fall back to live movers.        */
function renderTicker(mk){
  const M=(mk||[]);
  const pp=(typeof PP!=='undefined'&&PP)?PP:{};
  const w=(pp.watch&&pp.watch.symbol)?pp.watch:null;
  const radar=(pp.coiled||[]);
  const used=new Set();
  const parts=[];
  if(w){
    used.add(w.symbol);
    const ch=+w.change||0, rt=+w.rating||0;
    const col=rt>=70?'#0ECB81':rt>=55?'#F0B90B':'#525C66';
    parts.push(`<span class="tk lead" data-sym="${esc(w.symbol)}" style="cursor:pointer" title="following the pre-pump lead">`+
      `<span class="eye">👁 WATCH</span> <b>${symc(w.symbol)}</b> <span data-lp="${w.symbol}">${px(w.price)}</span> `+
      `<span class="${sg(ch)}" data-lc="${w.symbol}">${sx(ch)}%</span> `+
      `<span class="vr">VOL ${(+w.volume_ratio||0).toFixed(1)}x</span> `+
      `<span class="rt" style="color:${col}">★${rt.toFixed(0)}</span></span>`);
  }
  radar.slice(0,16).forEach(r=>{
    if(!r.symbol||used.has(r.symbol))return;
    used.add(r.symbol);
    const ch=+r.change||0, rt=+r.rating||0;
    const col=rt>=70?'#0ECB81':rt>=55?'#F0B90B':'#525C66';
    parts.push(`<span class="tk" data-sym="${esc(r.symbol)}" style="cursor:pointer" title="${esc((r.reasons||[]).join(' · '))}">`+
      `<span style="color:${ch>=0?'#0ECB81':'#F6465D'}">■</span> <b>${symc(r.symbol)}</b> <span data-lp="${r.symbol}">${px(r.price)}</span> `+
      `<span class="${sg(ch)}" data-lc="${r.symbol}">${sx(ch)}%</span> `+
      `<span class="rt" style="color:${col}">★${rt.toFixed(0)}</span></span>`);
  });
  M.filter(r=>r&&r.symbol&&!used.has(r.symbol))
   .sort((a,b)=>Math.abs(+b.price_change_percent||0)-Math.abs(+a.price_change_percent||0))
   .slice(0,10).forEach(r=>{
    const ch=+r.price_change_percent||0;
    parts.push(`<span class="tk" data-sym="${esc(r.symbol)}" style="cursor:pointer">`+
      `<span style="color:${ch>=0?'#0ECB81':'#F6465D'}">■</span> <b>${symc(r.symbol)}</b> <span data-lp="${r.symbol}">${px(r.current_price)}</span> `+
      `<span class="${sg(ch)}" data-lc="${r.symbol}">${sx(ch)}%</span></span>`);
  });
  $('ticker').innerHTML=parts.join('&nbsp;&nbsp;&nbsp;')||'sweeping…';
  [...$('ticker').querySelectorAll('.tk')].forEach(el=>el.onclick=()=>selectCoin(el.dataset.sym));
  // The scanner bar names the token actually being watched for a pre-pump,
  // so the header never reads as a generic "sweeping" label.
  const st=$('scanTag');
  if(st){
    if(w){
      st.innerHTML=`<i></i>Sweeping Binance · Watch <b>${symc(w.symbol)}</b> ${(+w.volume_ratio||0).toFixed(1)}x`;
      st.title=`watching ${w.symbol} for a pre-pump — click to load its chart`;
      st.onclick=()=>selectCoin(w.symbol);
    } else {
      st.innerHTML='<i></i>Sweeping Binance · Watch';
      st.title='no pre-pump lead locked yet';
      st.onclick=null;
    }
  }
}

/* ================= positions ================= */
function renderPositions(p){
  const rows=p||[];
  $('posMeta').innerHTML=`<b>${rows.length}</b> / 3 open`;
  if(!rows.length){$('posRows').innerHTML='<tr><td colspan="10" class="empty">no open positions</td></tr>';return}
  $('posRows').innerHTML=rows.map(x=>{
    const p=x.plan||{};
    const pl=(p.stop||p.tp2)
      ? `<span class="dn mono">SL ${px(p.stop)}</span> · <span class="up mono">TP ${px(p.tp2)}</span>`
        +(p.trail_arm?` · <span class="dim2 mono">tr ${px(p.trail_arm)}/${px(p.trail_dist)}</span>`:'')
      : '<span class="dim2">market · atr</span>';
    return `<tr data-sym="${x.symbol}" class="${SEL===x.symbol?'sel':''}">
    <td><div class="symc"><b>${symc(x.symbol)}</b><span class="q">/USDT</span></div></td>
    <td class="${x.side==='BUY'?'up':'dn'}">${esc(x.side)}</td>
    <td class="mono">${x.quantity}</td><td class="mono">${px(x.entry_price)}</td>
    <td class="mono">${x.order_flow_score||'—'}</td><td class="mono">${x.volume_ratio||'—'}</td>
    <td><span class="tag ${x.entry_type==='news-catalyst'?'y':''}">${esc(x.entry_type||'order-flow')}</span></td>
    <td><span class="tag">${esc(x.hunt_tf||'1m')}</span></td>
    <td style="font-size:10.5px">${pl}</td>
    <td><span class="tag y">${esc(x.status||'OPEN')}</span></td></tr>`}).join('');
  [...$('posRows').querySelectorAll('tr')].forEach(t=>t.onclick=()=>selectCoin(t.dataset.sym));
}

/* ================= trade plan ================= */
const pct=v=>{v=+v;if(!isFinite(v))return'—';return (v>=0?'+':'')+v.toFixed(2)+'%'};
const money=v=>{v=+v;if(!isFinite(v)||v===0)return'—';return '$'+v.toLocaleString(undefined,{maximumFractionDigits:2})};
/* holding duration: minutes -> "2h 14m" / "43m" (the gap between the signal and now / its exit) */
const dur=m=>{m=+m;if(!isFinite(m)||m<0)return'—';const t=Math.round(m),h=Math.floor(t/60);return h?`${h}h ${t%60}m`:`${t}m`};
async function renderPlan(sym){
  if(!sym)return;
  try{
    const r=await (await fetch('/api/plan/'+encodeURIComponent(sym))).json();
    const p=r.plan||{}, st=r.struct||{};
    $('plMeta').innerHTML=`<b>${symc(sym)}</b>${r.tf?' · '+esc(r.tf):''}`;
    if(!p.entry){
      $('plGrid').innerHTML='<div class="pc wide"><div class="k">plan</div><div class="v dim2">no plan yet — structure not readable</div></div>';
      $('plRr').firstElementChild.style.width='0%';$('plRrV').textContent='—';
      $('plWhy').innerHTML='<div class="empty">no live plan</div>';return;
    }
    const cell=(k,v,c)=>`<div class="pc"><div class="k">${k}</div><div class="v ${c||''}">${v}</div></div>`;
    $('plGrid').innerHTML=
      cell('entry',px(p.entry),'gold')+
      cell('stop',px(p.stop)+' <span class="dn">−'+(+p.risk_pct||0).toFixed(2)+'%</span>','dn')+
      cell('tp1',px(p.tp1),'up')+cell('tp2',px(p.tp2),'up')+
      cell('tp3',px(p.tp3),'up')+cell('trail arm',px(p.trail_arm),'dim')+
      `<div class="pc wide"><div class="k">size · ${esc(p.entry_src||'')} entry / ${esc(p.stop_src||'')} stop / ATR ${px(p.atr)}</div>
        <div class="v">${p.notional!=null?money(p.notional)+'  ≈  '+p.qty+' units':'no size — balance unavailable'}</div></div>`;
    const rr=+p.rr||0;
    $('plRr').firstElementChild.style.width=Math.max(0,Math.min(rr/4*100,100))+'%';
    $('plRrV').textContent=rr.toFixed(2)+'R'+(p.valid?'':' ⚠');
    const lv=[['stop',p.stop,'var(--dn)'],['entry',p.entry,'var(--gold)'],['tp1',p.tp1,'var(--up)'],['tp2',p.tp2,'var(--up)'],['tp3',p.tp3,'var(--up)']]
      .filter(x=>+x[1]>0);
    const lo=Math.min(...lv.map(x=>+x[1])),hi=Math.max(...lv.map(x=>+x[1]));
    $('plWhy').innerHTML=lv.map(([k,v,c])=>{
      const pos=hi>lo?((+v-lo)/(hi-lo)*100):50;
      return `<div class="lvl"><span class="k">${k}</span><span class="b"><i style="left:${pos.toFixed(1)}%;width:3px;background:${c}"></i></span><span class="mono" style="min-width:78px;text-align:right">${px(v)}</span></div>`}).join('')
      +(st.state?`<div class="lvl"><span class="k">structure</span><span class="b"></span><span class="dim2" style="font-size:9.5px">${esc(st.state)} · ${esc(st.tf||'')} · score ${st.score==null?'—':st.score}${st.bullish?' · bullish':''}</span></div>`:'')
      +`<div class="lvl"><span class="k">trail</span><span class="b"></span><span class="dim2" style="font-size:9.5px">arm ${px(p.trail_arm)} · gives back ${px(p.trail_dist)} from the high</span></div>`;
  }catch(e){}
}

/* ================= signal follow-up ================= */
function renderFollow(){
  const s=STATE.signals||{},plans=STATE.plans||[],bt=STATE.backtest||null;
  $('fwStats').innerHTML=
    `<div><div class="v">${s.total||0}</div><div class="l">tracked</div></div>
     <div><div class="v gold">${s.open||0}</div><div class="l">open</div></div>
     <div><div class="v ${(s.win_rate||0)>=50?'up':'dn'}">${s.win_rate==null?'—':s.win_rate+'%'}</div><div class="l">win</div></div>
     <div><div class="v">${s.profit_factor==null?'—':s.profit_factor}</div><div class="l">PF</div></div>`;
  $('fwMeta').innerHTML=`TP <b class="up">${s.tp||0}</b> · TRAIL <b>${s.trail||0}</b> · SL <b class="dn">${s.sl||0}</b> · TO <b>${s.timeout||0}</b>`;
  /* the sent time + holding duration come from the ledger's own rows (follow),
     which carry both live and resolved signals; fall back to the open plans only
     if this engine build has no follow list yet */
  const follow=(s.follow&&s.follow.length)?s.follow:null;
  const rows=(follow||plans).slice(0, follow?24:14);
  const pmap={};plans.forEach(p=>{if(p&&p.symbol)pmap[p.symbol]=p});
  $('fwBody').innerHTML=rows.length
    ?`<div class="fw dim2" style="border-bottom:1px solid var(--ln)"><span>SYMBOL</span><span>TF</span><span>TIME</span><span>HOLD</span><span>PLAN · SL / TP2</span><span>LAST</span><span>MFE</span></div>`+
      rows.map(x=>{
        const isOpen=(x.status||'OPEN')==='OPEN';
        const live=isOpen?(pmap[x.symbol]||{}):{};          /* live last/mfe live on the plan row */
        const dd=(x.age_min!=null)?x.age_min:x.hold_min;    /* age while open, hold once resolved */
        const last=isOpen?live.last_pct:x.outcome;
        const mfe=isOpen?live.mfe_pct:null;
        const rr=(x.rr!=null)?x.rr:live.rr;
        const st=x.status||'OPEN';
        const stc=st==='TP'?'g':st==='SL'?'r':st==='OPEN'?'y':'';
        return `<div class="fw clk" data-sym="${esc(x.symbol)}">
          <span class="sy">${symc(x.symbol)}</span>
          <span><span class="tag">${esc(x.tf||'1m')}</span></span>
          <span class="mono dim2">${hhmm(x.ts)}</span>
          <span class="mono"${!isOpen?' title="held until '+hhmm(x.resolved_ts)+'"':''}>${dur(dd)}</span>
          <span style="font-size:10px"><span class="dn mono">${px(x.stop)}</span> / <span class="up mono">${px(x.tp2)}</span>
            <span class="dim2">${rr?rr+'R':''}</span> <span class="tag ${x.kind==='entry'?'y':''}">${esc(x.kind||'signal')}</span>${isOpen?'':` <span class="tag ${stc}">${esc(st)}</span>`}</span>
          <span class="mono ${(+last||0)>=0?'up':'dn'}">${last==null?'—':pct(last)}</span>
          <span class="mono dim2">${mfe==null?'—':pct(mfe)}</span></div>`}).join('')
    :'<div class="empty">nothing tracked yet — every hunt is recorded here with its plan</div>';
  [...$('fwBody').querySelectorAll('[data-sym]')].forEach(el=>el.onclick=()=>selectCoin(el.dataset.sym));
  if(bt&&bt.symbols){
    const avg=bt.avg_ret, med=bt.median_ret, pp=bt.pct_profitable;
    const spread=(avg!=null&&med!=null&&Math.abs(avg-med)>Math.abs(med||1))
      ? ' <span class="dn" title="the mean sits far from the median — a few symbols are carrying this base rate">spread ⚠</span>' : '';
    $('fwBt').innerHTML=`base rate · <b>${bt.symbols}</b> sym · <b>${bt.trades}</b> trades · win <b>${bt.win_rate==null?'—':bt.win_rate+'%'}</b> · PF <b>${bt.profit_factor==null?'—':bt.profit_factor}</b>`
      +` · median <b>${pct(med)}</b> · <b>${pp==null?'—':pp+'%'}</b> sym profitable`
      +(bt.worst_sym?` · worst <b>${esc(symc(bt.worst_sym.symbol))} ${pct(bt.worst_sym.avg_ret)}</b>`:'')
      +spread;
  }
}

/* ================= altfins bullish patterns ================= */
function renderAltfins(){
  const a=STATE.altfins,b=$('afBody'),m=$('afMeta');
  if(!b||!m)return;
  if(!a||!a.available){
    m.innerHTML='<span class="dim2">'+(a&&a.error?a.error:'offline')+'</span>';
    b.innerHTML='<div class="empty">AltFins offline — pattern feed needs a key</div>';return;
  }
  m.innerHTML=`<b>${a.count||0}</b> bullish · <b class="gold">${a.actionable||0}</b> actionable`;
  const rows=(a.rows||[]).slice(0,24);
  b.innerHTML=rows.length?rows.map(x=>`<div class="fr clk" data-sym="${esc(x.symbol)}"
      style="display:grid;grid-template-columns:auto 1fr auto;gap:8px;padding:4px 10px;font-size:11px;border-bottom:1px solid var(--hline);align-items:center">
      <span class="mono gold">${esc(symc(x.symbol))}</span>
      <span class="dim">${esc(x.pattern_label||'')} <span class="dim2">· ${esc(x.timeframe||'')}${x.strength?' · '+esc(x.strength):''}${x.stage?' · '+esc(x.stage):''}</span></span>
      <span class="mono up">${x.profit_potential!=null?'+'+x.profit_potential+'%':''}</span></div>`).join('')
    :'<div class="empty">no bullish patterns right now</div>';
  [...b.querySelectorAll('[data-sym]')].forEach(el=>el.onclick=()=>selectCoin(el.dataset.sym));
}

/* ================= coin searcher ================= */
let COINS=[];
function livePx(s){try{const x=LIVE.px[s];return x?x.c:null}catch(e){return null}}
async function searchInit(){
  try{
    const r=await (await fetch('/api/symbols')).json();
    COINS=r.symbols||[];
    $('coinMeta').innerHTML=`<b>${COINS.length}</b> tradable USDT pairs`;
  }catch(e){$('coinMeta').textContent='index unavailable'}
}
function searchRender(){
  const box=$('coinRes'),q=($('coinQ').value||'').trim().toUpperCase();
  if(!q){box.classList.remove('on');box.innerHTML='';return}
  let hit=COINS.filter(s=>s.includes(q));
  hit.sort((a,b)=>(a.indexOf(q)-b.indexOf(q))||(a.length-b.length));
  hit=hit.slice(0,18);
  box.innerHTML=hit.length?hit.map(s=>{
    const c=livePx(s);
    return `<div class="sr" data-sym="${s}"><span class="sy">${esc(symc(s))}</span>
      <span class="nm">${esc(s)}</span><span class="pv">${c?px(c):'—'}</span></div>`}).join('')
    :`<div class="none">no Binance USDT pair matches “${esc(q)}”</div>`;
  box.classList.add('on');
  [...box.querySelectorAll('.sr')].forEach(el=>el.onclick=()=>searchPick(el.dataset.sym));
}
function searchPick(s){
  $('coinQ').value='';$('coinRes').classList.remove('on');
  selectCoin(s);jump('p_plan');toast(`<b>${esc(symc(s))}/USDT</b> loaded — plan + chart updated`);
}
function searchInitUI(){
  const q=$('coinQ');if(!q)return;
  q.oninput=searchRender;q.onfocus=searchRender;
  q.onkeydown=ev=>{
    if(ev.key==='Escape'){$('coinRes').classList.remove('on');q.blur();return}
    if(ev.key==='Enter'){const f=$('coinRes').querySelector('.sr');if(f)searchPick(f.dataset.sym);return}
  };
  document.addEventListener('click',ev=>{if(!ev.target.closest('.srch'))$('coinRes').classList.remove('on')});
  searchInit();
}

/* ================= decisions ================= */
async function renderDecisions(){
  try{
    const d=await (await fetch('/api/decisions')).json();
    let L=(d.decisions||[]).slice().reverse();
    if(AGFLT)L=L.filter(x=>(x.agent||'')===AGFLT);
    DECS=L;
    $('dcMeta').innerHTML=(AGFLT?`<b>${esc(AGFLT)}</b> · `:'')+(L.length?`<b>${L.length}</b> recent`:'—');
    $('decisions').innerHTML=L.length?L.map(x=>{const a=x.action||'?';
      const cls=a.includes('ent')?'g':a.includes('exit')||a.includes('close')?'r':'y';
      return `<div class="dec clk" data-sym="${esc(x.symbol||'')}">
        <span class="t">${esc((x.ts||'').slice(11,19))}</span>
        <span class="tag ${cls}">${esc(a)}</span>
        <span class="r">${esc(x.symbol||'')} ${esc(x.reason||'')}</span></div>`}).join('')
      :'<div class="empty">no decisions yet</div>';
    [...$('decisions').querySelectorAll('[data-sym]')].forEach(el=>el.onclick=()=>{
      const s=el.dataset.sym;
      if(!s){toast('no symbol on this decision');return}
      const known=[...(STATE.watchlist||[]),...(STATE.market||[])].some(r=>r.symbol===s);
      if(known)selectCoin(s);else{toast(`<b>${esc(s)}</b> is not in the current sweep`);}});
  }catch(e){}
}

/* ================= feeds ================= */
function renderFeeds(f){
  FEEDS=f||{};
  const cats=f.catalysts||[], heads=f.headlines||[];
  const bull=cats.filter(c=>c.dir==='BULL').length, bear=cats.length-bull;
  $('catMeta').innerHTML=`<b>${cats.length}</b> catalysts · <b class="up">${bull}</b> bull / <b class="dn">${bear}</b> bear · `+
    `<b>${heads.length}</b> headlines`;
  let h='';
  if(cats.length){
    h+='<div class="secttl">Keyword catalysts — mapped to coins (click → load coin)</div>';
    h+=cats.slice(0,14).map(c=>`<div class="cat" data-sym="${esc(c.symbol)}" data-url="${esc(c.url||'')}" title="shift-click → open source">
      <span class="tag ${c.dir==='BULL'?'g':'r'}">${esc(c.dir)}</span>
      <span class="symc"><b>${symc(c.symbol)}</b></span>
      <span class="tt">${esc(c.source)} · ${esc(c.title)}</span></div>`).join('');
  }
  h+='<div class="secttl">Official · news · social feeds (click → open source)</div>';
  h+=heads.length?heads.slice(0,26).map(n=>`<div class="headline ${esc(n.kind||'news')}" data-url="${esc(n.url||'')}" data-title="${esc(n.title||'')}">
      <span class="sr">${esc(n.kind||'')} · ${esc(n.source||'')} <span class="tm">${hhmm(n.ts)}</span></span>
      <span class="tt">${esc(n.title)}</span></div>`).join(''):'<div class="empty">no headlines — feeds warming up</div>';
  $('catBody').innerHTML=h;
  [...$('catBody').querySelectorAll('.cat')].forEach(el=>el.onclick=ev=>{
    const s=el.dataset.sym;
    if(ev.shiftKey&&el.dataset.url){window.open(el.dataset.url,'_blank');return}
    if(s)selectCoin(s);if(el.dataset.url)window.open(el.dataset.url,'_blank');});
  [...$('catBody').querySelectorAll('.headline')].forEach(el=>el.onclick=ev=>{
    const u=el.dataset.url;const hit=coinFromText(el.dataset.title||'');
    if(u)window.open(u,'_blank');
    if(hit)selectCoin(hit);else if(!u)toast('no link and no matched coin');
    else if(!hit)toast('source opened — no coin matched by keyword engine');});

  // ---- source feeds panel: trending, fear&greed, derivatives, source health ----
  const tr=f.trending||[],fng=f.fng||{},fut=f.futures||{},src=f.sources||[];
  let s='';
  if(fng&&fng.value!==undefined)s+=`<div class="fngbox"><span class="fngv">${fng.value}</span>
      <span class="fngl">${esc(fng.label)}</span><span class="grow"></span>
      <span class="dim2" style="font-size:9px">FEAR &amp; GREED</span></div>`;
  if(tr.length){s+='<div class="secttl">CoinGecko trending (click → load coin)</div>';
    s+=tr.map((t,i)=>`<div class="fr clk" data-sym="${esc(t.symbol)}USDT">
      <span class="s">#${t.rank||i+1}</span>
      <span><b>${esc(t.symbol)}</b> <span class="dim2">${esc((t.name||'').slice(0,18))}</span></span>
      <span class="q ${sg(t.chg24h)}">${t.chg24h==null?'—':sx(t.chg24h)+'%'}</span></div>`).join('');}
  const fk=Object.keys(fut);
  if(fk.length){s+='<div class="secttl">Binance USD-M futures · OI / funding</div>';
    s+=fk.map(k=>{const r=fut[k]||{};return `<div class="fr clk" data-sym="${esc(k)}">
      <span class="s">${symc(k)}</span>
      <span class="dim2">OI ${fv(r.oi_usd)} <span class="${sg(r.oi_chg_pct)}">${sx(r.oi_chg_pct||0)}%</span></span>
      <span class="q">fund ${(+(r.funding||0)).toFixed(4)}%</span></div>`}).join('');}
  if(src.length){const nok=src.filter(x=>x.status==='ok').length;
    s+='<div class="secttl">Source health — last fetch result (click → jump to the panel)</div>';
    s+=src.map(x=>`<div class="fr clk" data-jump="${SRCPANEL[x.kind]||''}" title="${esc(x.name)} — ${esc(x.status)}${x.note?' · '+esc(x.note):''}">
      <span class="dot" style="width:6px;height:6px;border-radius:50%;background:${x.status==='ok'?'#0ECB81':'#525C66'}"></span>
      <span>${esc(x.name)} <span class="dim2" style="font-size:9px">${esc(x.note||'')}</span></span>
      <span class="q ${x.status==='ok'?'up':'dim2'}">${esc(x.status)}</span></div>`).join('');
    $('srcMeta').innerHTML=`<b>${nok}</b>/${src.length} sources ok`+
      (nok<src.length?` · <b class="dn">${src.length-nok}</b> waiting`:'');}
  else $('srcMeta').innerHTML='sources warming up';
  $('feedBody').innerHTML=s||'<div class="empty">no feeds</div>';
  [...$('feedBody').querySelectorAll('[data-sym]')].forEach(el=>el.onclick=()=>{
    const s2=el.dataset.sym;
    const known=[...(STATE.watchlist||[]),...(STATE.market||[])].some(r=>r.symbol===s2);
    if(known)selectCoin(s2);else{toast(`<b>${esc(s2)}</b> not in the sweep — opening TradingView`);
      window.open('https://www.tradingview.com/chart/?symbol='+encodeURIComponent('BINANCE:'+s2),'_blank')}});
  [...$('feedBody').querySelectorAll('[data-jump]')].forEach(el=>el.onclick=()=>{
    if(el.dataset.jump)jump(el.dataset.jump);else toast('no panel mapped for this source')});

  renderWhales(f);renderSurge(f);renderCatches(f);renderTGPush();
}
function coinFromText(txt){
  const uni=new Set();[...(STATE.watchlist||[]),...(STATE.market||[])].forEach(r=>uni.add(r.symbol));
  for(const sym of uni){const b=symc(sym);if(b.length<3)continue;
    if(new RegExp('\\$'+b+'\\b').test(txt)||new RegExp('\\b'+b+'\\b').test(txt))return sym}
  return '';
}
function renderWhales(f){
  const w=(f.whales||[]);
  $('whMeta').innerHTML=w.length?`<b>${w.length}</b> block trades`:'—';
  $('whBody').innerHTML=w.length?w.slice(0,20).map(x=>`<div class="fr clk" data-sym="${esc(x.symbol)}" data-px="${x.price}">
    <span class="s ${x.side==='BUY'?'up':'dn'}">${esc(x.side)}</span>
    <span><b>${symc(x.symbol)}</b> <span class="dim2">@ ${px(x.price)}</span></span>
    <span class="q">$${fv(x.notional)}</span></div>`).join(''):'<div class="empty">no block trades yet</div>';
  [...$('whBody').querySelectorAll('[data-sym]')].forEach(el=>el.onclick=ev=>{
    if(ev.shiftKey){pinLevel(+el.dataset.px,'whale '+symc(el.dataset.sym),'#2DD4BF');return}
    const known=[...(STATE.watchlist||[]),...(STATE.market||[])].some(r=>r.symbol===el.dataset.sym);
    if(known)selectCoin(el.dataset.sym);else toast(`<b>${esc(symc(el.dataset.sym))}</b> not in the sweep`)});
  const walls=(f.walls||[]);
  if(walls.length)$('whBody').insertAdjacentHTML('afterbegin',
    `<div class="secttl">Standing walls</div>`+walls.slice(0,8).map(x=>`<div class="fr clk" data-sym="${esc(x.symbol)}" data-px="${x.price}">
      <span class="s ${x.side==='BID'?'up':'dn'}">${esc(x.side)}</span>
      <span><b>${symc(x.symbol)}</b> <span class="dim2">@ ${px(x.price)}</span></span>
      <span class="q">$${fv(x.notional)}</span></div>`).join(''));
  [...$('whBody').querySelectorAll('[data-sym]')].forEach(el=>{if(!el.onclick)el.onclick=()=>selectCoin(el.dataset.sym)});
}
function renderSurge(f){
  const rows=(f.volume_surge||[]);
  $('vsMeta').innerHTML=rows.length?`<b>${rows.length}</b> surging`:'—';
  $('vsBody').innerHTML=rows.length?rows.slice(0,22).map(r=>`<div class="fr clk" data-sym="${esc(r.symbol)}">
    <span class="s gold">${(+r.volume_ratio||0).toFixed(1)}×</span>
    <span><b>${symc(r.symbol)}</b> <span class="dim2">${px(r.price)}</span></span>
    <span class="q"><span class="${sg(r.momentum_5m)}">${sx(r.momentum_5m||0)}%</span> · ${r.score||0}</span></div>`).join('')
    :'<div class="empty">no surge detected</div>';
  [...$('vsBody').querySelectorAll('[data-sym]')].forEach(el=>el.onclick=()=>selectCoin(el.dataset.sym));
}
function renderCatches(f){
  const rows=(f.catches||[]);
  const byAg={};rows.forEach(r=>byAg[r.agent]=(byAg[r.agent]||0)+1);
  $('cgMeta').innerHTML=rows.length?Object.entries(byAg).slice(0,3).map(([a,n])=>`<b>${esc(a)}</b> ${n}`).join(' · '):'—';
  $('cgBody').innerHTML=rows.length?rows.slice(0,22).map(r=>`<div class="fr clk" data-sym="${esc(r.symbol||'')}">
    <span class="s" style="color:${AGCOL[r.agent]||'#7C8792'}">${esc(r.kind||r.agent)}</span>
    <span>${r.symbol?`<b>${symc(r.symbol)}</b> `:''}<span class="dim2">${esc((r.detail||'').slice(0,52))}</span></span>
    <span class="q dim2">${hhmm(r.ts)}</span></div>`).join(''):'<div class="empty">nothing caught yet</div>';
  [...$('cgBody').querySelectorAll('[data-sym]')].forEach(el=>el.onclick=()=>{
    if(el.dataset.sym)selectCoin(el.dataset.sym);else toast('agent note — no symbol')});
}
/* pre-pump radar: rated hunt list (highest first) + the lead we keep following */
function renderPrepump(d){
  PP=d||{};const rows=(PP.coiled||[]);
  const coiled=rows.filter(r=>r.coiled);
  const w=(PP.watch&&PP.watch.symbol)?PP.watch:null;
  const min=+PP.rating_min||+PP.threshold||55;
  $('ppMeta').innerHTML=w
    ? `★ following <b>${symc(w.symbol)}</b> · rating ${(+w.rating||0).toFixed(0)} · ${coiled.length} coiled`
    : (rows.length?`<b>${coiled.length}</b> coiled · best rating ≥ ${min}`:'—');
  $('ppBody').innerHTML=rows.length?rows.map(r=>{
    const rt=+r.rating||0,col=rt>=70?'#0ECB81':rt>=55?'#F0B90B':'#525C66';
    const isLead=!!(w&&w.symbol===r.symbol);
    return `<div class="fr clk${isLead?' follow':''}" data-sym="${esc(r.symbol)}" title="${esc((r.reasons||[]).join(' · '))}">
      <span class="s" style="color:${col}">${isLead?'★':''}<b>${rt.toFixed(0)}</b></span>
      <span><b>${symc(r.symbol)}</b> <span class="up" title="bullish only">▲ BUY</span> <span class="dim2">${px(r.price)}</span>${r.catalyst?' <span class="cat">news</span>':''}</span>
      <span class="q"><span class="${sg(r.change)}">${sx(r.change||0)}%</span> <span class="dim2">${esc((r.reasons||[])[0]||'')}${r.volume_ratio?' · vol '+(+r.volume_ratio).toFixed(1)+'x':''}</span></span></div>`}).join('')
    :'<div class="empty">no candidates scored yet</div>';
  [...$('ppBody').querySelectorAll('[data-sym]')].forEach(el=>el.onclick=()=>selectCoin(el.dataset.sym));
  const mv=(PP.moving_now||[]);
  $('mvMeta').innerHTML=mv.length?`<b>${mv.length}</b> moving`:'—';
  $('mvBody').innerHTML=mv.length?mv.map(r=>`<div class="fr clk" data-sym="${esc(r.symbol)}">
      <span class="s" style="color:${(+r.change>=0)?'#0ECB81':'#F6465D'}">${sx(r.change)}%</span>
      <span><b>${symc(r.symbol)}</b> <span class="dim2">${px(r.price)}</span></span>
      <span class="q dim2">${fv(r.quote_volume)}</span></div>`).join('')
    :'<div class="empty">no 24h movers above 3%</div>';
  [...$('mvBody').querySelectorAll('[data-sym]')].forEach(el=>el.onclick=()=>selectCoin(el.dataset.sym));
}
/* gate strip: armed state, risk envelope, regime, first-move radar */
function renderGates(){
  const r=STATE.risk||{},rg=STATE.regime||{},rd=STATE.radar||{};
  const set=(box,val,note,cls,txt,sub)=>{
    const b=$(box),v=$(val),n=$(note);
    if(b)b.className='gate '+(cls||'');
    if(v)v.textContent=(txt==null||txt==='')?'—':txt;
    if(n)n.textContent=sub||'';
  };
  const live=!!STATE.live_orders;
  const perm=r.trade_perm, permBad=(live&&perm===false);
  set('gLive','gLiveV','gLiveN',permBad?'bad':(live?'warn':'ok'),
      live?(permBad?'NO PERM':'ARMED'):'PAPER',
      permBad?('key lacks Spot trading · '+(r.trade_perm_reason||'cannot place orders'))
        :(live?'real Binance orders · envelope on':'orders suppressed'));
  if(typeof r.ok!=='boolean'){
    set('gRisk','gRiskV','gRiskN','','—','waiting');
  }else{
    const dp=+r.day_pnl_pct||0,st=+r.loss_streak||0;
    let cls=r.ok?'ok':'bad',txt=r.ok?'OK':'HALT';
    if(!r.ok&&r.day_locked)txt='LOCKED';
    if(r.ok&&st>0)cls='warn';
    if(+r.pause_sec>0){cls='warn';txt='PAUSE '+Math.ceil(+r.pause_sec/60)+'m';}
    set('gRisk','gRiskV','gRiskN',cls,txt,
      (dp>=0?'+':'')+dp.toFixed(2)+'% today · streak '+st+'/'+(+r.max_consec_losses||3));
  }
  if(rg.zone==null){
    set('gRegime','gRegimeV','gRegimeN','','—','warming up');
  }else{
    const zone=String(rg.zone).replace(/_/g,' ');
    set('gRegime','gRegimeV','gRegimeN',zone==='RISK OFF'?'bad':(rg.stale?'warn':'ok'),
      zone+(rg.score!=null?' '+(+rg.score).toFixed(0):''),
      rg.error?('error: '+esc(rg.error)):(rg.stale?'stale':esc(rg.guidance||'entries allowed')));
  }
  if(rd.enabled===false){
    set('gRadar','gRadarV','gRadarN','warn','OFF','radar disabled');
  }else if(rd.rows==null){
    set('gRadar','gRadarV','gRadarN','','—','warming up');
  }else{
    const nm=(+rd.rows||0)+' names'+(STATE.firstmove_entries?' · '+(+STATE.firstmove_entries)+' fired':'');
    const sub=rd.error?('error: '+esc(rd.error))
      :(rd.stale?'stale radar':'')+((rd.age_sec!=null)?((rd.stale?' · ':'')+(+rd.age_sec).toFixed(0)+'s'):'')
        +((rd.chains&&rd.chains.length)?' · '+rd.chains.length+' chains':'');
    set('gRadar','gRadarV','gRadarN',rd.stale||rd.error?'warn':'ok',nm,sub||'synced');
  }
}
function renderTGPush(){
  const t=(STATE.telegram||{});
  $('tgMeta').innerHTML=t.enabled?'<b class="up">linked</b>':'<b class="dn">not linked</b>';
  $('tgBody').innerHTML=
    `<div class="gr"><span class="k">Bot</span><span class="v">@salehbincbot</span></div>
     <div class="gr"><span class="k">Chat</span><span class="v">${esc(t.chat||'—')}</span></div>
     <div class="gr"><span class="k">Status</span><span class="v ${t.enabled?'up':'dn'}">${t.enabled?'armed':'awaiting chat id'}</span></div>
     <div class="gr"><span class="k">Cards sent</span><span class="v">${t.sent||0}</span></div>
     <div class="gr"><span class="k">Cards</span><span class="v" style="font-size:10px">signal · entry · exit · daily · weekly</span></div>`;
}

/* ================= Fib & Gann panel ================= */
function renderTA(ta){
  TA=ta||null;
  if(!TA||!TA.levels){$('taMeta').textContent=SEL?'no structure':'select a coin';
    $('taHead').innerHTML='';$('taLevels').innerHTML='<div class="empty">no swing structure in this window</div>';return}
  const t=TA,f=t.fib||{},g=t.gann||{},n=t.nearest||{};
  $('taMeta').innerHTML=`<b>${symc(t.symbol)}</b> · ${esc(t.interval)} · ${esc(t.trend)}`;
  $('taHead').innerHTML=
    `<div class="gr" data-jump="p_chart"><span class="m ${t.bias==='LONG'?'ok':''}">${t.bias==='LONG'?'▲':t.bias==='SHORT'?'▼':'·'}</span>
      <span class="k">Confluence</span><span class="v ${t.bias==='LONG'?'up':t.bias==='SHORT'?'dn':''}">${esc(t.bias)} ${t.score}/100</span></div>
     <div class="gr"><span class="m">·</span><span class="k">Fib retrace position</span>
      <span class="v">${(+f.position||0).toFixed(3)} <span class="dim2">${(f.position>=0.382&&f.position<=0.618)?'golden pocket':(f.position>0.786?'deep':'holding')}</span></span></div>
     <div class="gr"><span class="m">·</span><span class="k">Gann 1x1</span><span class="v">${px(g.fan&&g.fan['1x1'])}</span></div>
     <div class="gr"><span class="m">·</span><span class="k">Nearest support</span><span class="v">${n.support?px(n.support.price):'—'}</span></div>
     <div class="gr"><span class="m">·</span><span class="k">Nearest resistance</span><span class="v">${n.resistance?px(n.resistance.price):'—'}</span></div>`;
  [...$('taHead').querySelectorAll('[data-jump]')].forEach(el=>el.onclick=()=>jump(el.dataset.jump));
  const price=+t.price||0;
  const rows=(t.levels||[]).slice().sort((a,b)=>b.price-a.price);
  $('taLevels').innerHTML=rows.map(l=>{const d=price?((l.price-price)/price*100):0;
    const on=PINS.some(p=>Math.abs(p.price-l.price)<1e-12);
    return `<div class="lv k-${esc(l.kind)} ${on?'pinned':''}" data-px="${l.price}" data-lab="${esc(l.label)}" data-kind="${esc(l.kind)}">
      <span class="k">${esc(l.label)}</span>
      <span class="dim2" style="text-align:center">${on?'pinned':''}</span>
      <span class="p">${px(l.price)} <span class="dim2">${d>=0?'+':''}${d.toFixed(2)}%</span></span></div>`}).join('');
  [...$('taLevels').querySelectorAll('.lv')].forEach(el=>el.onclick=()=>{
    const p=+el.dataset.px,lab=el.dataset.lab,kind=el.dataset.kind;
    const i=PINS.findIndex(x=>Math.abs(x.price-p)<1e-12);
    if(i>=0)PINS.splice(i,1);else PINS.push({price:p,label:lab,color:LVCOL[kind]||'#F0B90B'});
    drawPins();renderTA(TA);
    toast(i>=0?`unpinned <b>${esc(lab)}</b>`:`pinned <b>${esc(lab)}</b> @ ${px(p)} on the chart`);
  });
}
function renderTAReasons(){/* reasons shown inline in the confluence row */}

/* ================= chart ================= */
function initChart(){
  const el=$('chartBox');el.innerHTML='';
  chart=LightweightCharts.createChart(el,{
    layout:{background:{color:'#0A0C0F'},textColor:'#7C8792',fontFamily:"'Azeret Mono',monospace",fontSize:10},
    grid:{vertLines:{color:'#131A1E'},horzLines:{color:'#131A1E'}},
    rightPriceScale:{borderColor:'#1E252B',scaleMargins:{top:0.08,bottom:0.22}},
    timeScale:{borderColor:'#1E252B',timeVisible:true,secondsVisible:false},
    crosshair:{mode:0,vertLine:{color:'#F0B90B',width:1,style:3,labelBackgroundColor:'#F0B90B'},
      horzLine:{color:'#F0B90B',width:1,style:3,labelBackgroundColor:'#F0B90B'}},
    width:el.clientWidth,height:el.clientHeight});
  cs=chart.addCandlestickSeries({upColor:'#0ECB81',downColor:'#F6465D',borderUpColor:'#0ECB81',
    borderDownColor:'#F6465D',wickUpColor:'#0ECB81',wickDownColor:'#F6465D',priceLineColor:'#F0B90B'});
  vs=chart.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'',
    priceLineVisible:false,lastValueVisible:false});
  chart.priceScale('').applyOptions({scaleMargins:{top:0.86,bottom:0}});
  new ResizeObserver(()=>{try{chart.applyOptions({width:el.clientWidth,height:el.clientHeight})}catch(e){}}).observe(el);
  chart.subscribeClick(p=>{if(!p||!p.point)return;
    if(chart&&cs){/* click the chart to pin the exact price under the cursor */}
    const price=cs.coordinateToPrice(p.point.y);
    if(price){pinLevel(+price,'pinned',  '#F0B90B');
      toast(`pinned chart level <b>${px(price)}</b>`);}});
}
function clearPins(){if(cs){PINS.forEach(l=>{try{cs.removePriceLine(l._line)}catch(e){}})}}
function drawPins(){
  if(!cs)return;
  PINS.forEach(p=>{try{if(p._line)cs.removePriceLine(p._line)}catch(e){}});
  PINS.forEach(p=>{try{p._line=cs.createPriceLine({price:+p.price,color:p.color||'#F0B90B',
    lineWidth:1,lineStyle:2,axisLabelVisible:true,title:p.label||''})}catch(e){}});
}
function pinLevel(price,label,color){if(!price)return;PINS.push({price:+price,label:label,color:color||'#F0B90B'});drawPins()}
async function loadChart(sym){
  if(!chart)initChart();
  try{
    const d=await (await fetch(`/api/chart/${sym}?interval=${TF}&limit=${TF_LIMIT[TF]||240}`)).json();
    const C=[],V=[];
    (d.candles||[]).forEach(k=>{const t=tsx(Math.floor(k.t/1000));
      C.push({time:t,open:k.o,high:k.h,low:k.l,close:k.c});
      V.push({time:t,value:k.v,color:(k.c>=k.o?'rgba(14,203,129,.42)':'rgba(246,70,93,.42)')})});
    if(!C.length){$('chartBox').innerHTML='<div class="empty">no candles for '+esc(sym)+'</div>';return}
    const lp=C[C.length-1].close;
    const prec=lp>=1000?2:lp>=1?4:lp>=0.01?6:8;
    cs.applyOptions({priceFormat:{type:'price',precision:prec,minMove:Math.pow(10,-prec)}});
    cs.setData(C);vs.setData(V);chart.timeScale().fitContent();drawPins();
    $('chartPx').textContent=px(lp);
    $('chartMeta').innerHTML=`<b>${symc(sym)}/USDT</b> · ${esc(TF)} · BINANCE`;
    $('chartTfNote').textContent=TF;
  }catch(e){}
}
async function loadTA(sym){
  try{const d=await (await fetch(`/api/ta/${sym}?interval=${TF}&limit=${Math.max(120,(TF_LIMIT[TF]||240))}`)).json();
    renderTA(d)}catch(e){renderTA(null)}
}

/* ================= order book / flow ================= */
/* drawBook + drawFlow are shared by the REST first paint and the live websocket
   streams, so the panels have exactly one rendering path. */
function drawBook(B,A){
  if(!B.length&&!A.length){$('obBody').innerHTML='<div class="empty">no depth — illiquid (excluded by gate)</div>';return}
  const mx=Math.max(...[...B,...A].map(x=>x.q),1);
  const mid=B.length&&A.length?(B[0].p+A[0].p)/2:(B[0]?B[0].p:A[0].p);
  const spr=B.length&&A.length?((A[0].p-B[0].p)/mid*100):0;
  const rw=(x,side)=>`<div class="rw ${side} clk" data-px="${x.p}" title="click → pin this level on the chart">
    <i style="width:${(x.q/mx*100).toFixed(1)}%"></i>
    <span>${px(x.p)}</span><span>${(+x.q).toLocaleString(undefined,{maximumFractionDigits:2})}</span></div>`;
  $('obBody').innerHTML=`<div class="hd"><span>Price</span><span>Size</span></div>
    ${A.slice(0,9).reverse().map(a=>rw(a,'ask')).join('')}
    <div class="mid">${px(mid)} <span class="dim2" style="font-size:9px">spread ${spr.toFixed(3)}%</span></div>
    ${B.slice(0,9).map(b=>rw(b,'bid')).join('')}`;
  [...$('obBody').querySelectorAll('[data-px]')].forEach(el=>el.onclick=()=>{
    pinLevel(+el.dataset.px,'book','#93C5FD');toast(`pinned book level <b>${px(el.dataset.px)}</b>`)});
}
async function loadBook(){
  if(!SEL)return;
  if(curBookSym!==SEL){$('obSymT').textContent=SEL;curBookSym=SEL}
  if(WSFLAG.tape)return;                     // the depth stream is live — polling would fight it
  try{
    const d=await (await fetch('/api/orderbook/'+SEL)).json();
    drawBook((d.bids||[]).map(x=>({p:+x.p,q:+x.q})),(d.asks||[]).map(x=>({p:+x.p,q:+x.q})));
  }catch(e){$('obBody').innerHTML='<div class="empty">unavailable</div>'}
}
function drawFlow(T){
  if(!T.length){$('flBody').innerHTML='<div class="empty">no trades</div>';return}
  let bv=0,sv=0;T.forEach(x=>{const u=x.p*x.q;if(x.m)sv+=u;else bv+=u});
  const tot=bv+sv||1,bp=bv/tot*100,delta=bv-sv;
  const rows=T.slice(-18).reverse().map(x=>{const sell=x.m;
    return `<div class="fr clk" data-px="${x.p}">
      <span class="s ${sell?'dn':'up'}">${sell?'SELL':'BUY'}</span>
      <span>${px(x.p)}</span>
      <span class="q">${(+x.q).toLocaleString(undefined,{maximumFractionDigits:2})} <span class="dim2">${hhmm(x.t)}</span></span></div>`}).join('');
  $('flBody').innerHTML=rows+`<div class="sum">
    <span>Buy <b class="up">$${fv(bv)}</b> <span class="dim2">${bp.toFixed(0)}%</span></span>
    <span>Sell <b class="dn">$${fv(sv)}</b></span>
    <span>Δ <b class="${delta>=0?'up':'dn'}">${delta>=0?'+':'-'}$${fv(Math.abs(delta))}</b></span></div>`;
  [...$('flBody').querySelectorAll('[data-px]')].forEach(el=>el.onclick=()=>{
    pinLevel(+el.dataset.px,'tape','#2DD4BF');toast(`pinned tape level <b>${px(el.dataset.px)}</b>`)});
}
async function loadFlow(){
  if(!SEL)return;
  $('flSymT').textContent=SEL;
  if(WSFLAG.tape)return;                     // the aggTrade stream is live
  try{
    const d=await (await fetch('/api/recent/'+SEL)).json();
    drawFlow((d.trades||[]).map(x=>({p:+x.p,q:+x.q,m:!!x.m,t:x.t})));
  }catch(e){$('flBody').innerHTML='<div class="empty">unavailable</div>'}
}

/* ================= REAL-TIME BINANCE STREAMS =================
   Everything price-bearing on this dashboard reads from Binance websockets:

     !miniTicker@arr      → every USDT pair, ~1s   → all price cells
     <sym>@depth20@100ms  → the order book, live   → Order Book panel
     <sym>@aggTrade       → the tape, live         → Volume Flow panel

   REST stays only as the first paint and as a fallback when a socket is down. */
const WS_BASE='wss://stream.binance.com:9443';
const LIVE={px:{}};
const WSFLAG={market:false,tape:false};
let wsMarket=null,wsSym=null;
let wsSymKey=null;
let depthPending=null,depthTimer=null,flowTimer=null;
const TAPE={sym:null,rows:[]};

function wsBadge(){
  const d=$('wsDot');if(!d)return;
  const n=[WSFLAG.market,WSFLAG.tape].filter(Boolean).length;
  d.className='wsdot '+(n?'on':'off');
  d.innerHTML=(n?'● LIVE BINANCE':'● REST POLL')+` <span class="dim2">ws ${n}/2</span>`;
  d.title='Binance websockets — market-wide prices · order book + tape';
}

/* ---- market-wide prices: ONE socket covers every listed pair ---- */
function wsMarketConnect(){
  try{if(wsMarket)wsMarket.close()}catch(e){}
  try{wsMarket=new WebSocket(WS_BASE+'/ws/!miniTicker@arr')}catch(e){return}
  wsMarket.onopen=()=>{WSFLAG.market=true;wsBadge()};
  wsMarket.onerror=()=>{};
  wsMarket.onclose=()=>{WSFLAG.market=false;wsBadge();setTimeout(wsMarketConnect,4000)};
  wsMarket.onmessage=ev=>{
    let a;try{a=JSON.parse(ev.data)}catch(e){return}
    if(!Array.isArray(a))return;
    for(let i=0;i<a.length;i++){
      const t=a[i],s=t.s;
      if(!s||s.slice(-4)!=='USDT')continue;
      const o=+t.o||0,c=+t.c||0;
      LIVE.px[s]={c:c,o:o,h:+t.h||0,l:+t.l||0,q:+t.q||0,chg:o?(c-o)/o*100:0};
    }
  };
}

/* ---- the in-page Binance kline chart is gone; the chart is TradingView only ---- */

/* ---- order book + tape for the selected coin, live ---- */
function symbolStream(sym){
  if(!sym)return;
  if(wsSymKey===sym&&wsSym&&wsSym.readyState===1)return;
  wsSymKey=sym;TAPE.sym=null;TAPE.rows=[];
  try{if(wsSym)wsSym.close()}catch(e){}
  const l=sym.toLowerCase();
  try{wsSym=new WebSocket(WS_BASE+'/stream?streams='+l+'@depth20@100ms/'+l+'@aggTrade')}catch(e){return}
  wsSym.onopen=()=>{WSFLAG.tape=true;wsBadge()};
  wsSym.onerror=()=>{};
  wsSym.onclose=()=>{WSFLAG.tape=false;wsBadge();
    if(SEL===sym&&wsSymKey===sym)setTimeout(()=>symbolStream(sym),4000)};
  wsSym.onmessage=ev=>{
    let m;try{m=JSON.parse(ev.data)}catch(e){return}
    const st=m.stream||'',d=m.data;
    if(!d||wsSymKey!==SEL)return;
    if(st.indexOf('@depth')>=0)onDepth(d);
    else if(st.indexOf('aggTrade')>=0)onAggTrade(d);
  };
}
function onDepth(d){
  depthPending={B:(d.bids||[]).map(x=>({p:+x[0],q:+x[1]})),A:(d.asks||[]).map(x=>({p:+x[0],q:+x[1]}))};
  if(depthTimer)return;
  depthTimer=setTimeout(()=>{depthTimer=null;const p=depthPending;depthPending=null;if(p)drawBook(p.B,p.A)},220);
}
function onAggTrade(d){
  if(TAPE.sym!==SEL){TAPE.sym=SEL;TAPE.rows=[]}
  TAPE.rows.push({p:+d.p,q:+d.q,m:!!d.m,t:+d.T});
  if(TAPE.rows.length>160)TAPE.rows.shift();
  if(flowTimer)return;
  flowTimer=setTimeout(()=>{flowTimer=null;drawFlow(TAPE.rows)},260);
}

/* ---- paint live prices into every cell that carries a symbol ---- */
function patchLive(){
  if(!WSFLAG.market)return;
  const L=LIVE.px;
  for(const el of document.querySelectorAll('[data-lp]')){
    const r=L[el.dataset.lp];if(!r)continue;
    const txt=px(r.c);
    if(el.textContent!==txt){
      const was=+el.dataset.last||0;
      el.textContent=txt;el.dataset.last=r.c;
      if(was&&r.c!==was){el.classList.remove('tick-up','tick-dn');void el.offsetWidth;
        el.classList.add(r.c>was?'tick-up':'tick-dn');
        clearTimeout(el._tt);el._tt=setTimeout(()=>el.classList.remove('tick-up','tick-dn'),480)}
    }
  }
  for(const el of document.querySelectorAll('[data-lc]')){
    const r=L[el.dataset.lc];if(!r)continue;
    const t=sx(r.chg)+'%';
    if(el.textContent!==t){el.textContent=t;el.classList.toggle('up',r.chg>=0);el.classList.toggle('dn',r.chg<0)}
  }
  /* footer price of the selected coin — the chart is a TradingView widget now, so the
     live last price keeps flowing from the Binance miniTicker socket instead of klines */
  if(SEL&&L[SEL]){const el=$('chartPx');if(el){const t=px(L[SEL].c);if(el.textContent!==t)el.textContent=t}}
}

/* ================= chart: TradingView only, Binance live feed =================
   There is one chart: the TradingView widget, loaded with the BINANCE: symbol, so
   the candles are Binance data drawn by TradingView with its full tool set. The
   in-page lightweight chart is gone; CHART_SRC is kept as the single switch so
   every guard in this file reads the chart source from one place. Live prices,
   the order book and the tape still stream straight from Binance websockets. */
const CHART_SRC='tradingview';
let tvLoading=false;
const TVINT={'1m':'1','5m':'5','15m':'15','1h':'60','4h':'240','1d':'D'};
function initTV(sym){
  const box=$('tvBox');
  const build=()=>{
    box.innerHTML='<div id="tvchart" style="height:100%;width:100%"></div>';
    try{
      new TradingView.widget({
        container_id:'tvchart',autosize:true,
        symbol:'BINANCE:'+sym,interval:TVINT[TF]||'1',
        timezone:(TZ.name||'Etc/UTC'),
        theme:'dark',style:'1',locale:'en',
        toolbar_bg:'#0F1316',
        enable_publishing:false,allow_symbol_change:true,
        hide_side_toolbar:false,hide_top_toolbar:false,withdateranges:true,
        details:false,save_image:false,studies:[],
        backgroundColor:'rgba(10,12,15,1)',gridColor:'rgba(19,26,30,1)'
      });
    }catch(e){toast('TradingView widget error: '+esc(e.message))}
  };
  $('chartMeta').innerHTML=`<b>${symc(sym)}/USDT</b> · ${esc(TF)} · TRADINGVIEW`;
  if(window.TradingView){build();return}
  if(tvLoading)return;
  tvLoading=true;
  const s=document.createElement('script');
  s.src='https://s3.tradingview.com/tv.js';
  s.onload=()=>{tvLoading=false;if(CHART_SRC==='tradingview'&&SEL)build()};
  s.onerror=()=>{tvLoading=false;
    box.innerHTML='<div class="empty" style="position:absolute;inset:0;display:grid;place-items:center">TradingView widget could not load (network blocked) — use ◆ BINANCE LIVE</div>'};
  document.head.appendChild(s);
}

/* ================= select ================= */
function selectCoin(sym){
  if(!sym)return;
  SEL=sym;
  [...document.querySelectorAll('[data-sym]')].forEach(t=>t.classList.toggle('sel',t.dataset.sym===sym));
  $('tvLink').style.display='inline';
  $('tvLink').href='https://www.tradingview.com/chart/?symbol='+encodeURIComponent('BINANCE:'+sym);
  $('obSymT').textContent=sym;$('flSymT').textContent=sym;
  const inShort=(STATE.watchlist||[]).some(r=>r.symbol===sym);
  if(!inShort)toast(`<b>${esc(sym)}</b> loaded — not in the deep-scan shortlist`);
  /* force the REST first paint for the new coin, then let the live streams take over */
  WSFLAG.tape=false;curBookSym=null;curFlowSym=null;
  initTV(sym);
  loadTA(sym);loadBook();loadFlow();renderPlan(sym);
  symbolStream(sym);
  if($('alwBox')&&$('alwBox').classList.contains('on'))alwFill(true);
}

/* ================= loop ================= */
async function tick(){
  try{
    const [sR,swR]=await Promise.all([fetch('/api/status'),fetch('/api/swarm')]);
    STATE=await sR.json();
    let sw={};try{sw=await swR.json()}catch(e){}
    renderHead(STATE);renderAgents(sw);
    renderGates();
    renderShort(STATE.watchlist||[]);
    renderMarket(STATE.market||[]);
    renderTicker(STATE.market||[]);
    renderPositions(STATE.positions_detail||[]);
    renderFollow();renderAltfins();
    renderTGPush();
  }catch(e){}
}
async function feedsTick(){
  try{
    const [fR,pR]=await Promise.all([fetch('/api/feeds'),fetch('/api/prepump')]);
    const f=await fR.json();renderFeeds(f);
    try{renderPrepump(await pR.json())}catch(e){}
  }catch(e){}
}

/* ---------- timeframe ---------- */
TFINIT();
function TFINIT(){
  [...$('tfbar').querySelectorAll('button')].forEach(b=>{
    b.onclick=()=>{
      TF=b.dataset.tf;
      [...$('tfbar').querySelectorAll('button')].forEach(x=>x.classList.toggle('on',x===b));
      $('chartTfNote').textContent=TF;PINS=[];drawPins();tickCandle();
      if(SEL){
        /* label immediately, so the header never lags the chip while the reload lands */
        $('chartMeta').innerHTML=`<b>${symc(SEL)}/USDT</b> · ${esc(TF)} · TRADINGVIEW`;
        initTV(SEL);loadTA(SEL);
      }
      toast(`timeframe <b>${esc(TF)}</b> applied to chart + Fib/Gann`);
    };
  });
}

/* ---------- static click wiring ---------- */
$('btnToggle').onclick=async()=>{try{await fetch('/toggle',{method:'POST'});tick()}catch(e){}};
$('taClear').onclick=()=>{PINS=[];drawPins();renderTA(TA);toast('chart levels cleared')};
$('taPin').onclick=()=>{if(!TA||!TA.levels){toast('nothing to pin');return}
  PINS=(TA.levels||[]).map(l=>({price:l.price,label:l.label,color:LVCOL[l.kind]||'#F0B90B'}));
  drawPins();renderTA(TA);toast(`pinned <b>${PINS.length}</b> Fib/Gann levels`)};
$('tgTest').onclick=async()=>{try{const r=await (await fetch('/api/notify?test=1')).json();
  toast(r.sent?'<b>Telegram</b> test card sent':'Telegram test failed: <b>'+esc(r.last_error||'not linked')+'</b>');
  tick()}catch(e){}};
$('tgDisc').onclick=async()=>{try{const r=await (await fetch('/api/notify?discover=1')).json();
  toast(r.chat?`chat discovered: <b>${esc(r.chat)}</b>`:'no chat yet — send the bot any message first');tick()}catch(e){}};
/* ---------- armed alerts: you set the level, the hunter fires the card ----------
   An alert is not a message you send. It is ARMED, re-checked every few seconds by
   the engine, and the Telegram card is pushed only when the price actually crosses
   the level or the armed clock arrives. "- send now" is the single manual path and
   exists only to test the pipe. */
const ALERT_TYPES=['CROSS UP','CROSS DOWN','ABOVE','BELOW','TIME'];
function normSym(raw){
  let s=String(raw||'').trim().toUpperCase();
  if(!s&&SEL)s=SEL;
  if(s&&!LIVE.px[s]&&LIVE.px[s+'USDT'])s=s+'USDT';
  return s;
}
const alertErr=r=>(r&&(r.error||(r.status&&r.status.last_error)))||'telegram not linked';
async function postAlert(body){
  try{
    return await(await fetch('/api/alert',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)})).json();
  }catch(e){return{error:'request failed'}}
}
/* arm it — it fires itself */
async function armAlert(o){
  const sym=normSym(o.sym);
  if(!sym)return{ok:false,error:'type a symbol — e.g. BTCUSDT'};
  const type=String(o.type||'CROSS UP').trim().toUpperCase();
  if(ALERT_TYPES.indexOf(type)<0)return{ok:false,error:'unknown trigger '+type};
  const body={symbol:sym,alert_type:type};
  const p=parseFloat(o.px);
  if(isFinite(p)&&p>0)body.price=p;
  const at=String(o.at||'').trim();
  if(at)body.at=at;
  const note=String(o.note||'').trim();
  if(note)body.note=note;
  if(type!=='TIME'&&!body.price)return{ok:false,error:type+' needs a target price'};
  if(type==='TIME'&&!body.at)return{ok:false,error:'TIME needs a clock — e.g. 14:30'};
  const r=await postAlert(body);
  if(r.error)return{ok:false,error:String(r.error)};
  if(r.alerts)renderAlerts(r.alerts);
  return{ok:!!r.armed,alert:r.alert,sym,type};
}
/* the ONE manual path — test the pipe, do not trade on it */
async function sendNow(o){
  const sym=normSym(o.sym);
  if(!sym)return{ok:false,error:'type a symbol — e.g. BTCUSDT'};
  const type=String(o.type||'CROSS UP').trim().toUpperCase();
  const body={symbol:sym,alert_type:type,immediate:true};
  const p=parseFloat(o.px);
  if(isFinite(p)&&p>0)body.price=p;
  const note=String(o.note||'').trim();
  if(note)body.note=note;
  const r=await postAlert(body);
  return{ok:!!r.sent&&!r.error,error:r.error?String(r.error):alertErr(r),sym,type,px:body.price};
}
function alertItem(a,fired){
  const id=esc(String(a.id||'')),tgt=a.price?px(a.price):'';
  const l1=`${esc(a.symbol||'')} <span class="dim2">· ${esc(a.type||'')}${tgt?' · '+tgt:''}</span>`;
  let l2='',l3='';
  if(fired){
    const fp=(a.fired_price!=null)?px(a.fired_price):'';
    let hit='';
    if(a.price&&a.fired_price!=null){
      const h=(a.fired_price-a.price)/a.price*100;
      hit=` <b class="${h>=0?'up':'dn'}">${h>=0?'+':''}${h.toFixed(3)}%</b>`;
    }
    l2=`fired ${fp?'@ '+fp:''}${hit} <span class="dim2">· ${a.fired_reason==='time'?'clock reached':'price crossed'}</span>`;
    l3=esc(a.fired_at_disp||'');
  }else{
    let d='';
    if(a.price&&a.last!=null){
      const pct=(a.last-a.price)/a.price*100;
      d=` <b class="${pct>=0?'up':'dn'}">${Math.abs(pct).toFixed(2)}% ${pct>=0?'above':'below'} target</b>`;
    }
    l2=(a.last!=null?('live '+px(a.last)):'no tick yet')+d;
    if(a.when_disp)l3='fires NY '+esc(String(a.when_disp).slice(0,11).trim());
  }
  const note=a.note?`<div class="l4" title="${esc(a.note)}">${esc(a.note)}</div>`:'';
  return `<div class="aitem${fired?' fired':''}">`
    +(fired?'':`<span class="ax" data-cancel="${id}" title="disarm this alert">✕</span>`)
    +`<div class="l1">${l1}</div><div class="l2">${l2}</div>`
    +(l3?`<div class="l3">${l3}</div>`:'')+note+`</div>`;
}
function renderAlerts(v){
  if(!v)return;
  ALERTS=v;
  const rows=[].concat((v.armed||[]).map(a=>alertItem(a,false)),(v.fired||[]).map(a=>alertItem(a,true)));
  const html=rows.length?rows.join('')
    :'<div class="aempty">no armed alerts — set a level or a time, then arm one</div>';
  ['alwList','tgAlerts'].forEach(id=>{const el=$(id);if(el)el.innerHTML=html});
  document.querySelectorAll('[data-cancel]').forEach(el=>el.onclick=()=>cancelAlert(el.dataset.cancel));
  const n=(v.counts&&v.counts.armed)||0,f=(v.counts&&v.counts.fired)||0;
  const badge=$('alwCount');
  if(badge)badge.innerHTML=n?`<b class="gold">${n}</b> armed${f?' · '+f+' fired':''}`:(f?f+' fired':'no armed alerts');
}
async function cancelAlert(id){
  try{
    const r=await(await fetch('/api/alert/cancel',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:String(id)})})).json();
    if(r.alerts)renderAlerts(r.alerts);
    toast(r.cancelled?'alert <b>disarmed</b>':'that alert is already spent');
  }catch(e){toast('could not disarm that alert')}
}
/* panel row (Telegram Push) — arms an alert */
$('alSend').onclick=async()=>{
  const r=await armAlert({sym:$('alSym').value,type:$('alType').value,px:$('alPx').value,
                          at:$('alWhen').value,note:$('alNote').value});
  if(r.ok){
    const a=r.alert||{};
    $('alNote').value='';$('alWhen').value='';
    toast(`alert <b>armed</b> — ${esc(a.symbol||'')} ${esc(a.type||'')}`
      +(a.price?' @ '+px(a.price):'')+(a.when_disp?' · NY '+esc(String(a.when_disp).slice(0,11).trim()):'')
      +' will fire itself');
  }else toast('not armed — <b>'+esc(r.error)+'</b>');
};

/* floating widget — stays on screen while you work inside the chart */
function alwLive(){
  /* LIVE.px holds a miniTicker object per symbol; `.c` is the close price */
  const s=$('alwSym').value.trim().toUpperCase();
  const x=LIVE.px[s]||LIVE.px[s+'USDT'];
  const c=x?+x.c:NaN;
  return isFinite(c)&&c>0?c:null;
}
let alwPinned=false;   /* an arm/send result stays on screen until the next interaction */
function alwFill(force){
  const b=$('alwBox');if(!b||!b.classList.contains('on'))return;
  if(force||!$('alwSym').value)$('alwSym').value=SEL||'';
  if(force)alwPinned=false;
  const sym=$('alwSym').value.trim().toUpperCase(),live=alwLive();
  if(force&&live&&$('alwType').value!=='TIME')$('alwPx').value=live;
  if(!alwPinned)$('alwStatus').innerHTML=live?`live <b class="gold">${px(live)}</b> · ${esc(sym)}`
    :(sym?`no live tick for <b>${esc(sym)}</b>`:'type a symbol, or select a coin');
}
function alwOpen(on){
  const b=$('alwBox');if(!b)return;
  b.classList.toggle('on',on);b.setAttribute('aria-hidden',on?'false':'true');
  $('alOpen').classList.toggle('on',on);
  if(on)alwFill(true);
}
if($('alOpen')){
  $('alOpen').onclick=()=>alwOpen(!$('alwBox').classList.contains('on'));
  $('alwClose').onclick=()=>alwOpen(false);
  $('alwSym').oninput=()=>{alwPinned=false;alwFill(false)};
  $('alwType').onchange=()=>{alwPinned=false;$('alwPx').disabled=($('alwType').value==='TIME');
    $('alwWhen').placeholder=$('alwType').value==='TIME'?'required — e.g. 14:30':'optional — e.g. 14:30'};
  $('alwLive').onclick=()=>{alwPinned=false;const l=alwLive();
    if(l){$('alwPx').value=l;alwFill(true)}
    else toast('no live tick for <b>'+esc($('alwSym').value.trim().toUpperCase()||'—')+'</b>')};
  $('alwArm').onclick=async()=>{
    const btn=$('alwArm');btn.disabled=true;alwPinned=true;$('alwStatus').textContent='arming…';
    const r=await armAlert({sym:$('alwSym').value,type:$('alwType').value,px:$('alwPx').value,
                            at:$('alwWhen').value,note:$('alwNote').value});
    btn.disabled=false;
    if(r.ok){
      const a=r.alert||{};
      $('alwStatus').innerHTML=`<b class="up">armed</b> · ${esc(a.type||'')} ${esc(a.symbol||'')}`
        +(a.price?' @ '+px(a.price):'')+(a.when_disp?' · NY '+esc(String(a.when_disp).slice(0,11).trim()):'');
      $('alwNote').value='';$('alwWhen').value='';
      toast(`alert <b>armed</b> — fires itself when `
        +(a.price?px(a.price)+' is crossed':'the clock arrives'));
    }else{
      $('alwStatus').innerHTML=`<b class="dn">not armed</b> · ${esc(r.error)}`;
      toast('not armed — <b>'+esc(r.error)+'</b>');
    }
  };
  $('alwSend').onclick=async()=>{
    const btn=$('alwSend');btn.disabled=true;alwPinned=true;$('alwStatus').textContent='sending…';
    const r=await sendNow({sym:$('alwSym').value,type:$('alwType').value,
                           px:$('alwPx').value,note:$('alwNote').value});
    btn.disabled=false;
    $('alwStatus').innerHTML=r.ok?`<b class="up">sent</b> · ${esc(r.type)} ${esc(r.sym)}${r.px?' @ '+px(r.px):''}`
                                :`<b class="dn">failed</b> · ${esc(r.error)}`;
    if(r.ok)$('alwNote').value='';
    toast(r.ok?`card pushed now · <b>${esc(r.sym)}</b>`:'send failed — <b>'+esc(r.error)+'</b>');
  };
  /* drag it anywhere by the header */
  let drag=null;
  $('alwHead').onmousedown=e=>{const b=$('alwBox'),r=b.getBoundingClientRect();
    drag={dx:e.clientX-r.left,dy:e.clientY-r.top};
    b.style.right='auto';b.style.bottom='auto';b.style.left=r.left+'px';b.style.top=r.top+'px';
    document.body.style.userSelect='none';e.preventDefault()};
  document.addEventListener('mousemove',e=>{if(!drag)return;const b=$('alwBox');
    b.style.left=clamp(e.clientX-drag.dx,4,innerWidth-b.offsetWidth-4)+'px';
    b.style.top=clamp(e.clientY-drag.dy,4,innerHeight-40)+'px'});
  document.addEventListener('mouseup',()=>{if(drag){drag=null;document.body.style.userSelect=''}});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('alwBox').classList.contains('on'))alwOpen(false)});
  setInterval(()=>alwFill(false),1000);
}
/* keep the armed board honest even with the widget closed */
async function pollAlerts(){try{renderAlerts(await(await fetch('/api/alerts')).json())}catch(e){}}
setInterval(pollAlerts,4000);
pollAlerts();
$('fwBack').onclick=async()=>{const t=$('fwBt');const old=t.innerHTML;t.textContent='replaying history…';
  try{await (await fetch('/api/backtest_all?fresh=1&limit=6')).json();tick();
    t.innerHTML=old;toast('backtest <b>complete</b> — base rate refreshed on the panel')}
  catch(e){t.textContent='backtest failed'}};
searchInitUI();
const KJ=[['kBal','p_pos'],['kTgt','p_pos'],['kPnl','p_pos'],['kPos','p_pos'],['kTr','p_dec'],['kSw','p_market'],['kCd','p_market'],['kSig','p_dec']];
KJ.forEach(([k,id])=>{const e=$(k);if(e&&e.closest('.kpi'))e.closest('.kpi').onclick=()=>jump(id)});
$('pill').onclick=()=>jump('p_dec','engine state: '+(STATE.running?'HUNTING':'PAUSED'));
$('mProg').closest('.mission').onclick=()=>jump('p_pos','mission $9 → $20');

/* ---------- boot ---------- */
tick();renderDecisions();feedsTick();
/* real-time Binance: market-wide price socket + the live-price painter */
wsMarketConnect();wsBadge();setInterval(patchLive,220);
setInterval(tick,5000);
setInterval(feedsTick,10000);
setInterval(renderDecisions,8000);
setInterval(()=>{if(SEL){loadBook();loadFlow()}},6000);
setInterval(()=>{if(SEL)renderPlan(SEL)},15000);
setInterval(()=>{if(SEL){loadBook();loadFlow();loadTA(SEL)}},12000);
setInterval(()=>{$('clk').textContent=clockStr();tickCandle()},1000);tickCandle();
