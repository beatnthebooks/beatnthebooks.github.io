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
function chrome(){
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
  function results(g){
    if(g.status!=='final') return '';
    const winner=g.hs>g.as?g.homeName:g.as>g.hs?g.awayName:null;
    const out=[];
    if('eloRight' in g){ const pick=g.pElo>=0.5?g.homeName:g.awayName;
      out.push(`<span class="pill ${g.eloRight?'ok':'no'}">${g.eloRight?'✓':'✗'} Model picked ${esc(pick)}</span>`); }
    if(g.mkt&&'mktRight' in g.mkt){ const fav=g.mkt.fair>=0.5?g.homeName:g.awayName;
      out.push(`<span class="pill ${g.mkt.mktRight?'ok':'no'}">${g.mkt.mktRight?'✓':'✗'} Market favored ${esc(fav)}</span>`); }
    if(g.mkt&&'leanUnits' in g.mkt){ const u=g.mkt.leanUnits;
      out.push(`<span class="pill ${cls(u)}">Lean bet ${u>0?'won':u<0?'lost':'pushed'} ${per100(u)}</span>`); }
    if('underUnits' in g){ const u=g.underUnits;
      out.push(`<span class="pill ${cls(u)}">Under bet ${u>0?'won':u<0?'lost':'pushed'} ${per100(u)}</span>`); }
    const head=winner?`${esc(winner)} won by ${Math.abs(g.hs-g.as)}`:'Tie game';
    return `<div class="results"><div class="rhead">${head}${g.windRecorded!=null?` <span class="why">· actual wind ${g.windRecorded} mph</span>`:''}</div>
      ${out.length?`<div class="pills">${out.join('')}</div><div class="why">Bet results are per $100 bet.</div>`:''}</div>`;
  }
  function card(g){
    const f=g.status==='final', aw=f&&g.as>g.hs, hw=f&&g.hs>g.as;
    const status=f?'<span class="chip final">Final</span>':g.status==='live'?'<span class="chip live">In progress</span>':'';
    const intl=g.neutral||/Tottenham|Wembley|Allianz|Deutsche|Bernabeu|Azteca|Banorte|Maracan|Corinthians/.test(g.stadium||'');
    const mk=g.mkt, sp=g.spread, tt=g.total;
    const fav=sp?favorite(sp.line,g):null, modelFav=favorite(g.eloLine,g);
    const notes=(g.notes||[]).map(n=>`<div class="note">${esc(n)}</div>`).join('');
    const team=(code,name,score,win)=>`<div class="trow ${f?(win?'win':'lose'):''}"><a href="${teamHref(code)}">${esc(name)}</a>${f?`<span class="score">${score}</span>`:''}</div>`;
    return `<article class="game ${g.signal==='under'?'sig-card':''}" id="g-${esc(g.id)}">
      <header class="ghead">
        <div class="gmeta"><span>${esc(g.ko)}</span>${status}${intl?`<span class="chip venue">${esc(g.stadium)}</span>`:''}</div>
        <div class="teams">${team(g.away,g.awayName,g.as,aw)}${team(g.home,g.homeName,g.hs,hw)}</div>
        <div class="why">${esc(g.awayName)} at ${esc(g.homeName)}</div>
      </header>
      <div class="gbody">
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
        ${shopBlock(g)}
        <div class="block signals"><div class="bh">Signals</div>${windLine(g)}${leanLine(g)}</div>
        ${notes?`<div class="block">${notes}</div>`:''}
      </div>
      ${f?`<footer class="gfoot">${results(g)}</footer>`:''}
    </article>`;
  }
  function render(){
    rail();
    const gs=D.games.filter(g=>g.wk===week);
    const fin=gs.filter(g=>g.status==='final').length;
    const sig=gs.filter(g=>g.signal==='under'), leans=gs.filter(g=>g.mkt&&g.mkt.lean).length;
    const gaps=gs.filter(g=>g.status==='upcoming'&&g.gaps&&g.gaps.length);
    $('#weekEyebrow').textContent=`${D.season} season${week===D.currentWeek?' · this week':''}`;
    $('#weekTitle').textContent=wkName(week);
    $('#weekSub').textContent=gs.length?`${gs[0].ko.split(' · ')[0]} to ${gs[gs.length-1].ko.split(' · ')[0]}`:'';
    $('#kpis').innerHTML=`
      <div class="kpi"><div class="v">${gs.length}</div><div class="l">Games<br><span>${fin} finished, ${gs.length-fin} to play</span></div></div>
      <div class="kpi"><div class="v ${sig.length?'good':''}">${sig.length}</div><div class="l">Under signals<br><span>windy outdoor games</span></div></div>
      <div class="kpi"><div class="v ${gaps.length?'good':''}">${D.oddsFetched?gaps.length:'n/a'}</div><div class="l">Price gaps<br><span>${D.oddsFetched?`Kalshi/Polymarket ${D.gapEv}%+ better than fair`:'needs sportsbook prices (private version)'}</span></div></div>
      <div class="kpi"><div class="v">${leans}</div><div class="l">Model leans<br><span>no proven edge</span></div></div>`;
    const open=sig.filter(g=>g.status==='upcoming');
    $('#playsWrap').hidden=!(open.length||gaps.length);
    $('#plays').innerHTML=open.map(g=>`<div class="play"><span class="tag under">Under signal</span>
      <span class="what">${esc(g.awayName)} at ${esc(g.homeName)}</span>
      <span class="why">${g.wind.toFixed(0)} mph wind forecast · ${esc(g.ko)} · re-check the forecast before kickoff</span>
      <a href="#g-${esc(g.id)}">See game</a></div>`).join('')
      +gaps.flatMap(g=>g.gaps.map(x=>`<div class="play"><span class="tag gap">Price gap</span>
      <span class="what">${gapTxt(g,x)}</span><span class="ok">${x.ev.toFixed(1)}% better than fair</span>
      <span class="why">${esc(g.awayName)} at ${esc(g.homeName)} · not yet proven · check the live price first</span>
      <a href="#g-${esc(g.id)}">See game</a></div>`)).join('');
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
    const wm=location.hash.match(/^#week(\d+)$/);
    if(wm&&weeks.includes(Number(wm[1]))) week=Number(wm[1]);
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
        return `<tr><td>${g?`${wkShort(g.wk)} · ${esc(g.awayName)} at ${esc(g.homeName)}`:esc(b.gid)}</td>
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
        <td>${esc(b.g.awayName)} ${b.g.as}, ${esc(b.g.homeName)} ${b.g.hs}</td>
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
        <td><button type="button" class="teamlink" data-team="${esc(r.team)}">${esc(r.name)}</button></td>
        <td>${esc(r.record)}</td><td class="n"><b>${pct(vsAvg(r.rating))}</b></td>
        <td>${change(r)}</td>
        <td style="width:22%"><span class="rbar" style="width:${8+92*(vsAvg(r.rating)-min)/Math.max(0.01,max-min)}%"></span></td></tr>`).join('')}</tbody>`;
  };
  const detail=()=>{
    const t=T.find(x=>x.team===sel), rank=T.indexOf(t)+1;
    $('#teamName').textContent=t.name;
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
        return `<tr><td><a href="index.html#week${g.wk}">${wkShort(g.wk)}</a></td><td>${home?'vs':'at'} ${esc(NAME[opp]||opp)}</td>
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
}

window.EDGE_TEST={betMath,fairNow,feePer,betText};   // for tests/tracker_test.html
chrome();
const page=($('main')||{}).dataset?.page;
({week:weekPage,season:seasonPage,teams:teamsPage,method:methodPage}[page]||(()=>{}))();
})();
