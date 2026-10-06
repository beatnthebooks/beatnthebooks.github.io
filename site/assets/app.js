/* Beatn’ the Books site. Every page loads data.js (window.EDGE, written by weekly.py) and this file.
   The page to render comes from <main data-page="...">.
   Writing rule for this file: every number on screen says what it means in plain words
   (dollars on $100 bets, "chance to win", "better/worse than fair"), never a bare code. */
(function(){
'use strict';
const D=window.EDGE;
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const MINUS='−';
const odds=o=>o==null||!isFinite(o)?'—':(o>0?'+':MINUS)+Math.abs(Math.round(o));
const pct=p=>Math.round(p*100)+'%';
const signed=(x,d=1)=>(x>0?'+':x<0?MINUS:'')+Math.abs(x).toFixed(d);
/* units (1 unit = one bet) -> dollars on $100 bets, e.g. 1.24 -> "+$124" */
const usd=v=>(v>0?'+':v<0?MINUS:'')+'$'+Math.round(Math.abs(v)).toLocaleString('en-US');
const per100=u=>usd(u*100);
const money=v=>(v>0?'+':v<0?MINUS:'')+'$'+Math.abs(v).toFixed(2);
const PLAYOFF={19:'Wild Card',20:'Divisional round',21:'Conference championships',22:'Super Bowl'};
const SHORT={19:'WC',20:'DIV',21:'CONF',22:'SB'};
const wkName=w=>PLAYOFF[w]||('Week '+w);
const wkShort=w=>SHORT[w]||('Wk '+w);
const NAME={}; (D.teams||[]).forEach(t=>NAME[t.team]=t.name);
const teamHref=t=>`teams.html#${encodeURIComponent(t)}`;
/* Team logos: ESPN's public dark-background set, on a round badge in the team's color. If a logo is
   blocked or fails, the image is dropped and the badge shows the team's letters. (No NFL shield: on a
   betting site it would look like an official NFL product.) */
const ESPN={LA:'lar',WAS:'wsh'};
const TCOLOR={ARI:'#97233F',ATL:'#A71930',BAL:'#5b3fb5',BUF:'#00338D',CAR:'#0085CA',CHI:'#C83803',CIN:'#FB4F14',CLE:'#FF3C00',
  DAL:'#869397',DEN:'#FB4F14',DET:'#0076B6',GB:'#2f5a45',HOU:'#A71930',IND:'#2a5fa8',JAX:'#006778',KC:'#E31837',LV:'#A5ACAF',
  LAC:'#0080C6',LA:'#003594',MIA:'#008E97',MIN:'#4F2683',NE:'#C60C30',NO:'#D3BC8D',NYG:'#0B2265',NYJ:'#125740',PHI:'#004C54',
  PIT:'#FFB612',SF:'#AA0000',SEA:'#69BE28',TB:'#D50A0A',TEN:'#4B92DB',WAS:'#773141'};
const logo=(code,size='')=>`<span class="tl ${size}" style="--tc:${TCOLOR[code]||'#4c3a8f'}" aria-hidden="true"><b>${esc(code)}</b>`+
  `<img src="https://a.espncdn.com/i/teamlogos/nfl/500-dark/${esc((ESPN[code]||code).toLowerCase())}.png" alt="" loading="lazy" decoding="async"></span>`;
/* the team's color on the element holding its name, so the name can show in it (style.css: "team colors") */
const tcv=code=>`--tc:${TCOLOR[code]||'#4c3a8f'}`;
const withLogo=(code,name,size='xs')=>`<span class="tteam" style="${tcv(code)}">${logo(code,size)}${esc(name)}</span>`;
const inBadge=t=>t&&t.tagName==='IMG'&&t.parentElement&&t.parentElement.classList.contains('tl');
document.addEventListener('load',e=>{if(inBadge(e.target)) e.target.parentElement.classList.add('ok');},true);    // letters until the logo arrives
document.addEventListener('error',e=>{if(inBadge(e.target)) e.target.remove();},true);
const day=s=>{const [y,m,d]=s.split('-').map(Number); return Date.UTC(y,m-1,d)/864e5;};
const MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const fmtDay=s=>{const [,m,d]=s.split('-').map(Number); return `${MONTHS[m-1]} ${d}`;};
const plural=(n,w,ws)=>`${n} ${n===1?w:(ws||w+'s')}`;
const cls=v=>v>0?'ok':v<0?'no':'push';
/* Elo rating -> chance to beat an average team on a neutral field */
const vsAvg=r=>1/(1+Math.pow(10,-(r-1500)/400));

/* Spread in words. nflverse convention: positive line = home team favored. */
function favorite(line,g){
  if(line==null) return null;
  if(line===0) return 'Even matchup';
  const a=Math.abs(line), n=Number.isInteger(a)?a:a.toFixed(1);
  return line>0?`${g.homeName} by ${n}`:`${g.awayName} by ${n}`;
}
/* "+2.8% better than fair" / "4.4% worse than fair" */
function vsFair(ev){
  if(ev==null) return '<span class="push">Different line, not comparable</span>';
  if(Math.abs(ev)<0.05) return '<span class="push">Same as fair</span>';
  return ev>0?`<span class="ok">${ev.toFixed(1)}% better than fair</span>`:`<span class="no">${Math.abs(ev).toFixed(1)}% worse than fair</span>`;
}

/* ======================= shared chrome ======================= */
/* Scoreboard strip above the header on every page: this week's games, live during games (ESPN). */
function scoreStrip(){
  const wk=D.currentWeek, gs=D.games.filter(g=>g.wk===wk), bar=$('header.bar');
  if(!gs.length||!bar) return;
  let sb=$('#scoreStrip');
  if(!sb){ sb=document.createElement('div'); sb.id='scoreStrip'; sb.className='sb'; sb.setAttribute('aria-label','Scores'); bar.before(sb); }
  const tile=g=>{
    const L=liveOf(g), f=g.status==='final'||(L&&L.state==='post'), on=L&&L.state==='in';
    const hs=L?L.hs:g.hs, as=L?L.as:g.as, show=f||!!L;
    const [day,time]=g.ko.split(' · ');
    const st=f?'Final':on?L.detail:g.status==='live'?'In progress':`${day.split(' ')[0]} ${time.replace(' CT','')}`;
    const row=(code,s,o)=>`<div class="sb-t ${f&&s<o?'lose':''}" style="${tcv(code)}">${logo(code,'xs')}<span class="sb-c">${esc(code)}</span>`
      +`${on&&L.poss===code?'<span class="poss">●</span>':''}${show?`<span class="sc">${s??''}</span>`:''}</div>`;
    return `<a class="sb-g ${on?'on':''}" href="index.html#week${g.wk}"><span class="sb-st ${f?'final':on?'live':''}">`
      +`${on?'<span class="livedot"></span>':''}${esc(st)}</span>${row(g.away,as,hs)}${row(g.home,hs,as)}</a>`;
  };
  sb.innerHTML=`<div class="sb-in"><a class="sb-wk" href="index.html#week${wk}">${esc(wkName(wk))}<span>${plural(gs.length,'game')}</span></a>${gs.map(tile).join('')}</div>`;
}
function chrome(){
  scoreStrip();
  watchLive(()=>D.currentWeek,()=>scoreStrip());
  $$('[data-stamp]').forEach(el=>el.textContent='Updated '+D.updatedLabel);
  const oddsTxt=D.oddsFetched?` Kalshi, Polymarket and sportsbook prices last checked ${new Date(D.oddsFetched).toLocaleString([], {weekday:'short',hour:'numeric',minute:'2-digit'})}.`:'';
  $$('[data-foot]').forEach(el=>el.textContent=`Updated ${D.updatedLabel}.${oddsTxt}`);
}

/* ======================= line chart ======================= */
/* series: [{name, n (1|2), points:[{x,y}]}]; xTicks:[{x,label}]; refY: dashed reference line */
function lineChart(box, opt){
  const draw=()=>{
    const W=Math.max(300, box.clientWidth), H=opt.height||250;
    const narrow=W<520;
    const m={t:14,r:(opt.endLabels&&!narrow)?150:16,b:30,l:opt.left||56};
    const all=opt.series.flatMap(s=>s.points);
    if(!all.length){ box.innerHTML=`<p class="why">${esc(opt.empty||'No data yet.')}</p>`; return; }
    const xs=all.map(p=>p.x), ys=all.map(p=>p.y).concat(opt.refY!=null?[opt.refY]:[]).concat(opt.zero?[0]:[]);
    let x0=Math.min(...xs), x1=Math.max(...xs); if(x0===x1){x0-=1;x1+=1;}
    let y0=Math.min(...ys), y1=Math.max(...ys); if(y0===y1){y0-=1;y1+=1;}
    const ticks=niceTicks(y0,y1,5); y0=Math.min(y0,ticks[0]); y1=Math.max(y1,ticks[ticks.length-1]);
    const X=x=>m.l+(x-x0)/(x1-x0)*(W-m.l-m.r), Y=y=>m.t+(1-(y-y0)/(y1-y0))*(H-m.t-m.b);
    let s=`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opt.label)}">`;
    ticks.forEach(t=>{ s+=`<line class="gridline" x1="${m.l}" x2="${W-m.r}" y1="${Y(t)}" y2="${Y(t)}"/>
      <text class="tick" x="${m.l-10}" y="${Y(t)+4}" text-anchor="end">${opt.yFmt?opt.yFmt(t):t}</text>`; });
    if(opt.zero&&y0<0&&y1>0) s+=`<line class="zero" x1="${m.l}" x2="${W-m.r}" y1="${Y(0)}" y2="${Y(0)}"/>`;
    if(opt.refY!=null){ s+=`<line class="ref" x1="${m.l}" x2="${W-m.r}" y1="${Y(opt.refY)}" y2="${Y(opt.refY)}"/>`;
      if(opt.refLabel) s+=`<text class="tick" x="${W-m.r}" y="${Y(opt.refY)-6}" text-anchor="end">${esc(opt.refLabel)}</text>`; }
    let last=-1e9;
    (opt.xTicks||[]).forEach(t=>{ const px=X(t.x); if(px<m.l-1||px>W-m.r+1||px-last<52) return; last=px;
      s+=`<text class="tick" x="${px}" y="${H-8}" text-anchor="middle">${esc(t.label)}</text>`; });
    opt.series.forEach(se=>{
      if(!se.points.length) return;
      const d=se.points.map((p,i)=>(i?'L':'M')+X(p.x).toFixed(1)+','+Y(p.y).toFixed(1)).join('');
      s+=`<path class="line s${se.n}" d="${d}"/>`;
      const e=se.points[se.points.length-1];
      s+=`<circle class="d${se.n}" cx="${X(e.x)}" cy="${Y(e.y)}" r="4.5"/>`;
      if(opt.endLabels&&!narrow) s+=`<text class="dlabel" x="${X(e.x)+10}" y="${Y(e.y)+4}">${esc(se.name)} ${esc(opt.yFmt?opt.yFmt(e.y):e.y)}</text>`;
    });
    s+=`<line class="cross" x1="0" x2="0" y1="${m.t}" y2="${H-m.b}" visibility="hidden"/>`;
    s+=`<rect x="${m.l}" y="0" width="${W-m.l-m.r}" height="${H}" fill="transparent"/></svg><div class="tip" hidden></div>`;
    box.innerHTML=s;
    const svg=box.querySelector('svg'), cross=svg.querySelector('.cross'), tip=box.querySelector('.tip');
    const move=ev=>{
      const r=svg.getBoundingClientRect(); const px=(ev.clientX-r.left);
      const xv=x0+(px-m.l)/(W-m.l-m.r)*(x1-x0);
      let best=null; all.forEach(p=>{ if(!best||Math.abs(p.x-xv)<Math.abs(best.x-xv)) best=p; });
      if(!best) return;
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

/* ---------- picks: built in Python (picks.py) so the same list feeds the cards, the log and the scoreboard ----------
   Each game's g.picks: best first by realistic edge (edge = expected profit per $1 at that price). Finished games
   show the suggestions logged before kickoff, graded at the price first shown (p.grade: units, beat the close). */
const EVID={wind:['under','Wind · tested'],roof:['roof','Wind · roof must be open'],gap:['gap','Price gap · unproven'],
  lean:['lean','Model pick · no proven edge'],spread:['lean','Model pick · no proven edge']};
const fmtLogged=s=>{const d=new Date(s+':00'); return isNaN(d)?s:`${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][d.getDay()]} ${MONTHS[d.getMonth()]} ${d.getDate()}, ${((d.getHours()+11)%12)+1}:${String(d.getMinutes()).padStart(2,'0')} ${d.getHours()<12?'AM':'PM'} CT`;};
const modelOnly=p=>p.edgeFrom==='lean'||p.edgeFrom==='spread';
const pickEdge=p=>modelOnly(p)&&p.model!=null
  ?`<span class="pedge model">${signed(p.model)}%<small> model edge</small></span>`
  :`<span class="pedge ${p.edge>0?'ok':'no'}">${signed(p.edge)}%<small> edge</small></span>`;
const logBtn=(g,p)=>`<button type="button" class="btn small logbet" data-gid="${esc(g.id)}" data-key="${esc(p.key)}">Log this bet</button>`;
/* Live scores: the page reads ESPN's public scoreboard while games are on (every 30 s; every 5 min on a game
   day otherwise). Nothing is saved; results still come from the site's own updates. If ESPN can't be reached
   (or a host blocks it), cards just show what the last site update knew. */
const LIVE=new Map(), ESPN_CODE={WSH:'WAS',LAR:'LA',JAC:'JAX'};
const liveOf=g=>{const v=LIVE.get(g.id); return v&&v.state!=='pre'?v:null;};
async function fetchLive(games,wk){
  if(!games.length) return [];
  // ESPN wants season + week (a range of dates returns nothing); playoffs are its season type 3, Super Bowl = week 5
  const post=wk>=19, ew=post?({19:1,20:2,21:3,22:5}[wk]||wk-18):wk;
  const d=await (await fetch(`https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=${post?3:2}&week=${ew}&dates=${D.season}`)).json();
  const changed=[];
  for(const e of d.events||[]){
    const c=(e.competitions||[])[0]; if(!c) continue;
    const t={}, byId={};
    c.competitors.forEach(x=>{const code=ESPN_CODE[x.team.abbreviation]||x.team.abbreviation; t[x.homeAway]={code,score:Number(x.score)}; byId[x.team.id]=code;});
    const g=games.find(g=>t.home&&t.away&&g.home===t.home.code&&g.away===t.away.code); if(!g) continue;
    const s=c.status.type, sit=c.situation||{};
    const v={state:s.state, detail:s.shortDetail||s.detail||'', hs:t.home.score, as:t.away.score,
      poss:byId[sit.possession]||'', down:s.state==='in'?(sit.downDistanceText||''):'', red:!!sit.isRedZone};
    if(JSON.stringify(LIVE.get(g.id))!==JSON.stringify(v)){ LIVE.set(g.id,v); changed.push(g); }
  }
  return changed;
}
/* One live loop for the page: each subscriber names a week to watch (or null) and redraws what changed.
   Polls only weeks with a non-final game dated today or earlier; 30 s while a game is on, else every 5 min;
   a hidden tab gets one check, then waits until it's visible again. */
const liveSubs=[];
let liveTimer=null, liveFirst=true;
const watchLive=(weekFn,onChange)=>liveSubs.push({weekFn,onChange});
async function liveTick(){
  clearTimeout(liveTimer);
  const today=new Date().toISOString().slice(0,10);
  let fast=false;
  for(const wk of [...new Set(liveSubs.map(s=>s.weekFn()).filter(w=>w!=null))]){
    const gs=D.games.filter(g=>g.wk===wk);
    const due=gs.some(g=>g.status!=='final'&&g.date<=today&&!(LIVE.get(g.id)&&LIVE.get(g.id).state==='post'));
    if(!due||(document.hidden&&!liveFirst)) continue;
    try{
      const changed=await fetchLive(gs,wk);
      if(changed.length) liveSubs.filter(s=>s.weekFn()===wk).forEach(s=>s.onChange(changed,gs));
      if(gs.some(g=>(LIVE.get(g.id)||{}).state==='in')) fast=true;
    }catch(_){}
  }
  liveFirst=false;
  liveTimer=setTimeout(liveTick,fast?30000:300000);
}
document.addEventListener('visibilitychange',()=>{ if(!document.hidden) liveTick(); });
/* Unit sizing: 1 unit = D.unitPct (2%) of the Kalshi bankroll the viewer types into My bets (kept in this browser
   only). Each pick's size in units comes from picks.units_for (evidence-based); this only turns it into dollars. */
const BANK_KEY='btb.kalshiBankroll', UPCT=()=>D.unitPct||2;
const bankroll=()=>{try{const v=Number(localStorage.getItem(BANK_KEY)); return v>0?v:null;}catch(_){return null;}};
const unitUsd=()=>{const b=bankroll(); return b?b*UPCT()/100:null;};
const fmtU=x=>`${+Number(x).toFixed(2)}u`;
const usdAmt=x=>'$'+(x<10?x.toFixed(2):Math.round(x).toLocaleString('en-US'));
const unitChip=p=>{ if(!p.units) return ''; const u=unitUsd();
  return `<span class="ustake" title="${fmtU(p.units)} = ${+(p.units*UPCT()).toFixed(2)}% of your Kalshi bankroll">${fmtU(p.units)}${u?` · ${usdAmt(p.units*u)}`:''}</span>`; };
const pctOf=u=>`${+(u*UPCT()).toFixed(2)}%`;
function unitKey(){
  const u=unitUsd(), row=(size,label,tag)=>`<span class="ukey-i"><b>${size}</b><span class="push">${pctOf(parseFloat(size))}</span>${tag?`<span class="tag ${tag}">${label}</span>`:esc(label)}</span>`;
  return `<div class="ukey" role="note"><span class="ukey-h">Unit key</span>
    <span class="ukey-i ukey-main"><b>1u</b> = <b>${UPCT()}%</b> of your Kalshi bankroll${u?` = <b>${usdAmt(u)}</b>`:''}</span>
    ${row('1.5u','Wind under, great price (edge 6%+)','under')}${row('1u','Wind under','under')}
    ${row('0.75u','Price gap the model agrees with','gap')}${row('0.5u','Price gap','gap')}${row('0.5u','Wind under, roof must be open','roof')}
    ${row('0.25u','Model pick (no proven edge)','lean')}
    ${u?'':'<span class="ukey-i push">Enter your Kalshi bankroll in <a href="index.html#bets">My bets</a> to see dollar amounts.</span>'}</div>`;
}
const priceTxt=pr=>!pr?'':pr.cents!=null?`${Number(pr.cents).toFixed(0)}¢ on ${esc(pr.book)}`:`${odds(pr.odds)} at sportsbooks`;
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
  function chanceRow(label,pA,pH,cA,cH,g){
    return `<div class="crow"><span class="clab">${label}</span>
      <span class="track" role="img" aria-label="${label}: ${esc(g.awayName)} ${pct(pA)}, ${esc(g.homeName)} ${pct(pH)}">
        <span style="width:${pA*100}%;background:${cA}"></span><span style="width:${pH*100}%;background:${cH}"></span></span>
      <span class="cval"><b>${esc(g.away)} ${pct(pA)}</b> · <b>${esc(g.home)} ${pct(pH)}</b></span></div>`;
  }
  function windLine(g){
    if(g.roof==='dome'||g.roof==='closed') return `<div class="sig muted"><span class="dot"></span><span><b>Wind:</b> indoors, so wind doesn’t matter.</span></div>`;
    if(g.wind==null) return `<div class="sig muted"><span class="dot"></span><span><b>Wind:</b> forecast not out yet (it appears about two weeks before kickoff).</span></div>`;
    const mph=`${g.wind.toFixed(0)} mph`;
    const when=g.status==='upcoming'?'forecast':'forecast at kickoff';
    if(g.signal==='under'){
      const bu=g.shop&&g.shop.total&&g.shop.total.under;
      const best=bu?` Best under you can buy: ${bu.point} at ${bu.cents.toFixed(0)}¢ on ${esc(bu.book)}${bu.ev==null?' (a different line from the sportsbooks)':`, ${bu.ev>=0?bu.ev.toFixed(1)+'% better':Math.abs(bu.ev).toFixed(1)+'% worse'} than the sportsbooks’ fair price before counting the wind`}.`
        :g.total&&g.total.line!=null?` The under is ${g.total.line} points.`:'';
      const stake=g.status==='upcoming'?' Suggested stake: 1% of bankroll.':'';
      return `<div class="sig good"><span class="tag under">Under signal</span><span><b>${mph}</b> wind ${when}. Games this windy have tended to go under.${best}${stake}</span></div>`;
    }
    if(g.signal==='roof') return `<div class="sig warn"><span class="tag roof">Windy</span><span><b>${mph}</b> wind ${when}, but the roof may be closed. Only bet the under if it’s open.</span></div>`;
    return `<div class="sig muted"><span class="dot"></span><span><b>Wind:</b> ${mph} ${when}. Not windy enough for a signal (needs 10+ mph).</span></div>`;
  }
  function leanLine(g){
    if(!g.mkt) return `<div class="sig muted"><span class="dot"></span><span><b>Model lean:</b> waiting for betting lines.</span></div>`;
    if(!g.mkt.lean) return `<div class="sig muted"><span class="dot"></span><span><b>Model lean:</b> none. Our model and the market roughly agree.</span></div>`;
    const t=g.mkt.lean==='home'?g.homeName:g.awayName;
    const price=g.mkt.leanCents!=null?`${g.mkt.leanCents.toFixed(0)}¢ on ${esc(g.mkt.leanBook)}`:odds(g.mkt.leanOdds);
    return `<div class="sig lean"><span class="tag lean">Model lean</span><span><b>${esc(t)}</b> at ${price}, expected return ${signed(g.mkt.leanEv)}%.
      No proven edge: in testing, lines moved toward these leans only slightly more often than not, which wasn’t enough to beat the price, early or late, on sportsbooks or on Kalshi and Polymarket.</span></div>`;
  }
  function shopBlock(g){
    const s=g.shop; if(!s) return '';
    const team=side=>side==='home'?g.homeName:g.awayName;
    const rows=[['ml','away',`${team('away')} to win`],['ml','home',`${team('home')} to win`],
      ['spread','away',null],['spread','home',null],['total','over',null],['total','under',null]]
      .map(([mk,side,label])=>{
        const x=s[mk]&&s[mk][side]; if(!x) return '';
        const lab=label||(mk==='spread'?`${team(side)} ${x.point>0?'+':''}${x.point}`:`${side==='over'?'Over':'Under'} ${x.point}`);
        return `<tr><td>${esc(lab)}</td><td class="n">${x.cents.toFixed(0)}¢</td><td>${esc(x.book)}</td><td>${vsFair(x.ev)}</td></tr>`;
      }).join('');
    if(!rows) return '';
    return `<div class="block"><div class="bh">Kalshi &amp; Polymarket prices <span class="why">(fees included) compared with the fair price from ${s.books?plural(s.books,'sportsbook'):'the betting line'}${D.gapBooks&&s.books<D.gapBooks?`, too few to flag price gaps (needs ${D.gapBooks})`:''}</span></div>
      <div class="tablebox flat"><table class="mini"><thead><tr><th>Bet</th><th class="n">Price</th><th>Where</th><th>Value</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }
  function gapTxt(g,x){
    const who=x.mk==='total'?(x.side==='over'?'Over':'Under')+' '+x.point
      :(x.side==='home'?g.homeName:g.awayName)+(x.mk==='spread'?' '+(x.point>0?'+':'')+x.point:' to win');
    return `${esc(who)} at ${x.cents.toFixed(0)}¢ on ${esc(x.book)}`;
  }
  function injuryBlock(g){
    const I=g.injuries; if(!I||g.status==='final'||(liveOf(g)||{}).state==='post') return '';
    const side=(code,name,list)=>`<div class="iteam"><div class="ihead">${logo(code,'xs')}<b>${esc(name)}</b></div>${list.length
      ?list.map(p=>`<div class="iplayer"><span class="ist ${p.status.toLowerCase()}">${esc(p.status)}</span>
          <span><b>${esc(p.name)}</b> <span class="push">${esc(p.pos)}${p.qb?' · starting QB':` · ${Math.round(p.share*100)}% of snaps`}</span></span></div>`).join('')
      :'<div class="push small">No key players listed</div>'}</div>`;
    return `<div class="block"><div class="bh">Key injuries <span class="why">starting QBs and players on the field 60%+ of snaps · ESPN</span></div>
      <div class="injuries">${side(g.away,g.awayName,I.away||[])}${side(g.home,g.homeName,I.home||[])}</div></div>`;
  }
  function picksBlock(g){
    const P=g.picks||[], f=g.status==='final', started=g.status!=='upcoming'||!!liveOf(g);
    const good=P.filter(p=>p.good), weak=P.filter(p=>!p.good);
    const head=`<div class="bh">${f?'Picks before kickoff':started?'Picks (locked at kickoff)':'Bets to take'}
      <span class="why">best first, by each kind of bet’s real record · edge = expected profit per $1 at that price</span></div>`;
    const res=u=>u==null?'':`<span class="pill ${cls(u)}">${u>0?'Won':u<0?'Lost':'Push'} ${per100(u)}</span>`;
    const clv=gr=>!gr||gr.beat==null?'':gr.clv!=null
      ?`<span class="pill ${gr.beat?'ok':'no'}">${gr.beat?'Beat':'Worse than'} the closing price ${signed(gr.clv)}%</span>`
      :`<span class="pill ${gr.beat?'ok':'no'}">${Math.abs(gr.clvPts)} pt ${gr.beat?'better':'worse'} than the closing line</span>`;
    const recTxt=p=>{const r=(D.modelRecord||{})[p.rec]; return r&&r.n?`<div class="prec">Model picks this strong have returned
      <b class="${cls(r.roi)}">${signed(r.roi)}%</b> over ${r.n.toLocaleString('en-US')} bets (${esc(r.seasons.replace('-','–'))}). Small stake or skip.</div>`:'';};
    const row=(p,i)=>`<div class="pick ${i===0?'top':''}"><span class="rank">${i+1}</span><div class="pmain">
      <div class="pline"><b>${esc(p.text)}</b><span class="pprice">${priceTxt(p.price)}</span>${unitChip(p)}${pickEdge(p)}</div>
      <div class="pwhy">${(p.src||[]).map(s=>`<span class="tag ${EVID[s][0]}">${EVID[s][1]}</span>`).join('')}
        <span>${esc((p.why||[]).join(' · '))}</span>${p.grade?res(p.grade.units)+clv(p.grade):''}</div>${modelOnly(p)?recTxt(p):''}${started?'':`<div class="pact">${logBtn(g,p)}</div>`}</div></div>`;
    const conflict=new Set(good.map(p=>p.key.split('|')[0])).size<good.length?
      '<div class="why">Two picks bet against each other on the same market: take the higher one, or pass.</div>':'';
    const none=!good.length?`<div class="nobet"><b>No bet${started?' was suggested':''}.</b> ${!g.mkt&&!g.windPick?'Waiting for betting lines.':started?'Nothing on this game showed a real edge before kickoff.':'Nothing on this game shows a real edge at the available prices, so pass.'}</div>`:'';
    const skip=weak.length&&!started?`<div class="skips"><span class="why">Not worth it at this price:</span> ${weak.map(p=>
      `<span class="skip">${esc(p.text)} <span class="no">${signed(p.edge)}%</span> <span class="tag ${EVID[p.src[0]][0]}">${EVID[p.src[0]][1]}</span></span>`).join('')}</div>`:'';
    const note=good.some(p=>p.reconstructed)?'<div class="why">Reconstructed at closing prices: this game was played before the site started saving its suggestions.</div>'
      :good.some(p=>p.logged)?`<div class="why">As first shown ${esc(fmtLogged(good.map(p=>p.logged).sort()[0]))}, graded at that price.</div>`:'';
    return `<div class="block picks">${head}${good.map(row).join('')}${conflict}${none}${skip}${started?note:''}</div>`;
  }
  function results(g){
    if(g.status!=='final') return '';
    const winner=g.hs>g.as?g.homeName:g.as>g.hs?g.awayName:null;
    const out=[];
    if('eloRight' in g){ const pick=g.pElo>=0.5?g.homeName:g.awayName;
      out.push(`<span class="pill ${g.eloRight?'ok':'no'}">${g.eloRight?'✓':'✗'} Model picked ${esc(pick)}</span>`); }
    if(g.mkt&&'mktRight' in g.mkt){ const fav=g.mkt.fair>=0.5?g.homeName:g.awayName;
      out.push(`<span class="pill ${g.mkt.mktRight?'ok':'no'}">${g.mkt.mktRight?'✓':'✗'} Market favored ${esc(fav)}</span>`); }
    const head=winner?`${esc(winner)} won by ${Math.abs(g.hs-g.as)}`:'Tie game';
    return `<div class="results"><div class="rhead">${head}${g.windRecorded!=null?` <span class="why">· actual wind ${g.windRecorded} mph</span>`:''}</div>
      ${out.length?`<div class="pills">${out.join('')}</div><div class="why">Bet results are per $100 bet.</div>`:''}</div>`;
  }
  function card(g){
    const L=!(g.status==='final')&&liveOf(g), f=g.status==='final'||(L&&L.state==='post');
    const hs=L?L.hs:g.hs, as=L?L.as:g.as, aw=f&&as>hs, hw=f&&hs>as, showScore=f||!!L;
    const status=f?'<span class="chip final">Final</span>'
      :L?`<span class="chip live"><span class="livedot"></span>Live · ${esc(L.detail)}</span>`
      :g.status==='live'?'<span class="chip live">In progress</span>':'';
    const intl=g.neutral||/Tottenham|Wembley|Allianz|Deutsche|Bernabeu|Azteca|Banorte|Maracan|Corinthians/.test(g.stadium||'');
    const mk=g.mkt, sp=g.spread, tt=g.total;
    const fav=sp?favorite(sp.line,g):null, modelFav=favorite(g.eloLine,g);
    const notes=(g.notes||[]).map(n=>`<div class="note">${esc(n)}</div>`).join('');
    const team=(code,name,score,win)=>`<div class="trow ${f?(win?'win':'lose'):''}" style="${tcv(code)}"><span class="tname">${logo(code)}<a href="${teamHref(code)}">${esc(name)}</a>${L&&L.state==='in'&&L.poss===code?'<span class="poss" title="Has the ball">●</span>':''}</span>${showScore?`<span class="score">${score}</span>`:''}</div>`;
    return `<article class="game ${g.signal==='under'?'sig-card':''}" id="g-${esc(g.id)}">
      <header class="ghead">
        <div class="gmeta"><span>${esc(g.ko)}</span>${status}${intl?`<span class="chip venue">${esc(g.stadium)}</span>`:''}</div>
        <div class="teams">${team(g.away,g.awayName,as,aw)}${team(g.home,g.homeName,hs,hw)}</div>
        <div class="why">${esc(g.awayName)} at ${esc(g.homeName)}${L&&L.down?` · <span class="sit ${L.red?'red':''}">${esc(L.down)}${L.red?' · red zone':''}</span>`:''}</div>
      </header>
      <div class="gbody">
        ${picksBlock(g)}
        <div class="block"><div class="bh">Chance to win</div>
          ${chanceRow('Our model',1-g.pElo,g.pElo,'var(--away)','var(--home)',g)}
          ${mk?chanceRow('Betting market',1-mk.fair,mk.fair,'var(--mkt-away)','var(--mkt-home)',g):'<div class="crow"><span class="clab">Betting market</span><span class="why">No betting line yet</span></div>'}
        </div>
        <dl class="facts">
          <div><dt>Favorite (point spread)</dt><dd>${fav||'Not posted yet'}</dd><dd class="sub">Our model: ${modelFav}</dd></div>
          <div><dt>Total points line</dt><dd>${tt&&tt.line!=null?tt.line+' points':'Not posted yet'}</dd><dd class="sub">${tt&&tt.oo?`Over ${odds(tt.oo)} · Under ${odds(tt.uo)}`:'&nbsp;'}</dd></div>
          <div><dt>Moneyline odds</dt>${mk&&mk.aml!=null
            ?`<dd>${esc(g.awayName)} ${odds(mk.aml)}</dd><dd class="sub">${esc(g.homeName)} ${odds(mk.hml)}</dd>`
            :`<dd>${mk?esc(g.homeName)+' '+pct(mk.fair)+' to win':'Not posted yet'}</dd><dd class="sub">${mk?'fair chance from sportsbooks':'&nbsp;'}</dd>`}</div>
        </dl>
        ${injuryBlock(g)}
        ${shopBlock(g)}
        <div class="block signals"><div class="bh">Signals</div>${windLine(g)}${leanLine(g)}</div>
        ${notes?`<div class="block">${notes}</div>`:''}
      </div>
      ${f?`<footer class="gfoot">${results(g)}</footer>`:''}
    </article>`;
  }
  /* Best bets: every pick worth taking this week, across all games, best edge first (same order as the cards) */
  function bestBets(gs){
    const open=games=>games.filter(g=>g.status==='upcoming'&&!liveOf(g))
      .flatMap(g=>(g.picks||[]).filter(p=>p.good).map(p=>({g,p}))).sort((a,b)=>b.p.edge-a.p.edge);
    let list=open(gs), ahead=false;
    if(!list.length&&week===D.currentWeek){                  // e.g. only Monday night left: show next week's
      list=open(D.games.filter(g=>g.wk===week+1)); ahead=list.length>0;
    }
    const wrap=$('#playsWrap');
    if(!list.length){                                        // nothing left to bet: the week's graded record
      const done=gs.flatMap(g=>(g.picks||[]).filter(p=>p.grade&&p.good));
      wrap.hidden=!done.length; if(!done.length) return;
      const u=done.reduce((s,p)=>s+p.grade.units,0), w=done.filter(p=>p.grade.won).length, l=done.filter(p=>p.grade.won===false).length;
      $('#playsTitle').textContent=`${wkName(week)} picks`;
      $('#plays').className='plays';
      $('#plays').innerHTML=`<div class="bestsum">${plural(done.length,'pick')} graded · ${w}–${l} · <b class="${cls(u)}">${per100(u)}</b> on $100 bets <a href="season.html">Full scoreboard</a></div>`;
      return;
    }
    $('#playsTitle').textContent=ahead?`Best bets · next up, ${wkName(week+1)}`:week===D.currentWeek?'Best bets this week':`Best bets · ${wkName(week)}`;
    wrap.hidden=false;
    const SHOW=8;
    $('#plays').className='plays';
    $('#plays').innerHTML=unitKey()+list.map(({g,p},i)=>`<div class="best ${i>=SHOW?'more':''}"><span class="rank">${i+1}</span>
      <div class="bmain"><div class="bline"><span class="duo">${logo(g.away,'sm')}${logo(g.home,'sm')}</span><b>${esc(p.text)}</b>
        <span class="pprice">${priceTxt(p.price)}</span>${unitChip(p)}</div>
        <div class="bwhy"><span>${esc(g.awayName)} at ${esc(g.homeName)} · ${esc(g.ko)}</span>
          ${(p.src||[]).map(s=>`<span class="tag ${EVID[s][0]}">${EVID[s][1]}</span>`).join('')}</div></div>
      <div class="bedge">${pickEdge(p)}</div>
      <div class="bact">${logBtn(g,p)}<a href="#g-${esc(g.id)}">See game</a></div></div>`).join('')
      +(list.length>SHOW?`<button type="button" class="btn ghost small showall" data-showall>Show all ${list.length}</button>`:'');
  }
  function render(){
    rail();
    const gs=D.games.filter(g=>g.wk===week);
    const fin=gs.filter(g=>g.status==='final').length;
    const sig=gs.filter(g=>g.signal==='under'), leans=gs.filter(g=>g.mkt&&g.mkt.lean).length;
    const gaps=gs.filter(g=>g.status==='upcoming'&&g.gaps&&g.gaps.length);
    $('#weekEyebrow').textContent=`NFL · ${D.season} season${week===D.currentWeek?' · this week':''}`;
    $('#weekTitle').textContent=wkName(week);
    $('#weekSub').textContent=gs.length?`${gs[0].ko.split(' · ')[0]} to ${gs[gs.length-1].ko.split(' · ')[0]}`:'';
    $('#kpis').innerHTML=`
      <div class="kpi"><div class="v">${gs.length}</div><div class="l">Games<br><span>${fin} finished, ${gs.length-fin} to play</span></div></div>
      <div class="kpi"><div class="v ${sig.length?'good':''}">${sig.length}</div><div class="l">Under signals<br><span>windy outdoor games</span></div></div>
      <div class="kpi"><div class="v ${gaps.length?'good':''}">${D.oddsFetched?gaps.length:'n/a'}</div><div class="l">Price gaps<br><span>${D.oddsFetched?`Kalshi/Polymarket ${D.gapEv}%+ better than fair`:'needs sportsbook prices (private version)'}</span></div></div>
      <div class="kpi"><div class="v">${leans}</div><div class="l">Model leans<br><span>no proven edge</span></div></div>`;
    bestBets(gs);
    const shown=gs.filter(g=>filter==='all'||(filter==='wind'&&g.signal)||(filter==='gap'&&g.gaps&&g.gaps.length)||(filter==='lean'&&g.mkt&&g.mkt.lean)||(filter==='final'&&g.status==='final'));
    shown.sort((a,b)=>(a.signal==='under'||(a.gaps&&a.gaps.length)?0:1)-(b.signal==='under'||(b.gaps&&b.gaps.length)?0:1));
    $('#games').innerHTML=shown.map(card).join('')||`<div class="empty">No games match this filter in ${esc(wkName(week))}.</div>`;
  }
  document.addEventListener('click',e=>{
    const lb=e.target.closest('[data-key][data-gid]');
    if(lb){ pendingLog={gid:lb.dataset.gid,key:lb.dataset.key};
      if(location.hash==='#bets') route(); else location.hash='#bets';
      return; }
    const sa=e.target.closest('[data-showall]');
    if(sa){ $('#plays').classList.add('all'); sa.remove(); return; }
    const b=e.target.closest('[data-wk]');
    if(b){ week=Number(b.dataset.wk); filter='all';
      $$('#filters button').forEach(x=>x.setAttribute('aria-pressed',x.dataset.f==='all'));
      try{history.replaceState(null,'','#week'+week);}catch(_){}
      render(); setTimeout(liveTick,50); return; }
    const f=e.target.closest('[data-f]');
    if(f){ filter=f.dataset.f; $$('#filters button').forEach(x=>x.setAttribute('aria-pressed',x===f)); render(); }
  });
  // Two views on this page: the week board and "My bets" (#bets). The tracker lives here
  // because the home page is where the claude.ai viewer grants the database.
  function route(){
    const bets=location.hash==='#bets';
    const wm=location.hash.match(/^#week(\d+)$/);
    if(wm&&weeks.includes(Number(wm[1]))) week=Number(wm[1]);
    $('#betsView').hidden=!bets; $('#weekView').hidden=bets; $('#rail').hidden=bets;
    $('#navWeek').toggleAttribute('aria-current',!bets); $('#navBets').toggleAttribute('aria-current',bets);
    if(bets){ $('#navBets').setAttribute('aria-current','page'); betsView();
      if(pendingLog&&fillBet){ const pl=pendingLog; pendingLog=null; fillBet(pl); } }
    else { $('#navWeek').setAttribute('aria-current','page'); render(); }
  }
  window.addEventListener('hashchange',route);
  route();
  // live scores for the week on screen (shared loop above)
  watchLive(()=>location.hash==='#bets'?null:week,(changed,gs)=>{
    changed.forEach(g=>{const el=document.getElementById('g-'+g.id); if(el) el.outerHTML=card(g);});
    bestBets(gs);
  });
  window.addEventListener('hashchange',()=>setTimeout(liveTick,50));
}

/* ======================= bet tracker ======================= */
const VENUE={kalshi:'Kalshi',polymarket:'Polymarket',other:'Other'};
const REASON={wind:'Wind under',gap:'Price gap',lean:'Model lean',other:'Other'};
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

function vsCloseTxt(r){
  if(r.clvPts!=null) return `<span class="${r.clvPts>0?'ok':'no'}">${Math.abs(r.clvPts)} pt${Math.abs(r.clvPts)===1?'':'s'} ${r.clvPts>0?'better':'worse'}</span>`;
  if(r.clvEv!=null) return Math.abs(r.clvEv)<0.05?'<span class="push">Same price</span>'
    :`<span class="${r.clvEv>0?'ok':'no'}">${Math.abs(r.clvEv).toFixed(1)}% ${r.clvEv>0?'better':'worse'}</span>`;
  return '<span class="push">After kickoff</span>';
}

let betsReady=false, store=null, bets=[];
let pendingLog=null, fillBet=null;      // "Log this bet": the pick to copy into the form
function betsView(){
  if(betsReady) return; betsReady=true;
  // ---- form ----
  const up=D.games.filter(g=>g.status!=='final'&&g.wk<=D.currentWeek+1);
  const fin=D.games.filter(g=>g.status==='final');
  const opt=g=>`<option value="${esc(g.id)}">${wkShort(g.wk)} · ${esc(g.awayName)} at ${esc(g.homeName)} · ${esc(g.ko.split(' · ')[0])}</option>`;
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
    const ev=pf==null?'':` It’s ${(()=>{const v=(pf/(p+fee/n)-1)*100; return Math.abs(v)<0.05?'right at':Math.abs(v).toFixed(1)+'% '+(v>0?'better than':'worse than');})()} the sportsbooks’ fair price right now.`;
    $('#bPreview').textContent=`Costs about ${money(n*p+fee).replace('+','')} including about ${money(fee).replace('+','')} in fees, and pays $${n.toFixed(0)} if it wins.${ev}`;
  };
  $('#bGame').addEventListener('change',sides);
  $('#bMarket').addEventListener('change',sides);
  $('#bSide').addEventListener('change',prefill);
  ['bCents','bQty','bPoint','bVenue'].forEach(id=>$('#'+id).addEventListener('input',preview));
  sides();
  const bankTxt=()=>{const u=unitUsd(); $('#bUnit').innerHTML=unitKey()
    +(u?'':'<p class="why">Your bankroll is saved in this browser only and never sent anywhere.</p>');};
  const b0=bankroll(); if(b0) $('#bBank').value=b0;
  $('#bBank').addEventListener('input',()=>{const v=Number($('#bBank').value);
    try{ if(v>0) localStorage.setItem(BANK_KEY,String(v)); else localStorage.removeItem(BANK_KEY); }catch(_){}
    bankTxt();});
  bankTxt();
  fillBet=({gid,key})=>{
    const g=GAME.get(gid), p=g&&(g.picks||[]).find(x=>x.key===key); if(!p) return;
    if(![...$('#bGame').options].some(o=>o.value===gid)) $('#bGame').insertAdjacentHTML('afterbegin',opt(g));
    $('#bGame').value=gid; $('#bMarket').value=p.mk; sides();
    $('#bSide').value=p.side; prefill();
    if(p.point!=null) $('#bPoint').value=p.point;
    const pr=p.price||{}, book=String(pr.book||'');
    $('#bVenue').value=/kalshi/i.test(book)?'kalshi':/polymarket/i.test(book)?'polymarket':'other';
    const c=pr.cents!=null?pr.cents:pr.odds!=null?(pr.odds<0?-pr.odds/(100-pr.odds):100/(pr.odds+100))*100:null;
    if(c!=null) $('#bCents').value=Number(c).toFixed(0);
    $('#bReason').value={wind:'wind',roof:'wind',gap:'gap',lean:'lean',spread:'lean'}[p.edgeFrom]||'other';
    $('#bNote').value=`Suggested: ${p.units?fmtU(p.units)+' ':''}${p.text}, ${signed(p.edge)}% edge`.slice(0,140);
    const u=unitUsd(), cc=Number($('#bCents').value)/100;
    if(p.units&&u&&cc>0&&cc<1){ const per=cc+feePer($('#bVenue').value,cc); $('#bQty').value=Math.max(1,Math.floor(p.units*u/per)); }
    preview();
    $('#bStatus').textContent=unitUsd()&&p.units
      ?`Filled in: ${fmtU(p.units)} = ${usdAmt(p.units*unitUsd())}. Set the price you actually paid, then Save.`
      :'Filled in from the pick: set the price you actually paid and how many contracts, then Save. (Enter your Kalshi bankroll above to size it in units.)';
    $('#betForm').scrollIntoView({behavior:'smooth',block:'center'});
    $('#bQty').focus({preventScroll:true});
  };

  $('#betForm').addEventListener('submit',async e=>{
    e.preventDefault();
    if(!store){ $('#bStatus').textContent='Still connecting to your saved bets. Try again in a moment.'; return; }
    const mk=$('#bMarket').value, cents=Number($('#bCents').value), n=Math.round(Number($('#bQty').value));
    const point=mk==='ml'?null:Number($('#bPoint').value);
    if(!(cents>0&&cents<100)||!(n>=1)||(mk!=='ml'&&!isFinite(point))||$('#bPoint').value===''&&mk!=='ml'){
      $('#bStatus').textContent='Check the line, the price (1–99¢) and the number of contracts.'; return; }
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
    const pushes=settled.length-won-lost;
    const pl=settled.reduce((s,r)=>s+r.pl,0), staked=settled.reduce((s,r)=>s+r.cost,0);
    const judged=rows.filter(r=>r.beat!=null), beat=judged.filter(r=>r.beat).length;
    const evs=rows.filter(r=>r.clvEv!=null), avgEv=evs.length?evs.reduce((s,r)=>s+r.clvEv,0)/evs.length:null;
    $('#betKpis').innerHTML=`
      <div class="kpi"><div class="v">${rows.length}</div><div class="l">Bets logged<br><span>${rows.length-settled.length} still open</span></div></div>
      <div class="kpi"><div class="v ${pl>0?'good':pl<0?'bad':''}">${settled.length?money(pl):'$0'}</div><div class="l">Profit so far<br><span>${settled.length?`${won} won, ${lost} lost${pushes?`, ${pushes} pushed`:''}${staked?` · ${signed(pl/staked*100)}% return`:''}`:'no finished bets yet'}</span></div></div>
      <div class="kpi"><div class="v ${judged.length&&beat/judged.length>0.5?'good':''}">${judged.length?Math.round(beat/judged.length*100)+'%':'n/a'}</div><div class="l">Beat the closing line<br><span>${judged.length?`${beat} of ${judged.length} bets; over 50% is a good sign`:'shows once your games kick off'}</span></div></div>
      <div class="kpi"><div class="v">${avgEv==null?'n/a':(avgEv>=0?'+':MINUS)+Math.abs(avgEv).toFixed(1)+'%'}</div><div class="l">Your price vs closing price<br><span>${avgEv==null?'needs bets at the closing line':avgEv>=0?'average, you paid less than the close':'average, you paid more than the close'}</span></div></div>`;
    $('#betTable').innerHTML=`<thead><tr><th>Game</th><th>Bet</th><th>Where</th><th class="n">Price paid</th><th class="n">Cost</th><th>Reason</th><th>Vs closing line</th><th>Result</th><th></th></tr></thead>
      <tbody>${rows.map(r=>{const b=r.b,g=r.g;
        const res=r.result?`<span class="${r.pl>0?'ok':r.pl<0?'no':'push'}">${r.result==='won'?'Won':r.result==='lost'?'Lost':'Push'} ${money(r.pl)}</span>`
          :`<span class="push">${g?(g.status==='live'?'In progress':'Not played yet'):'Unknown game'}</span>`;
        return `<tr><td>${g?`${wkShort(g.wk)} · ${withLogo(g.away,g.awayName)} at ${withLogo(g.home,g.homeName)}`:esc(b.gid)}</td>
          <td>${esc(betText(b,g))}${b.note?`<div class="push small">${esc(b.note)}</div>`:''}</td>
          <td>${esc(VENUE[b.venue]||b.venue)}</td><td class="n">${Number(b.cents).toFixed(0)}¢ × ${b.n}</td>
          <td class="n">${money(r.cost).replace('+','')}</td><td>${esc(REASON[b.reason]||b.reason)}</td>
          <td>${vsCloseTxt(r)}</td><td>${res}</td>
          <td><button type="button" class="btn ghost small" data-del="${esc(b.id)}">Delete</button></td></tr>`;}).join('')
        ||'<tr><td colspan="9" class="push">No bets yet. Add your first one above.</td></tr>'}</tbody>`;
    let cum=0; const pts=settled.slice().sort((x,y)=>x.g.date<y.g.date?-1:1).map((r,i)=>({x:i+1,y:Math.round((cum+=r.pl)*100)/100,r}));
    lineChart($('#betChart'),{label:'Running profit in dollars, finished bets',series:[{name:'Profit',n:1,points:pts.length?[{x:0,y:0},...pts]:[]}],
      zero:true,height:220,yFmt:v=>(v<0?MINUS:'')+'$'+Math.abs(v),empty:'No finished bets yet. Your running profit appears here once your games end.',
      xTicks:pts.length?[{x:0,label:'Start'},{x:pts.length,label:`Bet ${pts.length}`}]:[],
      tip:x=>{const q=pts[Math.round(x)-1]; return q?`<div>${esc(betText(q.r.b,q.r.g))} · ${fmtDay(q.r.g.date)}</div><div>Running total <b>${money(q.y)}</b></div>`:'<div>Start <b>$0</b></div>';}});
  };
  draw();
  $('#betsWhere').textContent='Connecting to your saved bets…';
  betStore().then(s=>{
    store=s;
    $('#betsWhere').textContent=s.kind==='db'?'Saved privately to your account':'Saved in this browser only';
    s.subscribe(list=>{bets=list; draw();},()=>{$('#betsWhere').textContent='Live sync stopped. Reload the page.';});
  });
}

/* ======================= season page ======================= */
function seasonBets(){
  const fin=D.games.filter(g=>g.status==='final').slice().sort((a,b)=>a.date<b.date?-1:a.date>b.date?1:0);
  const out=[];
  fin.forEach(g=>{
    if('underUnits' in g) out.push({g,type:'wind',label:`Under ${g.total.line}`,price:g.total.uo,detail:`Wind ${g.wind.toFixed(0)} mph`,u:g.underUnits});
    if(g.mkt&&'leanUnits' in g.mkt){ const side=g.mkt.lean==='home'?g.homeName:g.awayName;
      out.push({g,type:'lean',label:`${side} to win`,price:g.mkt.leanOdds,detail:`Expected return ${signed(g.mkt.leanEv)}%`,u:g.mkt.leanUnits}); }
  });
  return out;
}
function seasonPage(){
  const s=D.summary, c=u=>u>0?'good':u<0?'bad':'';
  const rec=o=>`${o.won} won, ${o.lost} lost${o.n-o.won-o.lost?`, ${o.n-o.won-o.lost} pushed`:''}`;
  const ret=o=>o.n?` · ${signed(o.units/o.n*100)}% return`:'';
  $('#seasonTitle').textContent=`${D.season} season so far`;
  $('#seasonSub').textContent=`${s.final} games played · results are profit on $100 bets`;
  const better=s.eloLL==null?null:Math.abs(s.eloLL-s.mktLL)<0.002?'About even':s.mktLL<s.eloLL?'Betting market':'Our model';
  $('#kpis').innerHTML=`
    <div class="kpi"><div class="v ${c(s.wind.units)}">${s.wind.n?per100(s.wind.units):'$0'}</div><div class="l">Wind under bets<br><span>${s.wind.n?rec(s.wind)+ret(s.wind):'none finished yet'}</span></div></div>
    <div class="kpi"><div class="v ${c(s.lean.units)}">${s.lean.n?per100(s.lean.units):'$0'}</div><div class="l">Model lean bets<br><span>${s.lean.n?rec(s.lean)+ret(s.lean):'none finished yet'}</span></div></div>
    <div class="kpi"><div class="v">${s.eloAcc!=null?pct(s.eloAcc):'n/a'} <small>vs ${s.mktAcc!=null?pct(s.mktAcc):'n/a'}</small></div><div class="l">Winners picked<br><span>our model vs the betting market (${s.withLines} games)</span></div></div>
    <div class="kpi"><div class="v small-v">${better||'n/a'}</div><div class="l">More accurate overall<br><span>judged by how confident each was, not just picks</span></div></div>`;

  /* Scoreboard: every suggestion graded at the price first shown, and whether that price beat the close */
  const B=s.picks;
  if(B&&$('#pickBoard')){
    const KIND=[['wind','Wind unders','under'],['gap','Price gaps','gap'],['lean','Model picks · moneyline','lean'],['spread','Model picks · spread','lean']];
    const line=(label,o,tag)=>`<tr${tag===null?' class="sel"':''}><td>${tag?`<span class="tag ${tag}">${label}</span>`:`<b>${label}</b>`}</td>
      <td class="n">${o.n}</td><td>${o.n?`${o.won}–${o.lost}${o.push?`–${o.push}`:''}`:'<span class="push">none yet</span>'}</td>
      <td class="n ${cls(o.units)}">${o.n?per100(o.units):'—'}</td><td class="n ${cls(o.units)}">${o.n?signed(o.units/o.n*100)+'%':'—'}</td>
      <td class="n ${cls(o.sized)}">${o.n?`${o.sized>0?'+':o.sized<0?MINUS:''}${fmtU(Math.abs(o.sized))} <span class="push small">on ${fmtU(o.staked)}</span>`:'—'}</td>
      <td>${o.judged?`<b class="${o.beat/o.judged>0.5?'ok':'no'}">${o.beat} of ${o.judged}</b>${o.clvAvg!=null?` <span class="push">· ${signed(o.clvAvg)}% avg</span>`:''}`:'<span class="push">once logged picks finish</span>'}</td></tr>`;
    $('#pickBoard').innerHTML=`<thead><tr><th>Kind of bet</th><th class="n">Bets</th><th>Won–lost</th><th class="n">Profit on $100 each</th><th class="n">Return</th><th class="n">As sized (units)</th><th>Beat the closing price</th></tr></thead>
      <tbody>${KIND.map(([k,l,t])=>line(l,B[k],t)).join('')}${line('All suggestions',B.all,null)}</tbody>`;
    const st=s.pickLogStarted;
    $('#pickBoardNote').textContent=`Every bet the “Bets to take” boxes suggested, graded at the price shown when it first appeared.`
      +` “Beat the closing price” compares that price with the final line before kickoff: beating it more than half the time is`
      +` the best early sign of a real edge, long before wins and losses mean anything.`
      +(st?` The site started saving its suggestions ${fmtLogged(st)}; games before that are reconstructed at closing prices,`
        +` so they count in wins and losses but can’t test the closing price.`:'');
  }

  const bets=seasonBets();
  const series=[{name:'Wind unders',n:1,type:'wind'},{name:'Model leans',n:2,type:'lean'}].map(se=>{
    let cum=0; const pts=[];
    bets.filter(b=>b.type===se.type).forEach(b=>{ cum+=b.u*100; pts.push({x:day(b.g.date),y:Math.round(cum)}); });
    const byDay=new Map(); pts.forEach(p=>byDay.set(p.x,p));          // one point per day
    const start=D.games.length?day(D.games[0].date)-1:0;
    return {name:se.name,n:se.n,points:[{x:start,y:0},...byDay.values()]};
  });
  const at=(se,x)=>{let v=0; se.points.forEach(p=>{if(p.x<=x) v=p.y;}); return v;};
  const xs=series.flatMap(se=>se.points.map(p=>p.x));
  lineChart($('#cumChart'),{label:'Running profit on $100 bets: wind unders and model leans',series,zero:true,endLabels:true,height:270,left:64,
    yFmt:v=>usd(v), refLabel:null,
    xTicks:xs.length?[{x:Math.min(...xs),label:fmtDay(D.games[0].date)},...monthTicks(Math.min(...xs),Math.max(...xs))]:[],
    empty:'No bets finished yet this season.',
    tip:x=>{const d=new Date(x*864e5); return `<div>${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}</div>`+
      series.map(se=>`<div><span style="color:var(--series-${se.n})">●</span> ${se.name} <b>${usd(at(se,x))}</b></div>`).join('');}});

  const cnt=(n,u)=>n?`<span class="${cls(u)}">${per100(u)}</span> <span class="push">· ${plural(n,'bet')}</span>`:'<span class="push">No bets</span>';
  $('#byWeek').innerHTML=`<thead><tr><th>Week</th><th class="n">Games</th><th class="n">Model picks right</th><th class="n">Market picks right</th>
    <th>Model lean bets</th><th>Wind under bets</th></tr></thead><tbody>${s.byWeek.map(r=>`<tr>
    <td><a href="index.html#week${r.wk}">${wkName(r.wk)}</a></td><td class="n">${r.games}</td>
    <td class="n">${r.eloRight} of ${r.decided}</td><td class="n">${r.mktRight} of ${r.decided}</td>
    <td>${cnt(r.leanN,r.leanUnits)}</td><td>${cnt(r.windN,r.windUnits)}</td></tr>`).join('')
    ||'<tr><td colspan="6">No finished games yet.</td></tr>'}</tbody>`;

  let f='all';
  const log=()=>{
    const rows=bets.filter(b=>f==='all'||b.type===f).slice().reverse();
    $('#betLog').innerHTML=`<thead><tr><th>Date</th><th>Game and final score</th><th>Bet</th><th class="n">Odds</th><th>Why</th><th>Result on $100</th></tr></thead>
      <tbody>${rows.map(b=>`<tr><td>${fmtDay(b.g.date)} <span class="push">· ${wkShort(b.g.wk)}</span></td>
        <td>${withLogo(b.g.away,b.g.awayName)} ${b.g.as}, ${withLogo(b.g.home,b.g.homeName)} ${b.g.hs}</td>
        <td><span class="tag ${b.type==='wind'?'under':'lean'}">${b.type==='wind'?'Wind':'Lean'}</span> ${esc(b.label)}</td>
        <td class="n">${odds(b.price)}</td><td class="push">${esc(b.detail)}</td>
        <td class="${cls(b.u)}">${b.u>0?'Won':b.u<0?'Lost':'Push'} ${per100(b.u)}</td></tr>`).join('')||'<tr><td colspan="6">No bets yet.</td></tr>'}</tbody>`;
  };
  document.addEventListener('click',e=>{const b=e.target.closest('[data-f]'); if(!b) return; f=b.dataset.f;
    $$('#filters button').forEach(x=>x.setAttribute('aria-pressed',x===b)); log();});
  log();
}

/* ======================= teams page ======================= */
function teamsPage(){
  const T=D.teams; if(!T.length) return;
  const max=vsAvg(T[0].rating), min=vsAvg(T[T.length-1].rating);
  const wkGames=D.games.filter(g=>g.wk===D.deltaWeek);
  const played=new Set(wkGames.filter(g=>g.status==='final').flatMap(g=>[g.home,g.away]));
  const scheduled=new Set(wkGames.flatMap(g=>[g.home,g.away]));
  let sel=decodeURIComponent((location.hash||'').slice(1)); if(!NAME[sel]) sel=T[0].team;
  $('#powerSub').textContent=`Updated after every game. “Win chance” is the chance to beat an average team on a neutral field. Change is since the start of ${wkName(D.deltaWeek||D.currentWeek)}.`;
  const change=r=>{
    if(D.deltaWeek&&!played.has(r.team))
      return `<span class="push">${scheduled.has(r.team)?'Game still to play':'Bye week'}</span>`;
    const x=(vsAvg(r.rating)-vsAvg(r.rating-r.delta))*100;
    if(Math.abs(x)<0.05) return '<span class="push">No change</span>';
    return `<span class="${x>0?'ok':'no'}">${x>0?'▲':'▼'} ${Math.abs(x).toFixed(1)}%</span>`;
  };
  const table=()=>{
    $('#power').innerHTML=`<thead><tr><th class="n">Rank</th><th>Team</th><th>Record</th><th class="n">Win chance</th><th>Change</th><th aria-hidden="true"></th></tr></thead>
      <tbody>${T.map((r,i)=>`<tr class="${r.team===sel?'sel':''}"><td class="n">${i+1}</td>
        <td><button type="button" class="teamlink" data-team="${esc(r.team)}" style="${tcv(r.team)}">${logo(r.team,'sm')}${esc(r.name)}</button></td>
        <td>${esc(r.record)}</td><td class="n"><b>${pct(vsAvg(r.rating))}</b></td>
        <td>${change(r)}</td>
        <td style="width:22%"><span class="rbar" style="width:${8+92*(vsAvg(r.rating)-min)/Math.max(0.01,max-min)}%"></span></td></tr>`).join('')}</tbody>`;
  };
  const detail=()=>{
    const t=T.find(x=>x.team===sel), rank=T.indexOf(t)+1;
    $('#teamName').innerHTML=logo(t.team,'lg')+`<span>${esc(t.name)}</span>`;
    $('#teamName').style.setProperty('--tc',TCOLOR[t.team]||'#4c3a8f');
    $('#teamSub').textContent=`Ranked ${rank} of 32 · ${t.record} this season · would beat an average team ${pct(vsAvg(t.rating))} of the time`;
    const pts=t.hist.map((h,i)=>({x:i,y:Math.round(vsAvg(h[1])*1000)/10}));
    const xTicks=[]; t.hist.forEach((h,i)=>{ if(i===0||h[3]!==t.hist[i-1][3]) xTicks.push({x:i,label:`${h[3]} season`}); });
    lineChart($('#teamChart'),{label:`${t.name}: chance to beat an average team, last two seasons`,series:[{name:t.name,n:1,points:pts}],
      refY:50,refLabel:'Average team',height:220,left:48,yFmt:v=>Math.round(v)+'%',xTicks,
      tip:x=>{const h=t.hist[Math.round(x)]; return `<div>${fmtDay(h[0])}, ${h[3]}</div><div>${h[2]?'Before playing '+esc(NAME[h[2]]||h[2]):'Now'}: <b>${pct(vsAvg(h[1]))}</b></div>`;}});
    const gs=D.games.filter(g=>g.home===sel||g.away===sel);
    $('#teamGames').innerHTML=`<thead><tr><th>Week</th><th>Opponent</th><th class="n">Our model</th><th class="n">Betting market</th><th>Result</th></tr></thead>
      <tbody>${gs.map(g=>{const home=g.home===sel, opp=home?g.away:g.home, pe=home?g.pElo:1-g.pElo;
        const pm=g.mkt?(home?g.mkt.fair:1-g.mkt.fair):null;
        let r='<span class="push">'+esc(g.ko.split(' · ')[0])+'</span>';
        if(g.status==='final'){const us=home?g.hs:g.as, them=home?g.as:g.hs; r=`<span class="${us>them?'ok':us<them?'no':'push'}">${us>them?'Won':us<them?'Lost':'Tied'} ${us}–${them}</span>`;}
        return `<tr><td><a href="index.html#week${g.wk}">${wkShort(g.wk)}</a></td><td>${home?'vs':'at'} ${withLogo(opp,NAME[opp]||opp)}</td>
          <td class="n">${pct(pe)} to win</td><td class="n">${pm==null?'<span class="push">No line yet</span>':pct(pm)+' to win'}</td><td>${r}</td></tr>`;}).join('')}</tbody>`;
  };
  document.addEventListener('click',e=>{const b=e.target.closest('[data-team]'); if(!b) return; sel=b.dataset.team;
    try{history.replaceState(null,'','#'+sel);}catch(_){} table(); detail();
    if(innerWidth<780) $('#teamName').scrollIntoView({behavior:'smooth',block:'start'});});
  table(); detail();
}

/* ======================= method page ======================= */
function methodPage(){
  $$('[data-season]').forEach(el=>el.textContent=D.season);
  /* Section 3, this season: the same model table for this year's finished games (weekly.season_models) */
  const MR=(D.summary||{}).models;
  if(MR&&MR.length&&$('#thisYear')){
    const mkt=MR.find(r=>r.kind==='market'), n=MR[0].n;
    const ret=(v,b)=>`<td class="n ${cls(v)}">${b?signed(v)+'%':'—'} <span class="push small">${b?plural(b,'bet'):''}</span></td>`;
    $('#thisYearTitle').textContent=`This season so far (${D.season}, ${plural(n,'game')})`;
    $('#thisYear').innerHTML=`<thead><tr><th>Model</th><th class="n">Accuracy score<br>(lower is better)</th><th class="n">Winners picked</th>
      <th class="n">Return, every edge</th><th class="n">Return, edges over 3%</th></tr></thead><tbody>${MR.map(r=>r.kind==='market'
        ?`<tr><td>${esc(r.label)}</td><td class="n">${r.ll.toFixed(4)}</td><td class="n">${(r.acc*100).toFixed(1)}%</td><td class="n push">benchmark</td><td class="n"></td></tr>`
        :`<tr${r.kind==='site'?' class="sel"':''}><td>${esc(r.label)}</td><td class="n ${mkt&&r.ll<mkt.ll?'ok':''}">${r.ll.toFixed(4)}</td><td class="n">${(r.acc*100).toFixed(1)}%</td>`
          +ret(r.roi,r.bets)+ret(r.roi3,r.bets3)+'</tr>').join('')}</tbody>`;
    const beat=mkt?MR.filter(r=>r.kind!=='market'&&r.ll<mkt.ll).length:0;
    $('#thisYearNote').textContent=(beat?`So far this season ${beat===MR.length-1?'every model has':plural(beat,'model')+' have'} been more accurate than the closing line (green), the reverse of 2016–2025, when the market won 9 of 10 seasons.`
      :'So far this season the closing line has been more accurate than every model, as it was in 9 of 10 seasons from 2016 to 2025.')
      +` ${n} games is a small sample: one season can swing a lot, so the ten-season table above is the better guide. Highlighted rows are the model the site uses now.`;
  }
  /* Top tile: this season's model picks at the final line (Mason's request), with the long-run record under it */
  const L=(D.summary||{}).lean, tile=$('#modelYear');
  if(tile&&L&&L.n){
    const r=L.units/L.n*100;
    tile.innerHTML=`<div class="v ${r>0?'good':r<0?'bad':''}">${signed(r)}%</div><div class="l">Our model’s picks this season, at the final line<br>
      <span>${D.season}: ${L.won} won, ${L.lost} lost (${plural(L.n,'bet')}), ${per100(L.units)} on $100 bets · 2016–2025: −5.5%, so a hot start isn’t proof</span></div>`;
  }
}

/* ======================= motion + navigation ======================= */
/* Oct 5: Mason picked "C · Stadium" of 3 moving backgrounds (previews in build/motion/), plus search,
   week arrows, a phone tab bar and scroll reveals. Everything still works, and stays still, with
   prefers-reduced-motion. */
const REDUCE=matchMedia('(prefers-reduced-motion: reduce)').matches;

/* Moving background: a football field gliding toward you (yard lines, hash marks, numbers), two light
   towers with sweeping beams, dust in the light. Canvas at ≤30 fps (24 on phones), paused in hidden tabs,
   one still frame with reduced motion. Scrolling moves you down the field; the camera drifts with the mouse. */
function stadiumBg(page){
  const layer=document.createElement('div'); layer.className='bgfx'; layer.setAttribute('aria-hidden','true');
  const cv=document.createElement('canvas'); layer.appendChild(cv);
  layer.insertAdjacentHTML('beforeend','<i class="grain"></i><i class="vig"></i>');
  document.body.prepend(layer);
  const ctx=cv.getContext('2d'); if(!ctx) return;
  const M={x:innerWidth/2,on:false};
  addEventListener('pointermove',e=>{M.x=e.clientX; M.on=e.pointerType==='mouse';},{passive:true});
  document.documentElement.addEventListener('pointerleave',()=>{M.on=false;});
  let W=0,H=0,dpr=1,motes=[],cx=0;
  const size=()=>{
    const d=Math.min(1.5,devicePixelRatio||1), w=Math.round(innerWidth*d), h=Math.round(innerHeight*d);
    if(w===W&&Math.abs(h-H)<160*d) return;                 // phone address bar showing/hiding: just stretch
    dpr=d; W=cv.width=w; H=cv.height=h;
    motes=Array.from({length:innerWidth<700?28:70},()=>({x:Math.random(),y:Math.random(),s:.6+Math.random()*1.8,v:.008+Math.random()*.025,ph:Math.random()*6.283}));
  };
  const glow=(x,y,r,stops)=>{const g=ctx.createRadialGradient(x,y,0,x,y,r); stops.forEach(([o,c])=>g.addColorStop(o,c)); ctx.fillStyle=g; ctx.fillRect(x-r,y-r,2*r,2*r);};
  const a3=v=>v.toFixed(3);
  function frame(t){
    ctx.globalCompositeOperation='source-over'; ctx.clearRect(0,0,W,H);
    const hz=H*.42, F=H*.95, camH=6.5, zmin=camH*F/(H-hz)*.92, zfar=125, half=26.67;   // field is 53⅓ yards wide
    cx+=(((M.on?M.x/innerWidth:.5)-.5)*16-cx)*.04;
    const camZ=t*6+scrollY*.035;
    const px=(x,z)=>W/2+(x-cx)*F/z, py=z=>hz+camH*F/z;
    const fade=z=>Math.max(0,Math.min(1,1-(z-zmin)/(zfar-zmin)))**.9;
    glow(W/2,hz,W*.6,[[0,'rgba(124,58,237,.42)'],[.35,'rgba(76,29,149,.18)'],[1,'rgba(9,8,13,0)']]);       // sky glow
    for(let Y=Math.floor((camZ+zmin)/5)*5-5; Y<camZ+zfar; Y+=5){                                              // mowing stripes
      const za=Math.max(zmin*.8,Y-camZ), zb=Math.max(zmin*.8,Y+5-camZ); if(zb<=za) continue;
      const a=.55*fade((za+zb)/2);
      ctx.fillStyle=((Y/5)%2+2)%2===1?`rgba(46,24,96,${a3(a)})`:`rgba(28,15,60,${a3(a)})`;
      ctx.beginPath(); ctx.moveTo(px(-half,za),py(za)); ctx.lineTo(px(half,za),py(za)); ctx.lineTo(px(half,zb),py(zb)); ctx.lineTo(px(-half,zb),py(zb)); ctx.fill();
    }
    ctx.globalCompositeOperation='lighter';
    [-half,half].forEach(x=>{ for(let z=zmin*.8; z<zfar; z*=1.18){ const z2=Math.min(zfar,z*1.18);                  // sidelines
      ctx.strokeStyle=`rgba(216,204,255,${a3(.75*fade(z))})`; ctx.lineWidth=Math.max(1,40*dpr/z);
      ctx.beginPath(); ctx.moveTo(px(x,z),py(z)); ctx.lineTo(px(x,z2),py(z2)); ctx.stroke(); }});
    ctx.textAlign='center'; ctx.textBaseline='middle';
    for(let Y=Math.ceil(camZ+zmin*.8); Y<camZ+zfar; Y++){                                                         // yard lines, numbers, hashes
      const z=Y-camZ, a=fade(z), yy=py(z);
      if(Y%5===0){
        const major=Y%10===0;
        ctx.strokeStyle=`rgba(196,181,253,${a3((major?.9:.55)*a)})`; ctx.lineWidth=Math.max(1,(major?55:38)*dpr/z);
        ctx.beginPath(); ctx.moveTo(px(-half,z),yy); ctx.lineTo(px(half,z),yy); ctx.stroke();
        ctx.strokeStyle=`rgba(139,92,246,${a3(.35*a)})`; ctx.lineWidth=Math.max(3,(major?260:160)*dpr/z);
        ctx.beginPath(); ctx.moveTo(px(-half,z),yy); ctx.lineTo(px(half,z),yy); ctx.stroke();
        const N=((Y%100)+100)%100;
        if(major&&N&&z<70){
          const lab=String(N<=50?N:100-N), zn=z+1.2, s=F/zn*.022;
          ctx.fillStyle=`rgba(221,214,254,${a3(.7*a)})`; ctx.font='800 100px Unbounded, system-ui, sans-serif';
          [-15.5,15.5].forEach(x=>{ ctx.save(); ctx.translate(px(x,zn),py(zn)); ctx.scale(s,s*camH/zn*1.6); ctx.fillText(lab,0,0); ctx.restore(); });
        }
      } else if(z<65){
        ctx.strokeStyle=`rgba(196,181,253,${a3(.5*a)})`; ctx.lineWidth=Math.max(1,30*dpr/z);
        [-3.1,3.1,-half+.5,half-.5].forEach(x=>{ ctx.beginPath(); ctx.moveTo(px(x-.35,z),yy); ctx.lineTo(px(x+.35,z),yy); ctx.stroke(); });
      }
    }
    const hg=ctx.createLinearGradient(0,hz-H*.02,0,hz+H*.1); hg.addColorStop(0,'rgba(124,58,237,.35)'); hg.addColorStop(1,'rgba(124,58,237,0)');
    ctx.fillStyle=hg; ctx.fillRect(0,hz-H*.02,W,H*.12);                                                            // horizon haze
    [[W*.07,H*.2,.6],[W*.93,H*.2,-.6]].forEach(([lx,ly,dir],k)=>{                                                   // light towers
      for(let b=0;b<2;b++){
        const ang=Math.PI/2-dir*(.55+b*.32)+.22*Math.sin(t*(.35+b*.12)+k*2+b), sp=.085, len=H*1.6;
        const g=ctx.createLinearGradient(lx,ly,lx+Math.cos(ang)*len,ly+Math.sin(ang)*len);
        g.addColorStop(0,'rgba(221,214,254,.34)'); g.addColorStop(.45,'rgba(167,139,250,.12)'); g.addColorStop(1,'rgba(139,92,246,0)');
        ctx.fillStyle=g; ctx.beginPath(); ctx.moveTo(lx,ly);
        ctx.lineTo(lx+Math.cos(ang-sp)*len,ly+Math.sin(ang-sp)*len); ctx.lineTo(lx+Math.cos(ang+sp)*len,ly+Math.sin(ang+sp)*len); ctx.fill();
        const hit=(hz+H*.2-ly)/Math.sin(ang);                                                                        // pool of light on the field
        ctx.save(); ctx.translate(lx+Math.cos(ang)*hit,hz+H*.2); ctx.scale(1,.32); glow(0,0,W*.12,[[0,'rgba(196,181,253,.22)'],[1,'rgba(139,92,246,0)']]); ctx.restore();
      }
      const fl=.85+.15*Math.sin(t*9+k*3)*Math.sin(t*2.3+k);
      glow(lx,ly,H*.32*fl,[[0,'rgba(255,255,255,.55)'],[.08,'rgba(221,214,254,.45)'],[.3,'rgba(139,92,246,.16)'],[1,'rgba(139,92,246,0)']]);
      ctx.save(); ctx.translate(lx,ly); ctx.scale(6,.18); glow(0,0,H*.12,[[0,'rgba(233,221,255,.5)'],[1,'rgba(139,92,246,0)']]); ctx.restore();
      ctx.fillStyle='rgba(255,255,255,.95)'; const s=3.2*dpr;
      for(let r=0;r<3;r++) for(let c=0;c<6;c++) ctx.fillRect(lx-(2.5-c)*s*2.6-s/2,ly-(1-r)*s*2.6-s/2,s,s);
    });
    motes.forEach(m=>{ m.y-=m.v/30; if(m.y<-.05){m.y=1.05; m.x=Math.random();}                                      // dust
      ctx.fillStyle=`rgba(221,214,254,${a3(.25+.35*(.5+.5*Math.sin(t*1.7+m.ph)))})`;
      ctx.beginPath(); ctx.arc((m.x+.02*Math.sin(t*.6+m.ph))*W,m.y*H,m.s*dpr,0,6.283); ctx.fill(); });
    ctx.globalCompositeOperation='source-over';
  }
  size(); addEventListener('resize',size);
  // full strength at the top of the page, calmer behind the reading further down (most on the Method page)
  const floor=page==='method'?.32:.55; let op=-1;
  const dim=()=>{const v=Math.round((1-Math.min(1,scrollY/600)*(1-floor))*100)/100; if(v!==op){op=v; cv.style.opacity=v;}};
  dim(); addEventListener('scroll',dim,{passive:true});
  if(REDUCE){ frame(7); addEventListener('resize',()=>frame(7)); return; }
  const fps=innerWidth<700?24:30, t0=performance.now(); let last=-1e9;
  const tick=now=>{requestAnimationFrame(tick); if(document.hidden||now-last<1000/fps-2) return; last=now; frame((now-t0)/1000);};
  requestAnimationFrame(tick);
}

/* Search (Ctrl+K, / or the magnifier): pages, weeks, teams and this/next week's games. Week arrows and
   ← → keys on the week page, back-to-top, cards sliding in as you scroll, numbers counting up, and menu
   icons that turn the menu into a bottom tab bar on phones. */
function navExtras(page){
  const PAGEFILE={week:'index.html',season:'season.html',teams:'teams.html',method:'method.html'};
  const svg=d=>`<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
  const ICON={'index.html':svg('<rect x="3" y="4" width="18" height="17" rx="3"/><path d="M3 9h18M8 2v4M16 2v4"/>'),
    'index.html#bets':svg('<path d="M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4z"/>'),
    'season.html':svg('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'),
    'teams.html':svg('<path d="M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6z"/>'),
    'method.html':svg('<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5M8 7h7"/>')};
  $$('.nav a').forEach(a=>{const k=a.getAttribute('href'); if(ICON[k]&&!a.querySelector('svg')) a.innerHTML=ICON[k]+`<span>${esc(a.textContent)}</span>`;});

  /* ---- search ---- */
  const cur=D.currentWeek, weeks=[...new Set(D.games.map(g=>g.wk))].sort((a,b)=>a-b);
  const ITEMS=[
    {grp:'Pages',label:'This week',href:`index.html#week${cur}`,ico:'◉'},
    {grp:'Pages',label:'Best bets',href:`index.html#week${cur}`,goto:'playsWrap',ico:'★'},
    {grp:'Pages',label:'My bets',href:'index.html#bets',ico:'$'},
    {grp:'Pages',label:'Season & scoreboard',href:'season.html',ico:'▲'},
    {grp:'Pages',label:'Teams & power ratings',href:'teams.html',ico:'◆'},
    {grp:'Pages',label:'Method & research',href:'method.html',ico:'?'},
    ...(D.teams||[]).map(t=>({grp:'Teams',label:t.name,href:teamHref(t.team),goto:'teamName',teams:[t.team],sub:t.record})),
    ...D.games.filter(g=>g.wk===cur||g.wk===cur+1).map(g=>({grp:'Games',label:`${g.awayName} at ${g.homeName}`,href:`index.html#week${g.wk}`,
      goto:'g-'+g.id,teams:[g.away,g.home],sub:`${wkShort(g.wk)} · ${g.ko.split(' · ')[0]}`})),
    ...weeks.map(w=>({grp:'Weeks',label:wkName(w),href:`index.html#week${w}`,ico:SHORT[w]||String(w),sub:w===cur?'this week':''}))
  ].map(it=>({...it,keys:`${it.label} ${(it.teams||[]).join(' ')}`.toLowerCase().split(/[\s·&]+/).filter(Boolean)}));
  const bar=$('.brandrow');
  let btn=null;
  if(bar){ btn=document.createElement('button'); btn.type='button'; btn.className='cmdk-btn'; btn.setAttribute('aria-label','Search the site');
    btn.innerHTML=svg('<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>')+'<span>Search</span><kbd>Ctrl K</kbd>';
    bar.insertBefore(btn,bar.querySelector('.stamp')); btn.addEventListener('click',()=>open()); }
  const ov=document.createElement('div'); ov.className='cmdk'; ov.hidden=true;
  ov.innerHTML=`<div class="cmdk-box" role="dialog" aria-modal="true" aria-label="Search the site">
    <input type="text" placeholder="Search teams, games, weeks, pages…" aria-label="Search" aria-controls="cmdkList" autocomplete="off" spellcheck="false">
    <div class="cmdk-list" id="cmdkList" role="listbox"></div><div class="cmdk-foot">↑ ↓ to move · Enter to open · Esc to close</div></div>`;
  document.body.appendChild(ov);
  const inp=ov.querySelector('input'), list=ov.querySelector('.cmdk-list');
  let shown=[], sel=0;
  function draw(){
    const q=inp.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    shown=q.length?ITEMS.filter(it=>q.every(w=>it.keys.some(k=>k.startsWith(w)))).slice(0,40)
      :ITEMS.filter(it=>it.grp==='Pages'||(it.grp==='Games'&&it.href.endsWith('#week'+cur)));
    sel=Math.min(sel,Math.max(0,shown.length-1));
    let last='';
    list.innerHTML=shown.map((it,i)=>{const h=it.grp!==last?`<div class="cmdk-grp">${it.grp}</div>`:''; last=it.grp;
      const icon=it.teams?`<span class="cmdk-logos">${it.teams.map(c=>logo(c,'xs')).join('')}</span>`:`<span class="cmdk-ico">${esc(it.ico)}</span>`;
      return h+`<div class="cmdk-it${i===sel?' on':''}" data-i="${i}" role="option" aria-selected="${i===sel}">${icon}<span>${esc(it.label)}</span>${it.sub?`<span class="sub">${esc(it.sub)}</span>`:''}</div>`;}).join('')
      ||'<div class="cmdk-none">Nothing found.</div>';
    const on=list.querySelector('.on'); if(on) on.scrollIntoView({block:'nearest'});
  }
  function open(){ ov.hidden=false; inp.value=''; sel=0; draw(); inp.focus(); }
  function close(){ if(ov.hidden) return; ov.hidden=true; if(btn) btn.focus({preventScroll:true}); }
  function go(it){
    if(!it) return; close();
    const [file,hash='']=it.href.split('#');
    if(file!==PAGEFILE[page]){ try{sessionStorage.setItem('btb.goto',it.goto||'');}catch(_){} location.href=it.href; return; }
    if(page==='teams'&&hash){ const b=$(`[data-team="${CSS.escape(decodeURIComponent(hash))}"]`); if(b) b.click(); }
    else if(location.hash!=='#'+hash) location.hash=hash;
    setTimeout(()=>goTo(it.goto||(page==='week'?'':'top')),120);
  }
  function goTo(id){
    if(id==='top'){ scrollTo({top:0,behavior:REDUCE?'auto':'smooth'}); return; }
    const el=id&&document.getElementById(id); if(!el||!el.offsetParent) return;
    el.scrollIntoView({behavior:REDUCE?'auto':'smooth',block:'start'});
    if(el.classList.contains('game')&&el.animate) el.animate([{boxShadow:'0 0 0 3px #a78bfa'},{boxShadow:'0 0 0 0 rgba(167,139,250,0)'}],{duration:1800});
  }
  inp.addEventListener('input',()=>{sel=0; draw();});
  inp.addEventListener('keydown',e=>{
    if(e.key==='ArrowDown'){sel=Math.min(sel+1,shown.length-1); draw(); e.preventDefault();}
    else if(e.key==='ArrowUp'){sel=Math.max(sel-1,0); draw(); e.preventDefault();}
    else if(e.key==='Enter'){e.preventDefault(); go(shown[sel]);}
    else if(e.key==='Escape'){close();}
  });
  list.addEventListener('click',e=>{const it=e.target.closest('[data-i]'); if(it) go(shown[+it.dataset.i]);});
  ov.addEventListener('click',e=>{if(e.target===ov) close();});
  setTimeout(()=>{let id=''; try{id=sessionStorage.getItem('btb.goto')||''; sessionStorage.removeItem('btb.goto');}catch(_){} if(id) goTo(id);},350);

  /* ---- week arrows beside the title (week page) ---- */
  let step=null;
  if(page==='week'&&$('#weekTitle')){
    const box=document.createElement('span'); box.className='wkarrows';
    box.innerHTML='<button type="button" aria-label="Previous week">‹</button><button type="button" aria-label="Next week">›</button>';
    $('#weekTitle').after(box);
    const [prev,next]=box.children, at=()=>{const b=$$('#rail .wk'); return [b,b.findIndex(x=>x.getAttribute('aria-pressed')==='true')];};
    step=d=>{const [b,i]=at(); if(i>=0&&b[i+d]) b[i+d].click();};
    const sync=()=>{const [b,i]=at(); prev.disabled=i<=0; next.disabled=i<0||i>=b.length-1;};
    prev.addEventListener('click',()=>step(-1)); next.addEventListener('click',()=>step(1));
    new MutationObserver(sync).observe($('#rail'),{childList:true}); sync();
  }
  document.addEventListener('keydown',e=>{
    const typing=/^(input|select|textarea)$/i.test((e.target||{}).tagName||'')||(e.target&&e.target.isContentEditable);
    if((e.key==='k'||e.key==='K')&&(e.ctrlKey||e.metaKey)){ e.preventDefault(); ov.hidden?open():close(); return; }
    if(!ov.hidden||typing||e.ctrlKey||e.metaKey||e.altKey) return;
    if(e.key==='/'){ e.preventDefault(); open(); return; }
    if(step&&(e.key==='ArrowLeft'||e.key==='ArrowRight')&&!$('#weekView').hidden) step(e.key==='ArrowLeft'?-1:1);
  });

  /* ---- back to top ---- */
  const top=document.createElement('button'); top.type='button'; top.className='totop'; top.setAttribute('aria-label','Back to top'); top.textContent='↑';
  document.body.appendChild(top); top.addEventListener('click',()=>scrollTo({top:0,behavior:REDUCE?'auto':'smooth'}));
  addEventListener('scroll',()=>top.classList.toggle('show',scrollY>700),{passive:true});

  /* ---- slide-in on scroll + count-up (things already on screen just show; anything redrawn later just appears) ---- */
  if(REDUCE||!('IntersectionObserver' in window)) return;
  const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in'); io.unobserve(e.target);}}),{rootMargin:'0px 0px -40px 0px'});
  $$('.game,.best,.kpi,.tablebox,.panel,.chart,.prose h2,.ukey').forEach((el,i)=>{
    const r=el.getBoundingClientRect(); if(!el.offsetParent||r.top<innerHeight) return;
    el.classList.add('rv'); el.style.transitionDelay=(i%3)*70+'ms'; io.observe(el);});
  $$('.kpi .v').forEach(el=>{
    const node=el.firstChild; if(el.childNodes.length!==1||!node||node.nodeType!==3) return;
    const m=node.textContent.match(/^([^\d−-]*)([−-]?)([\d,]+(?:\.\d+)?)(.*)$/); if(!m) return;
    const target=parseFloat(m[3].replace(/,/g,'')), dec=(m[3].split('.')[1]||'').length, t0=performance.now(), final=node.textContent;
    const tick=t=>{const k=Math.min(1,(t-t0)/900), v=target*(1-Math.pow(1-k,3));
      node.textContent=k<1?m[1]+m[2]+v.toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec})+m[4]:final; if(k<1) requestAnimationFrame(tick);};
    requestAnimationFrame(tick);
  });
}

window.EDGE_TEST={betMath,fairNow,feePer,betText};   // for tests/tracker_test.html
chrome();
const page=($('main')||{}).dataset?.page;
({week:weekPage,season:seasonPage,teams:teamsPage,method:methodPage}[page]||(()=>{}))();
liveTick();
if(page){ stadiumBg(page); navExtras(page); }
})();
