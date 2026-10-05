/* Edge Board site. Every page loads data.js (window.EDGE, written by weekly.py) and this file.
   The page to render comes from <main data-page="...">. */
(function(){
'use strict';
const D=window.EDGE;
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const MINUS='−';
const odds=o=>o==null||!isFinite(o)?'—':(o>0?'+':MINUS)+Math.abs(Math.round(o));
const pct=p=>(p*100).toFixed(0)+'%';
const units=u=>(u>0?'+':u<0?MINUS:'±')+Math.abs(u).toFixed(2)+'u';
const signed=(x,d=1)=>(x>0?'+':x<0?MINUS:'')+Math.abs(x).toFixed(d);
const PLAYOFF={19:'Wild Card',20:'Divisional',21:'Conference',22:'Super Bowl'};
const SHORT={19:'WC',20:'DIV',21:'CONF',22:'SB'};
const wkName=w=>PLAYOFF[w]||('Week '+w);
const wkShort=w=>SHORT[w]||('Wk '+w);
const NAME={}; (D.teams||[]).forEach(t=>NAME[t.team]=t.name);
const teamHref=t=>`teams.html#${encodeURIComponent(t)}`;
const day=s=>{const [y,m,d]=s.split('-').map(Number); return Date.UTC(y,m-1,d)/864e5;};
const MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const fmtDay=s=>{const [y,m,d]=s.split('-').map(Number); return `${MONTHS[m-1]} ${d}`;};

function lineTxt(line, home, away){
  if(line==null) return '—';
  if(line===0) return 'PK';
  return (line>0?home:away)+' '+MINUS+Math.abs(line);
}
function cls(u){return u>0?'ok':u<0?'no':'push';}

/* ======================= shared chrome ======================= */
function chrome(){
  $$('[data-stamp]').forEach(el=>el.textContent='Updated '+D.updatedLabel);
  const oddsTxt=D.oddsFetched?` Sportsbook prices: The Odds API, ${D.oddsGames} games, fetched ${new Date(D.oddsFetched).toLocaleString([], {weekday:'short',hour:'numeric',minute:'2-digit'})}.`:'';
  $$('[data-foot]').forEach(el=>el.textContent=
    `Updated ${D.updatedLabel}. Elo home field ${D.hfa} · blend ${Math.round(D.blendW*100)}% Elo · wind threshold ${D.windMph} mph.${oddsTxt}`);
}

/* ======================= line chart ======================= */
/* series: [{name, n (1|2), points:[{x,y,tip}]}]; xTicks:[{x,label}]; refY: dashed reference line */
function lineChart(box, opt){
  const draw=()=>{
    const W=Math.max(300, box.clientWidth), H=opt.height||250;
    const narrow=W<520;
    const m={t:12,r:(opt.endLabels&&!narrow)?118:14,b:26,l:46};
    const all=opt.series.flatMap(s=>s.points);
    if(!all.length){ box.innerHTML=`<p class="why">${esc(opt.empty||'No data yet.')}</p>`; return; }
    const xs=all.map(p=>p.x), ys=all.map(p=>p.y).concat(opt.refY!=null?[opt.refY]:[]).concat(opt.zero?[0]:[]);
    let x0=Math.min(...xs), x1=Math.max(...xs); if(x0===x1){x0-=1;x1+=1;}
    let y0=Math.min(...ys), y1=Math.max(...ys); if(y0===y1){y0-=1;y1+=1;}
    const ticks=niceTicks(y0,y1,5); y0=Math.min(y0,ticks[0]); y1=Math.max(y1,ticks[ticks.length-1]);
    const X=x=>m.l+(x-x0)/(x1-x0)*(W-m.l-m.r), Y=y=>m.t+(1-(y-y0)/(y1-y0))*(H-m.t-m.b);
    let s=`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opt.label)}">`;
    ticks.forEach(t=>{ s+=`<line class="gridline" x1="${m.l}" x2="${W-m.r}" y1="${Y(t)}" y2="${Y(t)}"/>
      <text class="tick" x="${m.l-8}" y="${Y(t)+4}" text-anchor="end">${opt.yFmt?opt.yFmt(t):t}</text>`; });
    if(opt.zero&&y0<0&&y1>0) s+=`<line class="zero" x1="${m.l}" x2="${W-m.r}" y1="${Y(0)}" y2="${Y(0)}"/>`;
    if(opt.refY!=null) s+=`<line class="ref" x1="${m.l}" x2="${W-m.r}" y1="${Y(opt.refY)}" y2="${Y(opt.refY)}"/>`;
    let last=-1e9;
    (opt.xTicks||[]).forEach(t=>{ const px=X(t.x); if(px<m.l-1||px>W-m.r+1||px-last<46) return; last=px;
      s+=`<text class="tick" x="${px}" y="${H-6}" text-anchor="middle">${esc(t.label)}</text>`; });
    opt.series.forEach(se=>{
      if(!se.points.length) return;
      const d=se.points.map((p,i)=>(i?'L':'M')+X(p.x).toFixed(1)+','+Y(p.y).toFixed(1)).join('');
      s+=`<path class="line s${se.n}" d="${d}"/>`;
      const e=se.points[se.points.length-1];
      s+=`<circle class="d${se.n}" cx="${X(e.x)}" cy="${Y(e.y)}" r="4.5"/>`;
      if(opt.endLabels&&!narrow) s+=`<text class="dlabel" x="${X(e.x)+9}" y="${Y(e.y)+4}">${esc(se.name)} ${esc(opt.yFmt?opt.yFmt(e.y):e.y)}</text>`;
    });
    s+=`<line class="cross" x1="0" x2="0" y1="${m.t}" y2="${H-m.b}" visibility="hidden"/>`;
    s+=`<rect x="${m.l}" y="0" width="${W-m.l-m.r}" height="${H}" fill="transparent"/></svg><div class="tip" hidden></div>`;
    box.innerHTML=s;
    const svg=box.querySelector('svg'), cross=svg.querySelector('.cross'), tip=box.querySelector('.tip');
    const move=ev=>{
      const r=svg.getBoundingClientRect(); const px=(ev.clientX-r.left);
      const xv=x0+(px-m.l)/(W-m.l-m.r)*(x1-x0);
      let best=null; all.forEach(p=>{ if(!best||Math.abs(p.x-xv)<Math.abs(best.x-xv)) best=p; });
      if(!best){return;}
      const cx=X(best.x); cross.setAttribute('x1',cx); cross.setAttribute('x2',cx); cross.setAttribute('visibility','visible');
      tip.innerHTML=opt.tip(best.x); tip.hidden=false;
      const tw=tip.offsetWidth; tip.style.left=Math.min(Math.max(0,cx+12), W-tw)+'px'; tip.style.top='8px';
      if(cx+12+tw>W) tip.style.left=Math.max(0,cx-12-tw)+'px';
    };
    const leave=()=>{cross.setAttribute('visibility','hidden'); tip.hidden=true;};
    svg.addEventListener('pointermove',move); svg.addEventListener('pointerleave',leave);
  };
  draw();
  box._draw=draw;                                   // one resize listener per chart box, even if redrawn
  if(!box._bound){ box._bound=true; let t=null;
    window.addEventListener('resize',()=>{clearTimeout(t); t=setTimeout(()=>box._draw(),150);}); }
}
function niceTicks(a,b,n){
  const span=b-a, step0=span/n, mag=Math.pow(10,Math.floor(Math.log10(step0)));
  const step=[1,2,2.5,5,10].map(k=>k*mag).find(k=>span/k<=n)||10*mag;
  const out=[]; for(let v=Math.floor(a/step)*step; v<=b+step*0.999; v+=step) out.push(Math.round(v*1e6)/1e6);
  return out;
}
function monthTicks(d0,d1){
  const out=[]; const a=new Date(d0*864e5), b=new Date(d1*864e5);
  let y=a.getUTCFullYear(), mo=a.getUTCMonth()+1;
  while(Date.UTC(y,mo,1)<=b.getTime()){ if(mo>11){mo=0;y++;} out.push({x:Date.UTC(y,mo,1)/864e5,label:MONTHS[mo]}); mo++; }
  return out;
}

/* ======================= week page ======================= */
function weekPage(){
  let week=D.currentWeek, filter='all';
  const m=location.hash.match(/^#week(\d+)$/); if(m) week=Number(m[1]);
  const weeks=[...new Set(D.games.map(g=>g.wk))].sort((a,b)=>a-b);
  if(!weeks.includes(week)) week=D.currentWeek;

  function rail(){
    $('#rail').innerHTML=weeks.map(w=>`<button type="button" class="wk ${w===D.currentWeek?'cur':''}" data-wk="${w}" aria-pressed="${w===week}">${wkShort(w)}</button>`).join('');
    const on=$('#rail .wk[aria-pressed="true"]'); if(on) on.scrollIntoView({block:'nearest',inline:'center'});
  }
  function probRow(label,pA,pH,cA,cH,g){
    return `<span class="lab">${label}</span><div class="pbar"><span class="pv">${esc(g.away)} ${pct(pA)}</span>
      <span class="track" role="img" aria-label="${label}: ${esc(g.awayName)} ${pct(pA)}, ${esc(g.homeName)} ${pct(pH)}">
      <span style="width:${pA*100}%;background:${cA}"></span><span style="width:${pH*100}%;background:${cH}"></span></span>
      <span class="pv r">${pct(pH)} ${esc(g.home)}</span></div>`;
  }
  function windCall(g){
    if(g.roof==='dome'||g.roof==='closed') return `<div class="call"><span class="tag none">Indoors</span><span class="why">No wind call</span></div>`;
    if(g.wind==null) return `<div class="call"><span class="tag none">Wind pending</span><span class="why">Forecast appears within 15 days of kickoff</span></div>`;
    const src=g.windSrc==='live'?(g.status==='upcoming'?'latest forecast':'last forecast before kickoff'):'archived forecast';
    const bu=g.shop&&g.shop.total&&g.shop.total.under;
    const tot=bu?` · under ${bu.point} at ${bu.cents.toFixed(0)}¢ on ${esc(bu.book)}${bu.ev!=null?` (${signed(bu.ev)}% vs books)`:''}`
      :g.total&&g.total.line!=null?` · under ${g.total.line}${g.total.uo?' ('+odds(g.total.uo)+')':''}`:'';
    if(g.signal==='under') return `<div class="call"><span class="tag under">UNDER signal</span><span class="num">${g.wind.toFixed(1)} mph</span><span class="why">${src}${tot} · 1% stake</span></div>`;
    if(g.signal==='roof') return `<div class="call"><span class="tag roof">Windy · roof?</span><span class="num">${g.wind.toFixed(1)} mph</span><span class="why">${src} · retractable roof, bet only if open</span></div>`;
    return `<div class="call"><span class="tag none">No wind signal</span><span class="num">${g.wind.toFixed(1)} mph</span><span class="why">${src}</span></div>`;
  }
  function leanCall(g){
    if(!g.mkt) return `<div class="call"><span class="tag none">No line yet</span><span class="why">Elo only until the moneyline is posted</span></div>`;
    if(!g.mkt.lean) return `<div class="call"><span class="tag none">No Elo lean</span><span class="why">Neither side is +EV after blending with the market</span></div>`;
    const t=g.mkt.lean==='home'?g.homeName:g.awayName;
    const price=g.mkt.leanCents!=null
      ?`<span class="num">${g.mkt.leanCents.toFixed(0)}¢</span> on ${esc(g.mkt.leanBook)}`
      :`<span class="num">${odds(g.mkt.leanOdds)}</span>`;
    return `<div class="call"><span class="tag lean">Elo lean</span><span>${esc(t)} ${price}</span><span class="why">EV +${g.mkt.leanEv.toFixed(1)}% · historically ${MINUS}7.1%, check the news</span></div>`;
  }
  function shopBlock(g){
    const s=g.shop; if(!s) return '';
    const o=(x,pt)=>{
      if(!x) return '<span class="push">—</span>';
      const p=pt&&x.point!=null?(pt==='s'&&x.point>0?'+':'')+x.point+' ':'';
      const ev=x.ev==null?'<span class="push">other line</span>'
        :`<span class="${x.ev>=D.gapEv?'ok':x.ev<0?'no':'push'}">${signed(x.ev)}%</span>`;
      return `${p}<span class="num">${x.cents.toFixed(0)}¢</span> <span class="bk">${esc(x.book)}</span> ${ev}`;
    };
    return `<div class="shop"><div class="lab">Your markets · price after fees vs fair price from ${s.books} sportsbook${s.books===1?'':'s'}</div>
      <div class="shoprow"><span class="k">ML</span><span>${esc(g.away)} ${o(s.ml.away)}</span><span>${esc(g.home)} ${o(s.ml.home)}</span></div>
      <div class="shoprow"><span class="k">Spread</span><span>${esc(g.away)} ${o(s.spread.away,'s')}</span><span>${esc(g.home)} ${o(s.spread.home,'s')}</span></div>
      <div class="shoprow"><span class="k">Total</span><span>Over ${o(s.total.over,'p')}</span><span>Under ${o(s.total.under,'p')}</span></div></div>`;
  }
  function gapTxt(g,x){
    const who=x.mk==='total'?(x.side==='over'?'Over':'Under')+' '+x.point
      :(x.side==='home'?g.homeName:g.awayName)+(x.mk==='spread'?' '+(x.point>0?'+':'')+x.point:'');
    return `${esc(who)} at ${x.cents.toFixed(0)}¢ on ${esc(x.book)}`;
  }
  function result(g){
    if(g.status!=='final') return '';
    const b=[];
    if('eloRight' in g) b.push(`Elo <span class="${g.eloRight?'ok':'no'}">${g.eloRight?'✓':'✗'}</span>`);
    if(g.mkt&&'mktRight' in g.mkt) b.push(`Market <span class="${g.mkt.mktRight?'ok':'no'}">${g.mkt.mktRight?'✓':'✗'}</span>`);
    if(g.mkt&&'leanUnits' in g.mkt) b.push(`Lean <span class="${cls(g.mkt.leanUnits)}">${units(g.mkt.leanUnits)}</span>`);
    if('underUnits' in g) b.push(`Under <span class="${cls(g.underUnits)}">${units(g.underUnits)}</span>`);
    if(g.windRecorded!=null) b.push(`<span class="push">recorded wind ${g.windRecorded} mph</span>`);
    return b.length?`<div class="res">${b.join('')}</div>`:'';
  }
  function card(g){
    const f=g.status==='final', aw=f&&g.as>g.hs, hw=f&&g.hs>g.as;
    const status=f?'<span class="chip final">Final</span>':g.status==='live'?'<span class="chip live">Started</span>':'';
    const intl=g.neutral||/Tottenham|Wembley|Allianz|Deutsche|Bernabeu|Azteca|Banorte|Maracan|Corinthians/.test(g.stadium||'');
    const mk=g.mkt, sp=g.spread, tt=g.total;
    const foot=result(g)+(g.notes||[]).map(n=>`<span class="note">${esc(n)}</span>`).join('');
    return `<article class="game ${g.signal==='under'?'sig':''}" id="g-${esc(g.id)}">
      <header class="ghead">
        <div class="match"><a href="${teamHref(g.away)}">${esc(g.awayName)}</a>${f?`<span class="sc ${aw?'w':'l'}">${g.as}</span>`:''}
          <span class="at">@</span><a href="${teamHref(g.home)}">${esc(g.homeName)}</a>${f?`<span class="sc ${hw?'w':'l'}">${g.hs}</span>`:''}</div>
        <div class="chips"><span class="chip">${esc(g.ko)}</span>${status}${intl?`<span class="chip venue">${esc(g.stadium)}</span>`:''}</div>
      </header>
      <div class="gbody">
        <div class="probs">${probRow('Elo',1-g.pElo,g.pElo,'var(--away)','var(--home)',g)}
          ${mk?probRow('Market',1-mk.fair,mk.fair,'var(--mkt-away)','var(--mkt-home)',g):'<span class="lab">Market</span><span class="na">No line yet</span>'}</div>
        <dl class="ledger">
          <div><dt>Spread</dt><dd>${sp?lineTxt(sp.line,g.home,g.away):'—'}<small>Elo ${lineTxt(g.eloLine,g.home,g.away)}</small></dd></div>
          <div><dt>Total</dt><dd>${tt&&tt.line!=null?tt.line:'—'}<small>${tt&&tt.oo?'o '+odds(tt.oo)+' · u '+odds(tt.uo):'&nbsp;'}</small></dd></div>
          <div><dt>Moneyline</dt>${!mk?'<dd>—<small>&nbsp;</small></dd>':mk.aml!=null
            ?`<dd>${esc(g.away)} ${odds(mk.aml)}<small>${esc(g.home)} ${odds(mk.hml)}</small></dd>`
            :`<dd>${esc(g.home)} ${pct(mk.fair)}<small>fair, books</small></dd>`}</div>
        </dl>
        ${shopBlock(g)}
        <div class="calls">${windCall(g)}${leanCall(g)}</div>
      </div>
      ${foot?`<footer class="gfoot">${foot}</footer>`:''}
    </article>`;
  }
  function render(){
    rail();
    const gs=D.games.filter(g=>g.wk===week);
    const fin=gs.filter(g=>g.status==='final').length, lines=gs.filter(g=>g.mkt).length;
    const sig=gs.filter(g=>g.signal==='under'), leans=gs.filter(g=>g.mkt&&g.mkt.lean).length;
    const gaps=gs.filter(g=>g.status==='upcoming'&&g.gaps&&g.gaps.length);
    $('#weekEyebrow').textContent=`${D.season} season${week===D.currentWeek?' · current week':''}`;
    $('#weekTitle').textContent=wkName(week);
    $('#weekSub').textContent=gs.length?`${gs[0].ko.split(' · ')[0]} – ${gs[gs.length-1].ko.split(' · ')[0]}`:'';
    $('#kpis').innerHTML=`
      <div class="kpi"><div class="v">${gs.length}</div><div class="l">Games · ${fin} final</div></div>
      <div class="kpi"><div class="v ${sig.length?'good':''}">${sig.length}</div><div class="l">Wind under signals</div></div>
      <div class="kpi"><div class="v ${gaps.length?'good':''}">${D.oddsFetched?gaps.length:'—'}</div><div class="l">Price gaps ≥ ${D.gapEv}% after fees (untested)</div></div>
      <div class="kpi"><div class="v accent">${leans}</div><div class="l">Elo leans (historically ${MINUS}7.1%)</div></div>`;
    const open=sig.filter(g=>g.status==='upcoming');
    $('#playsWrap').hidden=!(open.length||gaps.length);
    $('#plays').innerHTML=open.map(g=>{
      const bu=g.shop&&g.shop.total&&g.shop.total.under;
      const vs=bu&&(bu.ev==null?' (different line from the books, check the price)':` (${signed(bu.ev)}% vs books before the wind edge)`);
      const where=bu?` · under ${bu.point} at ${bu.cents.toFixed(0)}¢ on ${esc(bu.book)}${vs}`
        :g.total&&g.total.line!=null?' · under '+g.total.line+(g.total.uo?' '+odds(g.total.uo):''):'';
      return `<div class="play"><span class="tag under">UNDER</span>
      <span class="what">${esc(g.awayName)} @ ${esc(g.homeName)}${where}</span>
      <span class="num">${g.wind.toFixed(1)} mph</span><span class="why">${esc(g.ko)} · flat 1% stake · re-check the forecast before kickoff</span>
      <a class="why" href="#g-${esc(g.id)}">See game</a></div>`;}).join('')
      +gaps.flatMap(g=>g.gaps.map(x=>`<div class="play gap"><span class="tag lean">PRICE GAP</span>
      <span class="what">${gapTxt(g,x)}</span><span class="num ok">${signed(x.ev)}%</span>
      <span class="why">${esc(g.awayName)} @ ${esc(g.homeName)} · vs the sportsbooks' fair price, after fees · check the live order book first</span>
      <a class="why" href="#g-${esc(g.id)}">See game</a></div>`)).join('');
    const shown=gs.filter(g=>filter==='all'||(filter==='wind'&&g.signal)||(filter==='gap'&&g.gaps&&g.gaps.length)||(filter==='lean'&&g.mkt&&g.mkt.lean)||(filter==='final'&&g.status==='final'));
    shown.sort((a,b)=>(a.signal==='under'||(a.gaps&&a.gaps.length)?0:1)-(b.signal==='under'||(b.gaps&&b.gaps.length)?0:1));
    $('#games').innerHTML=shown.map(card).join('')||`<div class="empty">No games match this filter in ${esc(wkName(week))}.</div>`;
  }
  document.addEventListener('click',e=>{
    const b=e.target.closest('[data-wk]');
    if(b){ week=Number(b.dataset.wk); filter='all';
      $$('#filters button').forEach(x=>x.setAttribute('aria-pressed',x.dataset.f==='all'));
      try{history.replaceState(null,'','#week'+week);}catch(_){}
      render(); return; }
    const f=e.target.closest('[data-f]');
    if(f){ filter=f.dataset.f; $$('#filters button').forEach(x=>x.setAttribute('aria-pressed',x===f)); render(); }
  });
  // Two views on this page: the week board and "My bets" (#bets). The tracker lives here
  // because the home page is where the claude.ai viewer grants the database.
  function route(){
    const bets=location.hash==='#bets';
    $('#betsView').hidden=!bets; $('#weekView').hidden=bets; $('#rail').hidden=bets;
    $('#navWeek').toggleAttribute('aria-current',!bets); $('#navBets').toggleAttribute('aria-current',bets);
    if(bets){ $('#navBets').setAttribute('aria-current','page'); betsView(); }
    else { $('#navWeek').setAttribute('aria-current','page'); render(); }
  }
  window.addEventListener('hashchange',route);
  route();
}

/* ======================= bet tracker ======================= */
const VENUE={kalshi:'Kalshi',polymarket:'Polymarket',other:'Other'};
const REASON={wind:'Wind under',gap:'Price gap',lean:'Elo lean',other:'Other'};
const GAME=new Map(D.games.map(g=>[g.id,g]));
const feePer=(venue,p)=>((D.fees||{})[venue]||0)*p*(1-p);          // $ per $1 contract

function betText(b,g){
  const team=s=>g?(s==='home'?g.homeName:g.awayName):s;
  if(b.mk==='ml') return `${team(b.side)} to win`;
  if(b.mk==='spread') return `${team(b.side)} ${b.point>0?'+':''}${b.point}`;
  return `${b.side==='over'?'Over':'Under'} ${b.point}`;
}
function betMath(b){
  const g=GAME.get(b.gid), p=b.cents/100, n=b.n, fee=feePer(b.venue,p)*n;
  const out={g,cost:n*p+fee,fee};
  if(!g) return out;
  const cf=g.closeFair;
  if(cf&&g.status!=='upcoming'){                        // kicked off: nflverse lines are the close
    const eff=1/(p+feePer(b.venue,p));
    let pf=null, pts=null;
    if(b.mk==='ml'&&cf.home!=null) pf=b.side==='home'?cf.home:1-cf.home;
    if(b.mk==='spread'&&cf.spreadLine!=null){
      pts=b.point-(b.side==='home'?-cf.spreadLine:cf.spreadLine);   // more points = better
      if(pts===0&&cf.spreadHome!=null) pf=b.side==='home'?cf.spreadHome:1-cf.spreadHome;
    }
    if(b.mk==='total'&&cf.total!=null){
      pts=b.side==='under'?b.point-cf.total:cf.total-b.point;
      if(pts===0&&cf.over!=null) pf=b.side==='over'?cf.over:1-cf.over;
    }
    if(pf!=null) out.clvEv=(pf*eff-1)*100;
    if(pts) out.clvPts=pts;
    out.beat=out.clvPts!=null?out.clvPts>0:out.clvEv!=null?out.clvEv>0:null;
  }
  if(g.status==='final'){
    const m=b.mk==='ml'?(b.side==='home'?g.hs-g.as:g.as-g.hs)
      :b.mk==='spread'?(b.side==='home'?g.hs-g.as:g.as-g.hs)+b.point
      :b.side==='over'?(g.hs+g.as)-b.point:b.point-(g.hs+g.as);
    out.result=m>0?'won':m<0?'lost':'push';
    out.pl=m>0?n*(1-p)-fee:m<0?-n*p-fee:-fee;
  }
  return out;
}
function fairNow(g,mk,side,point){
  const f=g&&g.shop&&g.shop.fair; if(!f) return null;
  if(mk==='ml'&&f.home!=null) return side==='home'?f.home:1-f.home;
  if(mk==='spread'&&f.spreadHome!=null){
    if(side==='home'&&point===f.spreadPoint) return f.spreadHome;
    if(side==='away'&&point===-f.spreadPoint) return 1-f.spreadHome;
  }
  if(mk==='total'&&f.over!=null&&point===f.totalPoint) return side==='over'?f.over:1-f.over;
  return null;
}

/* Storage: the claude.ai page's private database when available, else this browser. */
async function betStore(){
  let db=null;
  try{ if(window.claude&&window.claude.use) db=await window.claude.use('db'); }catch(_){}
  if(db){
    const col=db.collection('bets');
    return {kind:'db',
      subscribe:(cb,err)=>col.onSnapshot(s=>cb(s.docs.map(d=>Object.assign({id:d.id},d.data()))),err),
      add:b=>col.add(b), remove:id=>col.doc(id).delete()};
  }
  const K='edgeboard.bets.v1', subs=[];
  const read=()=>{try{return JSON.parse(localStorage.getItem(K))||[];}catch(_){return [];}};
  const write=a=>{try{localStorage.setItem(K,JSON.stringify(a));}catch(_){} subs.forEach(f=>f(a));};
  return {kind:'local',
    subscribe:cb=>{subs.push(cb); cb(read()); return ()=>{};},
    add:b=>{write(read().concat([Object.assign({id:Date.now().toString(36)+Math.random().toString(36).slice(2,6)},b)])); return Promise.resolve();},
    remove:id=>{write(read().filter(x=>x.id!==id)); return Promise.resolve();}};
}

let betsReady=false, store=null, bets=[];
function betsView(){
  if(betsReady) return; betsReady=true;
  const money=v=>(v<0?MINUS:'')+'$'+Math.abs(v).toFixed(2);
  // ---- form ----
  const up=D.games.filter(g=>g.status!=='final'&&g.wk<=D.currentWeek+1);
  const fin=D.games.filter(g=>g.status==='final');
  const opt=g=>`<option value="${esc(g.id)}">${wkShort(g.wk)} · ${esc(g.awayName)} @ ${esc(g.homeName)} · ${esc(g.ko.split(' · ')[0])}</option>`;
  const finWeeks=[...new Set(fin.map(g=>g.wk))].sort((a,b)=>b-a);
  $('#bGame').innerHTML=(up.length?`<optgroup label="Upcoming">${up.map(opt).join('')}</optgroup>`:'')
    +finWeeks.map(w=>`<optgroup label="${esc(wkName(w))} · final">${fin.filter(g=>g.wk===w).map(opt).join('')}</optgroup>`).join('');
  const sides=()=>{
    const g=GAME.get($('#bGame').value), mk=$('#bMarket').value;
    $('#bSide').innerHTML=mk==='total'?'<option value="under">Under</option><option value="over">Over</option>'
      :`<option value="away">${esc(g.awayName)}</option><option value="home">${esc(g.homeName)}</option>`;
    $('#bPointWrap').hidden=mk==='ml';
    prefill();
  };
  const prefill=()=>{
    const g=GAME.get($('#bGame').value), mk=$('#bMarket').value, side=$('#bSide').value;
    const o=g.shop&&g.shop[mk]&&g.shop[mk][side];
    let pt=o&&o.point!=null?o.point:null;
    if(pt==null&&mk==='spread'&&g.spread) pt=side==='home'?-g.spread.line:g.spread.line;
    if(pt==null&&mk==='total'&&g.total) pt=g.total.line;
    $('#bPoint').value=pt==null?'':pt;
    $('#bCents').value=o?o.cents.toFixed(0):'';
    if(o&&VENUE[o.key]) $('#bVenue').value=o.key;
    preview();
  };
  const preview=()=>{
    const g=GAME.get($('#bGame').value), mk=$('#bMarket').value, side=$('#bSide').value;
    const p=Number($('#bCents').value)/100, n=Number($('#bQty').value)||0;
    if(!(p>0&&p<1)||!n){ $('#bPreview').textContent='Enter the price you paid and how many contracts.'; return; }
    const fee=feePer($('#bVenue').value,p)*n, point=mk==='ml'?null:Number($('#bPoint').value);
    const pf=fairNow(g,mk,side,point);
    const ev=pf==null?'':` · ${signed((pf/(p+fee/n)-1)*100)}% vs the books' fair price now`;
    $('#bPreview').textContent=`Costs about ${money(n*p+fee)} incl. ~${money(fee)} fees · pays $${n.toFixed(0)} if it wins${ev}`;
  };
  $('#bGame').addEventListener('change',sides);
  $('#bMarket').addEventListener('change',sides);
  $('#bSide').addEventListener('change',prefill);
  ['bCents','bQty','bPoint','bVenue'].forEach(id=>$('#'+id).addEventListener('input',preview));
  sides();

  $('#betForm').addEventListener('submit',async e=>{
    e.preventDefault();
    if(!store){ $('#bStatus').textContent='Still connecting to your saved bets. Try again in a moment.'; return; }
    const mk=$('#bMarket').value, cents=Number($('#bCents').value), n=Math.round(Number($('#bQty').value));
    const point=mk==='ml'?null:Number($('#bPoint').value);
    if(!(cents>0&&cents<100)||!(n>=1)||(mk!=='ml'&&!isFinite(point))||$('#bPoint').value===''&&mk!=='ml'){
      $('#bStatus').textContent='Check the line, price (1–99¢) and contracts.'; return; }
    const doc={gid:$('#bGame').value,mk,side:$('#bSide').value,point,venue:$('#bVenue').value,
      cents,n,reason:$('#bReason').value,note:$('#bNote').value.trim().slice(0,140),placed:new Date().toISOString(),v:1};
    $('#bSave').disabled=true; $('#bStatus').textContent='Saving…';
    try{ await store.add(doc); $('#bStatus').textContent='Saved.'; $('#bNote').value=''; }
    catch(err){ $('#bStatus').textContent=err&&err.code==='quota_exceeded'?'Storage is full. Delete old bets to add more.':'Couldn’t save. Try again.'; }
    finally{ $('#bSave').disabled=false; }
  });

  // ---- table, tiles, chart ----
  document.addEventListener('click',async e=>{
    const del=e.target.closest('[data-del]'); if(!del) return;
    if(del.dataset.armed!=='1'){ del.dataset.armed='1'; del.textContent='Confirm'; setTimeout(()=>{del.dataset.armed=''; del.textContent='Delete';},3000); return; }
    del.disabled=true; try{ await store.remove(del.dataset.del); }catch(_){ del.disabled=false; del.textContent='Delete'; }
  });
  const draw=()=>{
    const rows=bets.map(b=>Object.assign({b},betMath(b))).sort((x,y)=>(y.b.placed||'').localeCompare(x.b.placed||''));
    const settled=rows.filter(r=>r.result), won=settled.filter(r=>r.result==='won').length, lost=settled.filter(r=>r.result==='lost').length;
    const pl=settled.reduce((s,r)=>s+r.pl,0), staked=settled.reduce((s,r)=>s+r.cost,0);
    const judged=rows.filter(r=>r.beat!=null), beat=judged.filter(r=>r.beat).length;
    const evs=rows.filter(r=>r.clvEv!=null);
    $('#betKpis').innerHTML=`
      <div class="kpi"><div class="v">${rows.length}</div><div class="l">Bets · ${rows.length-settled.length} open</div></div>
      <div class="kpi"><div class="v ${pl>0?'good':pl<0?'bad':''}">${settled.length?money(pl):'—'}</div><div class="l">Profit · ${won}–${lost}${settled.length-won-lost?'–'+(settled.length-won-lost):''}${staked?` · ROI ${signed(pl/staked*100)}%`:''}</div></div>
      <div class="kpi"><div class="v ${judged.length&&beat/judged.length>0.5?'good':''}">${judged.length?Math.round(beat/judged.length*100)+'%':'—'}</div><div class="l">Beat the closing line (${judged.length} judged)</div></div>
      <div class="kpi"><div class="v">${evs.length?signed(evs.reduce((s,r)=>s+r.clvEv,0)/evs.length)+'%':'—'}</div><div class="l">Average value vs close (${evs.length} same-line bets)</div></div>`;
    $('#betTable').innerHTML=`<thead><tr><th>Game</th><th>Bet</th><th>Where</th><th class="n">Price</th><th class="n">Cost</th><th>Why</th><th class="n">vs close</th><th class="n">Result</th><th></th></tr></thead>
      <tbody>${rows.map(r=>{const b=r.b,g=r.g;
        const vs=r.clvPts!=null?`<span class="${r.clvPts>0?'ok':'no'}">${signed(r.clvPts)} pt</span>`
          :r.clvEv!=null?`<span class="${r.clvEv>0?'ok':'no'}">${signed(r.clvEv)}%</span>`:'<span class="push">—</span>';
        const res=r.result?`<span class="${r.pl>0?'ok':r.pl<0?'no':'push'}">${r.result} ${money(r.pl)}</span>`
          :`<span class="push">${g?(g.status==='live'?'in play':'open'):'unknown game'}</span>`;
        return `<tr><td>${g?`${wkShort(g.wk)} · ${esc(g.away)} @ ${esc(g.home)}`:esc(b.gid)}</td>
          <td>${esc(betText(b,g))}${b.note?`<div class="push" style="font-size:11.5px">${esc(b.note)}</div>`:''}</td>
          <td>${esc(VENUE[b.venue]||b.venue)}</td><td class="n">${Number(b.cents).toFixed(0)}¢ ×${b.n}</td>
          <td class="n">${money(r.cost)}</td><td>${esc(REASON[b.reason]||b.reason)}</td>
          <td class="n">${vs}</td><td class="n">${res}</td>
          <td><button type="button" class="btn ghost small" data-del="${esc(b.id)}">Delete</button></td></tr>`;}).join('')
        ||'<tr><td colspan="9" class="push">No bets yet. Add your first one above.</td></tr>'}</tbody>`;
    let cum=0; const pts=settled.slice().sort((x,y)=>x.g.date<y.g.date?-1:1).map((r,i)=>({x:i+1,y:Math.round((cum+=r.pl)*100)/100,r}));
    lineChart($('#betChart'),{label:'Running profit in dollars, settled bets',series:[{name:'Profit',n:1,points:pts.length?[{x:0,y:0},...pts]:[]}],
      zero:true,height:220,yFmt:v=>(v<0?MINUS:'')+'$'+Math.abs(v),empty:'No settled bets yet. Your running profit appears here once games finish.',
      xTicks:pts.length?[{x:0,label:'start'},{x:pts.length,label:`bet ${pts.length}`}]:[],
      tip:x=>{const q=pts[Math.round(x)-1]; return q?`<div>${esc(betText(q.r.b,q.r.g))} · ${fmtDay(q.r.g.date)}</div><div>Total <b>${money(q.y)}</b></div>`:'<div>Start <b>$0.00</b></div>';}});
  };
  draw();
  $('#betsWhere').textContent='Connecting to your saved bets…';
  betStore().then(s=>{
    store=s;
    $('#betsWhere').textContent=s.kind==='db'?'Saved privately to your claude.ai page':'Saved in this browser only';
    s.subscribe(list=>{bets=list; draw();},()=>{$('#betsWhere').textContent='Live sync stopped. Reload the page.';});
  });
}

/* ======================= season page ======================= */
function seasonBets(){
  const fin=D.games.filter(g=>g.status==='final').slice().sort((a,b)=>a.date<b.date?-1:a.date>b.date?1:0);
  const bets=[];
  fin.forEach(g=>{
    if('underUnits' in g) bets.push({g,type:'wind',label:`Under ${g.total.line}`,price:g.total.uo,detail:`${g.wind.toFixed(1)} mph`,u:g.underUnits});
    if(g.mkt&&'leanUnits' in g.mkt){ const side=g.mkt.lean==='home'?g.homeName:g.awayName;
      bets.push({g,type:'lean',label:side,price:g.mkt.leanOdds,detail:`EV +${g.mkt.leanEv.toFixed(1)}%`,u:g.mkt.leanUnits}); }
  });
  return bets;
}
function seasonPage(){
  const s=D.summary, roi=o=>o.n?signed(o.units/o.n*100)+'%':'—', c=u=>u>0?'good':u<0?'bad':'';
  const rec=o=>`${o.won}–${o.lost}${o.n-o.won-o.lost?'–'+(o.n-o.won-o.lost):''}`;
  $('#seasonTitle').textContent=`${D.season} season so far`;
  $('#seasonSub').textContent=`${s.final} games final · every bet 1 unit at the posted price`;
  $('#kpis').innerHTML=`
    <div class="kpi"><div class="v ${c(s.wind.units)}">${s.wind.n?units(s.wind.units):'—'}</div><div class="l">Wind unders · ${rec(s.wind)} · ROI ${roi(s.wind)}</div></div>
    <div class="kpi"><div class="v ${c(s.lean.units)}">${s.lean.n?units(s.lean.units):'—'}</div><div class="l">Elo leans · ${rec(s.lean)} · ROI ${roi(s.lean)}</div></div>
    <div class="kpi"><div class="v">${s.eloAcc!=null?pct(s.eloAcc):'—'} <small>vs ${s.mktAcc!=null?pct(s.mktAcc):'—'}</small></div><div class="l">Winners picked · Elo vs market (${s.withLines} games)</div></div>
    <div class="kpi"><div class="v">${s.eloLL!=null?s.eloLL.toFixed(3):'—'} <small>vs ${s.mktLL!=null?s.mktLL.toFixed(3):'—'}</small></div><div class="l">Log loss · Elo vs market (lower wins)</div></div>`;

  const bets=seasonBets();
  const series=[{name:'Wind unders',n:1,type:'wind'},{name:'Elo leans',n:2,type:'lean'}].map(se=>{
    let cum=0; const pts=[];
    bets.filter(b=>b.type===se.type).forEach(b=>{ cum+=b.u; pts.push({x:day(b.g.date),y:Math.round(cum*100)/100}); });
    // one point per day (last bet of the day)
    const byDay=new Map(); pts.forEach(p=>byDay.set(p.x,p));
    const start=D.games.length?day(D.games[0].date)-1:0;
    return {name:se.name,n:se.n,points:[{x:start,y:0},...byDay.values()]};
  });
  const at=(se,x)=>{let v=0; se.points.forEach(p=>{if(p.x<=x) v=p.y;}); return v;};
  const xs=series.flatMap(se=>se.points.map(p=>p.x));
  lineChart($('#cumChart'),{label:'Cumulative units by date: wind unders and Elo leans',series,zero:true,endLabels:true,height:260,
    yFmt:v=>(v>0?'+':v<0?MINUS:'')+Math.abs(v)+'u',
    xTicks:xs.length?[{x:Math.min(...xs),label:fmtDay(D.games[0].date)},...monthTicks(Math.min(...xs),Math.max(...xs))]:[],
    empty:'No bets settled yet this season.',
    tip:x=>{const d=new Date(x*864e5); return `<div>${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}</div>`+
      series.map(se=>`<div><span style="color:var(--series-${se.n})">●</span> ${se.name} <b>${units(at(se,x))}</b></div>`).join('');}});

  $('#byWeek').innerHTML=`<thead><tr><th>Week</th><th class="n">Final</th><th class="n">Elo right</th><th class="n">Market right</th>
    <th class="n">Elo leans</th><th class="n">Wind unders</th></tr></thead><tbody>${s.byWeek.map(r=>`<tr>
    <td><a href="index.html#week${r.wk}">${wkShort(r.wk)}</a></td><td class="n">${r.games}</td>
    <td class="n">${r.eloRight}/${r.decided}</td><td class="n">${r.mktRight}/${r.decided}</td>
    <td class="n">${r.leanN?`<span class="${cls(r.leanUnits)}">${units(r.leanUnits)}</span> <span class="push">(${r.leanN})</span>`:'—'}</td>
    <td class="n">${r.windN?`<span class="${cls(r.windUnits)}">${units(r.windUnits)}</span> <span class="push">(${r.windN})</span>`:'—'}</td></tr>`).join('')
    ||'<tr><td colspan="6">No finished games yet.</td></tr>'}</tbody>`;

  let f='all';
  const log=()=>{
    const rows=bets.filter(b=>f==='all'||b.type===f).slice().reverse();
    $('#betLog').innerHTML=`<thead><tr><th>Date</th><th>Game</th><th>Bet</th><th class="n">Price</th><th>Why</th><th class="n">Result</th></tr></thead>
      <tbody>${rows.map(b=>`<tr><td>${fmtDay(b.g.date)} <span class="push">${wkShort(b.g.wk)}</span></td>
        <td>${esc(b.g.away)} ${b.g.as} @ ${esc(b.g.home)} ${b.g.hs}</td>
        <td><span class="tag ${b.type==='wind'?'under':'lean'}">${b.type==='wind'?'Wind':'Lean'}</span> ${esc(b.label)}</td>
        <td class="n">${odds(b.price)}</td><td class="push">${esc(b.detail)}</td>
        <td class="n ${cls(b.u)}">${units(b.u)}</td></tr>`).join('')||'<tr><td colspan="6">No bets yet.</td></tr>'}</tbody>`;
  };
  document.addEventListener('click',e=>{const b=e.target.closest('[data-f]'); if(!b) return; f=b.dataset.f;
    $$('#filters button').forEach(x=>x.setAttribute('aria-pressed',x===b)); log();});
  log();
}

/* ======================= teams page ======================= */
function teamsPage(){
  const T=D.teams; if(!T.length) return;
  const max=T[0].rating, min=T[T.length-1].rating;
  let sel=decodeURIComponent((location.hash||'').slice(1)); if(!NAME[sel]) sel=T[0].team;
  $('#powerSub').textContent=`Elo after every finished game · change from ${wkName(D.deltaWeek||D.currentWeek)}`;
  const table=()=>{
    $('#power').innerHTML=`<thead><tr><th class="n">#</th><th>Team</th><th>Record</th><th class="n">Elo</th><th class="n">Change</th><th aria-hidden="true"></th></tr></thead>
      <tbody>${T.map((r,i)=>`<tr class="${r.team===sel?'sel':''}"><td class="n">${i+1}</td>
        <td><button type="button" class="teamlink" data-team="${esc(r.team)}">${esc(r.name)}</button></td>
        <td class="num">${esc(r.record)}</td><td class="n">${r.rating.toFixed(0)}</td>
        <td class="n ${cls(r.delta)}">${signed(r.delta)}</td>
        <td style="width:28%"><span class="rbar" style="width:${8+92*(r.rating-min)/Math.max(1,max-min)}%"></span></td></tr>`).join('')}</tbody>`;
  };
  const detail=()=>{
    const t=T.find(x=>x.team===sel), rank=T.indexOf(t)+1;
    $('#teamName').textContent=t.name;
    $('#teamSub').textContent=`#${rank} of 32 · Elo ${t.rating.toFixed(0)} · ${t.record} this season`;
    const pts=t.hist.map((h,i)=>({x:i,y:h[1],h}));
    const xTicks=[]; t.hist.forEach((h,i)=>{ if(i===0||h[3]!==t.hist[i-1][3]) xTicks.push({x:i,label:String(h[3])}); });
    lineChart($('#teamChart'),{label:`${t.name} Elo rating, last two seasons`,series:[{name:t.name,n:1,points:pts}],refY:1500,height:220,
      yFmt:v=>String(Math.round(v)),xTicks,
      tip:x=>{const h=t.hist[Math.round(x)]; return `<div>${fmtDay(h[0])} ${h[3]}</div><div>${h[2]?'Before '+esc(h[2]):'Now'} <b>${Math.round(h[1])}</b></div>`;}});
    const gs=D.games.filter(g=>g.home===sel||g.away===sel);
    $('#teamGames').innerHTML=`<thead><tr><th>Week</th><th>Opponent</th><th class="n">Elo win%</th><th class="n">Market</th><th>Result</th></tr></thead>
      <tbody>${gs.map(g=>{const home=g.home===sel, opp=home?g.away:g.home, pe=home?g.pElo:1-g.pElo;
        const pm=g.mkt?(home?g.mkt.fair:1-g.mkt.fair):null;
        let r='<span class="push">'+esc(g.ko.split(' · ')[0])+'</span>';
        if(g.status==='final'){const us=home?g.hs:g.as, them=home?g.as:g.hs; r=`<span class="${us>them?'ok':us<them?'no':'push'}">${us>them?'W':us<them?'L':'T'} ${us}–${them}</span>`;}
        return `<tr><td><a href="index.html#week${g.wk}">${wkShort(g.wk)}</a></td><td>${home?'vs':'@'} ${esc(NAME[opp]||opp)}</td>
          <td class="n">${pct(pe)}</td><td class="n">${pm==null?'—':pct(pm)}</td><td>${r}</td></tr>`;}).join('')}</tbody>`;
  };
  document.addEventListener('click',e=>{const b=e.target.closest('[data-team]'); if(!b) return; sel=b.dataset.team;
    try{history.replaceState(null,'','#'+sel);}catch(_){} table(); detail();
    if(innerWidth<780) $('#teamName').scrollIntoView({behavior:'smooth',block:'start'});});
  table(); detail();
}

/* ======================= method page ======================= */
function methodPage(){
  $$('[data-season]').forEach(el=>el.textContent=D.season);
}

window.EDGE_TEST={betMath,fairNow,feePer,betText};   // for tests/tracker_test.html
chrome();
const page=($('main')||{}).dataset?.page;
({week:weekPage,season:seasonPage,teams:teamsPage,method:methodPage}[page]||(()=>{}))();
})();
