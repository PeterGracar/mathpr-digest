#!/usr/bin/env python3
"""Build the browsable HTML site from cached week JSON files.

Emits, into site/:
  * index.js          -- window.DIGEST_INDEX: lightweight metadata + per-week
                         summaries (counts only, NO entries). Loaded up front.
  * data/week-*.js    -- one file per week, window.DIGEST_WEEKS["<monday>"] =
                         {full entries}. Lazy-loaded on demand when a week is
                         opened, so the initial payload stays small and constant
                         no matter how many weeks accumulate.
  * index.html        -- the dynamic single-page browser
  * style.css         -- styling

Per-week files load via <script> injection, which works over http:// and from
file:// in most browsers; if a file:// browser blocks it, the page shows a hint
to serve the folder instead.

Can be run standalone (reads data/) or called as build(weeks).
"""
import glob
import json
import os
from datetime import datetime, timezone

import config

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SITE_DIR = os.path.join(HERE, "site")


def load_all_weeks():
    weeks = []
    for p in sorted(glob.glob(os.path.join(DATA_DIR, "week-*.json"))):
        with open(p) as f:
            weeks.append(json.load(f))
    return weeks


def _counts(week):
    c = {"coauthor": 0, "high": 0, "medium": 0, "other": 0}
    for e in week["entries"]:
        c[e.get("bucket", "other")] = c.get(e.get("bucket", "other"), 0) + 1
    c["total"] = len(week["entries"])
    return c


def build(weeks=None):
    if weeks is None:
        weeks = load_all_weeks()
    # newest first
    weeks = sorted(weeks, key=lambda w: w["monday"], reverse=True)
    site_data = os.path.join(SITE_DIR, "data")
    os.makedirs(site_data, exist_ok=True)

    # one lazy-loaded file per week (full entries)
    META = ("monday", "sunday", "iso_year", "iso_week", "category",
            "complete", "finalized", "data_through",
            "total_submissions", "fetched", "generated_at")
    summaries = []
    for w in weeks:
        with open(os.path.join(site_data, f"week-{w['monday']}.js"), "w") as f:
            f.write(f'window.DIGEST_WEEKS=window.DIGEST_WEEKS||{{}};'
                    f'window.DIGEST_WEEKS["{w["monday"]}"]=')
            json.dump(w, f, ensure_ascii=False)
            f.write(";\n")
        summary = {k: w.get(k) for k in META}
        summary["counts"] = _counts(w)
        summaries.append(summary)

    # lightweight index loaded up front (no entries)
    index = {
        "owner": config.OWNER,
        "profile_url": config.PROFILE_URL,
        "category": config.CATEGORY,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "coauthors": config.COAUTHORS,
        "weeks": summaries,
    }
    with open(os.path.join(SITE_DIR, "index.js"), "w") as f:
        f.write("window.DIGEST_INDEX = ")
        json.dump(index, f, ensure_ascii=False)
        f.write(";\n")

    # drop the old single-file payload if present (superseded by lazy loading)
    legacy = os.path.join(SITE_DIR, "digests.js")
    if os.path.exists(legacy):
        os.remove(legacy)

    with open(os.path.join(SITE_DIR, "index.html"), "w") as f:
        f.write(INDEX_HTML)
    with open(os.path.join(SITE_DIR, "style.css"), "w") as f:
        f.write(STYLE_CSS)
    print(f"  site built: {len(weeks)} week(s), lazy-loaded "
          f"-> {SITE_DIR}/index.html")


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>math.PR Weekly Digest &middot; Peter Gracar</title>
<link rel="stylesheet" href="style.css">
<script>
// Render LaTeX in arXiv titles/abstracts. Content is built dynamically, so we
// disable auto-typeset on load and call MathJax.typesetPromise() ourselves after
// each render (see typesetMath()).
window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\(', '\\)']],
    displayMath: [['$$', '$$'], ['\\[', '\\]']],
    processEscapes: true,
  },
  options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'] },
  startup: {
    typeset: false,
    ready: () => {
      MathJax.startup.defaultReady();
      // Typeset whatever was already rendered before MathJax finished loading.
      MathJax.startup.promise.then(() => {
        const m = document.querySelector('#main');
        if(m) MathJax.typesetPromise([m]).catch(()=>{});
      });
    },
  },
};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" id="MathJax-script" async></script>
</head>
<body>
<header>
  <div class="wrap">
    <h1>math.PR weekly digest</h1>
    <p class="sub">New submissions to <a href="https://arxiv.org/list/math.PR/recent" target="_blank" rel="noopener">arXiv math.PR</a>,
       curated for <a id="ownerLink" href="#" target="_blank" rel="noopener"></a>'s research interests
       &mdash; random geometric graphs, percolation, particle systems, and the spread of infection.</p>
  </div>
</header>

<div class="layout wrap">
  <aside id="sidebar">
    <div class="search"><input id="filter" type="search" placeholder="Filter titles / authors / keywords&hellip;"></div>
    <p class="searchstat" id="searchStat" hidden>searching all weeks&hellip;</p>
    <div id="allResults"></div>
    <h2>Digests</h2>
    <nav id="weekList"></nav>
    <div class="legend">
      <span class="chip coauthor">coauthor</span>
      <span class="chip high">highly relevant</span>
      <span class="chip medium">possibly relevant</span>
    </div>
    <p class="foot" id="genStamp"></p>
  </aside>

  <main id="main"></main>
</div>

<script src="index.js"></script>
<script>
const D = window.DIGEST_INDEX;
const $ = (s, r=document) => r.querySelector(s);
const el = (t, c, h) => { const e=document.createElement(t); if(c)e.className=c; if(h!=null)e.innerHTML=h; return e; };
const esc = s => (s||"").replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// Typeset any LaTeX inside a node once MathJax has loaded. Safe to call before
// MathJax is ready (the initial render is re-typeset from the startup hook below).
function typesetMath(node){
  if(!node || !window.MathJax || !MathJax.typesetPromise) return;
  MathJax.typesetClear && MathJax.typesetClear([node]);
  MathJax.typesetPromise([node]).catch(()=>{});
}

const BUCKETS = [
  {key:"coauthor", label:"Coauthor submissions", cls:"coauthor"},
  {key:"high",     label:"Highly relevant",      cls:"high"},
  {key:"medium",   label:"Possibly relevant",    cls:"medium"},
  {key:"other",    label:"Everything else",      cls:"other"},
];

function fmtRange(w){
  const o={month:'short',day:'numeric'};
  const a=new Date(w.monday+'T00:00:00'), b=new Date(w.sunday+'T00:00:00');
  return a.toLocaleDateString('en-GB',o)+' – '+b.toLocaleDateString('en-GB',{...o,year:'numeric'});
}
function fmtDay(d){ return d? new Date(d+'T00:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : ''; }
const inProgress = w => w.complete===false;

function authorsHTML(e){
  const set=new Set((e.coauthors||[]).map(c=>c.toLowerCase()));
  return e.authors.map(a=>{
    const isCo=[...set].some(c=>{const p=c.split(' ');return a.toLowerCase().includes(p[p.length-1].replace(/[^a-z]/g,''));});
    return isCo? '<strong class="co">'+esc(a)+'</strong>' : esc(a);
  }).join(', ');
}

function entryCard(e){
  const card=el('article','entry b-'+e.bucket);
  const cats=e.categories.map(c=>'<span class="cat'+(c===e.primary_category?' prim':'')+'">'+esc(c)+'</span>').join('');
  const kws=(e.matched_keywords||[]).slice(0,8).map(k=>'<span class="kw">'+esc(k)+'</span>').join('');
  const co=(e.coauthors&&e.coauthors.length)?'<div class="cobanner">★ Coauthor: '+e.coauthors.map(esc).join(', ')+'</div>':'';
  card.innerHTML =
    co+
    '<h3><a href="'+e.abs_url+'" target="_blank" rel="noopener">'+esc(e.title)+'</a></h3>'+
    '<div class="authors">'+authorsHTML(e)+'</div>'+
    '<div class="meta">'+cats+' <a class="idlink" href="'+e.abs_url+'" target="_blank" rel="noopener">'+esc(e.id)+'</a>'+
      ' &middot; <a href="'+e.pdf_url+'" target="_blank" rel="noopener">pdf</a></div>'+
    '<details class="abs"><summary>Abstract</summary><p>'+esc(e.abstract)+'</p></details>'+
    (kws?'<div class="kws">'+kws+'</div>':'');
  return card;
}

// Single source of truth for what "matches" the search term, shared by the main
// panel, the per-week sidebar counts, and the combined view. `t` MUST already be
// trimmed + lowercased by the caller.
function entryMatches(e, t){
  return (e.title+' '+e.authors.join(' ')+' '+
          (e.matched_keywords||[]).join(' ')+' '+e.abstract)
         .toLowerCase().includes(t);
}

// Wire up the collapsible "Everything else" bucket. When it starts hidden we tag
// it tex2jax_ignore so the page-level typeset skips it (it's the largest bucket),
// then typeset it lazily the first time it's expanded — keeping MathJax work off
// content the reader hasn't opened.
function collapsibleOther(sec, body, startHidden){
  if(startHidden) body.classList.add('hidden','tex2jax_ignore');
  let typeset=!startHidden;
  sec.querySelector('.bhead').addEventListener('click',()=>{
    const hidden=body.classList.toggle('hidden');
    if(!hidden && !typeset){ body.classList.remove('tex2jax_ignore'); typeset=true; typesetMath(body); }
  });
}

function renderWeek(w, term){
  const main=$('#main'); main.innerHTML='';
  const head=el('div','weekhead');
  const coN=w.entries.filter(e=>e.bucket==='coauthor').length;
  head.innerHTML='<h2>'+fmtRange(w)+(inProgress(w)?' <span class="tag-prog">in progress</span>':'')+'</h2>'+
    '<p class="wstats">'+w.entries.length+(inProgress(w)?' submissions so far':' new submissions')+' to '+esc(w.category)+
    ' &middot; ISO week '+w.iso_year+'-W'+String(w.iso_week).padStart(2,'0')+
    (coN?' &middot; <span class="hl">'+coN+' coauthor</span>':'')+'</p>'+
    (inProgress(w)?'<div class="progress">● Partial week — data through '+fmtDay(w.data_through)+
      '. This digest updates automatically on each run until the week closes.</div>':'');
  main.appendChild(head);

  const t=(term||'').trim().toLowerCase();
  let shown=0;
  for(const b of BUCKETS){
    let items=w.entries.filter(e=>e.bucket===b.key);
    if(t) items=items.filter(e=>entryMatches(e,t));
    if(!items.length) continue;
    const sec=el('section','bucket '+b.cls);
    const isOther=b.key==='other';
    sec.innerHTML='<h3 class="bhead'+(isOther?' collapsible':'')+'">'+b.label+' <span class="ct">'+items.length+'</span></h3>';
    const body=el('div','bbody');
    items.forEach(e=>body.appendChild(entryCard(e)));
    if(isOther) collapsibleOther(sec, body, !t);
    sec.appendChild(body);
    main.appendChild(sec);
    shown+=items.length;
  }
  if(!shown){
    const msg = t ? 'No submissions match &ldquo;'+esc(term)+'&rdquo; this week.'
                  : (inProgress(w) ? 'No submissions yet &mdash; this week is still in progress.'
                                   : 'No submissions recorded for this week.');
    main.appendChild(el('p','empty',msg));
  }
  typesetMath(main);
}

let current=0;
let openYears=null;                       // Set of expanded years; null => init
let viewAll=false;                        // main panel showing combined results?
let lastWeek=0;                           // week to restore when search is cleared
let searchTimer=null;                     // debounce timer for cross-week search
let searchScope='recent';                 // cross-week search window: 'recent'|'all'
const WINDOW_MONTHS=12;                    // size of the 'recent' window
const yearOf = w => w.monday.slice(0,4);
const lc = s => (s||'').trim().toLowerCase();

// Cross-week search is windowed so the download and combined render stay bounded
// as the archive grows: by default only weeks within the last WINDOW_MONTHS are
// loaded and aggregated; "include older weeks" widens the scope to the full
// archive. Until the archive exceeds the window there are no older weeks, so this
// is a no-op and everything behaves as a plain all-weeks search.
function scopeCutoff(){ const d=new Date(); d.setMonth(d.getMonth()-WINDOW_MONTHS);
  return d.toISOString().slice(0,10); }
function inScope(w){ return searchScope==='all' || w.monday>=scopeCutoff(); }
function scopeIndices(){ const o=[]; D.weeks.forEach((w,i)=>{ if(inScope(w)) o.push(i); }); return o; }
function olderCount(){ const c=scopeCutoff(); return D.weeks.filter(w=>w.monday<c).length; }
function scopeLoaded(){ return scopeIndices().every(i=>(window.DIGEST_WEEKS||{})[D.weeks[i].monday]); }

// Filtered per-bucket counts for a *loaded* week, or null if not loaded yet.
// `t` is already trimmed + lowercased.
function filteredCounts(monday, t){
  const wk=(window.DIGEST_WEEKS||{})[monday];
  if(!wk) return null;
  const c={coauthor:0,high:0,medium:0,other:0,total:0};
  for(const e of wk.entries){
    if(!entryMatches(e,t)) continue;
    c[(e.bucket in c)?e.bucket:'other']++;
    c.total++;
  }
  return c;
}

// Badge markup shared by week links and the "All weeks" entry. With a term we show
// coauthor★ / high / medium / other (nonzero only); without, the static layout.
function badgesHTML(c, term){
  if(!lc(term)){
    return (c.coauthor?'<span class="b coauthor">★'+c.coauthor+'</span>':'')+
           (c.high?'<span class="b high">'+c.high+'</span>':'')+
           '<span class="b tot">'+c.total+'</span>';
  }
  return (c.coauthor?'<span class="b coauthor">★'+c.coauthor+'</span>':'')+
         (c.high  ?'<span class="b high">'  +c.high  +'</span>':'')+
         (c.medium?'<span class="b medium">'+c.medium+'</span>':'')+
         (c.other ?'<span class="b other">' +c.other +'</span>':'');
}

function weekLink(i, term){
  const w=D.weeks[i];
  const t=lc(term);
  const a=el('a','weeklink'+(!viewAll&&i===current?' active':''));
  a.href='#';
  let badges;
  if(!t){                                       // static index counts
    badges=badgesHTML(w.counts, '');
  }else if(!inScope(w)){                         // outside the search window
    badges='<span class="b tot">'+w.counts.total+'</span>';
    a.classList.add('outofscope');
  }else{
    const fc=filteredCounts(w.monday, t);
    if(!fc){                                    // term active, week not loaded yet
      badges='<span class="b loading">&hellip;</span>';
      a.classList.add('pending');
    }else{
      badges=badgesHTML(fc, term);
      if(!fc.total && i!==current) a.classList.add('nomatch');
    }
  }
  a.innerHTML='<span class="wr">'+fmtRange(w)+(inProgress(w)?' <span class="dot" title="in progress">●</span>':'')+'</span>'+
    '<span class="badges">'+badges+'</span>';
  a.addEventListener('click',ev=>{ev.preventDefault();selectWeek(i, $('#filter').value);});
  return a;
}

function renderNav(term){
  renderAllEntry(term);
  const nav=$('#weekList'); nav.innerHTML='';
  const t=lc(term);
  // group week indices by year, preserving the newest-first order of D.weeks
  const order=[], byYear={};
  D.weeks.forEach((w,i)=>{
    const y=yearOf(w);
    if(!(y in byYear)){ byYear[y]=[]; order.push(y); }
    byYear[y].push(i);
  });
  if(openYears===null){               // default: only the most recent year open
    openYears=new Set(order.length?[order[0]]:[]);
  }
  openYears.add(yearOf(D.weeks[current]));   // keep the active week's year open
  order.forEach(y=>{
    const items=byYear[y];
    const open=openYears.has(y);
    const coAll=items.reduce((s,i)=>s+D.weeks[i].counts.coauthor,0);
    // during search, show this year's total hits once all its weeks are loaded
    let yearHits=null;
    if(t){
      yearHits=0;
      for(const i of items){ const fc=filteredCounts(D.weeks[i].monday,t);
        if(fc) yearHits+=fc.total; else { yearHits=null; break; } }
    }
    const head=el('button','yearhead'+(open?' open':''));
    const meta=(yearHits!=null)? items.length+' wk · <span class="hits">'+yearHits+' hit'+(yearHits===1?'':'s')+'</span>'
                               : items.length+' wk'+(coAll?' · <span class="co">★'+coAll+'</span>':'');
    head.innerHTML='<span><span class="caret">'+(open?'▾':'▸')+'</span> '+y+'</span>'+
      '<span class="ymeta">'+meta+'</span>';
    head.addEventListener('click',()=>{ openYears.has(y)?openYears.delete(y):openYears.add(y); renderNav(term); });
    nav.appendChild(head);
    if(open){
      const grp=el('div','yearweeks');
      items.forEach(i=>grp.appendChild(weekLink(i,term)));
      nav.appendChild(grp);
    }
  });
}

// Sidebar "All weeks" entry: aggregated hit counts across all loaded weeks. Only
// shown while a search term is active; clicking shows the combined results.
function renderAllEntry(term){
  const box=$('#allResults'); box.innerHTML='';
  const t=lc(term);
  if(!t) return;
  const c={coauthor:0,high:0,medium:0,other:0,total:0};
  scopeIndices().forEach(i=>{ const fc=filteredCounts(D.weeks[i].monday,t);
    if(fc) for(const k in c) c[k]+=fc[k]; });
  const scoped=(searchScope==='recent' && olderCount()>0);
  const a=el('a','weeklink allweeks'+(viewAll?' active':''));
  a.href='#';
  a.innerHTML='<span class="wr">'+(scoped?'Recent weeks':'All weeks')+'</span>'+
    '<span class="badges">'+badgesHTML(c, term)+'</span>';
  a.addEventListener('click',ev=>{ev.preventDefault();selectAll($('#filter').value);});
  box.appendChild(a);
}

// Lazy-load a week's full entries (injected <script>, works from file:// in
// most browsers). The week file populates window.DIGEST_WEEKS["<monday>"].
function loadWeek(mon, cb, err){
  const store=window.DIGEST_WEEKS||(window.DIGEST_WEEKS={});
  if(store[mon]) return cb(store[mon]);
  const s=document.createElement('script');
  s.src='data/week-'+mon+'.js';
  s.onload=()=>{ const d=(window.DIGEST_WEEKS||{})[mon]; d?cb(d):(err&&err()); };
  s.onerror=()=>err&&err();
  document.head.appendChild(s);
}

// Load the full data for every in-scope week (reusing loadWeek). Each settle (ok
// or fail) triggers refreshSearch, which re-renders from live state — so it's safe
// to call repeatedly (e.g. when the scope widens) and late arrivals can never
// apply stale results. Failures still settle so it never hangs; cached/in-flight
// weeks are skipped.
const loadingWeeks=new Set();
function loadScope(){
  scopeIndices().forEach(i=>{ const m=D.weeks[i].monday;
    if((window.DIGEST_WEEKS||{})[m] || loadingWeeks.has(m)) return;
    loadingWeeks.add(m);
    const fin=()=>{ loadingWeeks.delete(m); refreshSearch(); };
    loadWeek(m, fin, fin);
  });
}

// Re-render the combined view + sidebar from the current term/scope. Single source
// of truth for the "searching…" caption: visible iff a combined search is showing
// and its in-scope weeks aren't all loaded yet.
function refreshSearch(){
  const term=$('#filter').value;
  if(!viewAll || !lc(term)){ $('#searchStat').hidden=true; return; }
  $('#searchStat').hidden=scopeLoaded();
  renderNav(term); renderAllResults(term);
}

function selectWeek(i, term, scroll){
  current=i; viewAll=false; $('#searchStat').hidden=true; renderNav(term);
  const w=D.weeks[i], main=$('#main');
  if(!(window.DIGEST_WEEKS||{})[w.monday]) main.innerHTML='<p class="empty">Loading&hellip;</p>';
  loadWeek(w.monday,
    full=>renderWeek(full, $('#filter').value),
    ()=>{ main.innerHTML='<p class="empty">Couldn\'t load <code>data/week-'+w.monday+'.js</code>. '+
      'If you opened this page directly from disk, your browser may be blocking local data files &mdash; '+
      'serve the folder instead: <code>python3 -m http.server --directory site</code></p>'; });
  if(scroll!==false) window.scrollTo(0,0);
}

// Combined view: every matching entry across all loaded weeks, grouped by bucket,
// each card tagged with its week (click to open that week).
function renderAllResults(term){
  const main=$('#main'); main.innerHTML='';
  const t=lc(term);
  const loading=!scopeLoaded();
  const scoped=(searchScope==='recent' && olderCount()>0);
  // gather matches per bucket from loaded in-scope weeks, newest-first
  const hits={}; let total=0, weeksWith=0;
  BUCKETS.forEach(b=>hits[b.key]=[]);
  scopeIndices().forEach(i=>{
    const w=D.weeks[i], wk=(window.DIGEST_WEEKS||{})[w.monday];
    if(!wk) return;
    let any=false;
    wk.entries.forEach(e=>{ if(!entryMatches(e,t)) return;
      (hits[e.bucket]||hits.other).push({e, i, w}); total++; any=true; });
    if(any) weeksWith++;
  });
  const head=el('div','weekhead');
  head.innerHTML='<h2>'+(scoped?'Recent weeks':'All weeks')+(loading?' <span class="tag-prog">loading…</span>':'')+'</h2>'+
    '<p class="wstats">'+total+' submission'+(total===1?'':'s')+' matching &ldquo;'+esc(term)+'&rdquo;'+
    ' across '+weeksWith+' week'+(weeksWith===1?'':'s')+
    (scoped?' &middot; last '+WINDOW_MONTHS+' months':'')+'</p>';
  main.appendChild(head);
  let shown=0;
  for(const b of BUCKETS){
    const items=hits[b.key];
    if(!items.length) continue;
    const sec=el('section','bucket '+b.cls);
    const isOther=b.key==='other';
    sec.innerHTML='<h3 class="bhead'+(isOther?' collapsible':'')+'">'+b.label+' <span class="ct">'+items.length+'</span></h3>';
    const body=el('div','bbody');
    items.forEach(({e,i,w})=>{
      const card=entryCard(e);
      const tag=el('a','entry-week'); tag.href='#'; tag.textContent=fmtRange(w);
      tag.addEventListener('click',ev=>{ev.preventDefault();selectWeek(i, $('#filter').value);});
      card.insertBefore(tag, card.firstChild);
      body.appendChild(card);
    });
    if(isOther) collapsibleOther(sec, body, true);
    sec.appendChild(body); main.appendChild(sec); shown+=items.length;
  }
  if(!shown) main.appendChild(el('p','empty',loading?'Searching weeks&hellip;':
    'No submissions match &ldquo;'+esc(term)+'&rdquo;.'));
  if(scoped){
    const n=olderCount();
    const btn=el('button','loadmore','Include '+n+' older week'+(n===1?'':'s'));
    btn.addEventListener('click',expandScope);
    main.appendChild(btn);
  }
  typesetMath(main);
}

function selectAll(term){
  viewAll=true; renderNav(term); renderAllResults(term);
  $('#searchStat').hidden = !lc(term) || scopeLoaded();
  loadScope();                              // fetch any missing in-scope weeks
  window.scrollTo(0,0);
}

// Widen the combined search to the full archive, loading older weeks on demand.
function expandScope(){ searchScope='all'; selectAll($('#filter').value); }

// Debounced cross-week search. The combined "All weeks" view is the default while
// a term is active; per-week sidebar badges update once data is loaded.
function onSearchInput(raw){
  clearTimeout(searchTimer);
  const t=(raw||'').trim();
  if(!t){                                   // cleared: revert to the last week view
    viewAll=false; searchScope='recent';
    $('#searchStat').hidden=true;
    selectWeek(lastWeek,'',false);
    return;
  }
  if(!viewAll) lastWeek=current;            // remember where we came from
  searchTimer=setTimeout(()=>selectAll(raw), 200);
}

function init(){
  const ol=$('#ownerLink'); ol.textContent=D.owner; ol.href=D.profile_url;
  $('#genStamp').textContent='Generated '+new Date(D.generated_at).toLocaleString('en-GB')+
    ' · '+D.weeks.length+' week(s) archived';
  if(!D.weeks.length){ $('#main').innerHTML='<p class="empty">No digests yet.</p>'; return; }
  renderNav('');
  selectWeek(0,'',false);
  $('#filter').addEventListener('input',e=>onSearchInput(e.target.value));
}
init();
</script>
</body>
</html>
"""


STYLE_CSS = r""":root{
  --bg:#0f1115; --panel:#171a21; --panel2:#1d2129; --ink:#e7e9ee; --mut:#9aa3b2;
  --line:#272c36; --accent:#6ea8fe; --co:#ffcf5c; --hi:#67d99b; --med:#8fb6ff;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
header{background:linear-gradient(180deg,#191d26,#12151c);border-bottom:1px solid var(--line);padding:26px 0 20px}
header h1{margin:0 0 6px;font-size:25px;letter-spacing:.2px}
header .sub{margin:0;color:var(--mut);max-width:820px}
.layout{display:grid;grid-template-columns:300px 1fr;gap:26px;padding-top:24px;padding-bottom:60px;align-items:start}
#sidebar{position:sticky;top:18px}
.search input{width:100%;padding:9px 11px;border-radius:9px;border:1px solid var(--line);
  background:var(--panel);color:var(--ink);font-size:14px}
.searchstat{margin:6px 2px 0;font-size:11.5px;color:var(--mut)}
#sidebar h2{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--mut);margin:18px 0 8px}
.yearhead{width:100%;display:flex;justify-content:space-between;align-items:center;
  background:transparent;border:none;color:var(--ink);cursor:pointer;
  padding:7px 4px;margin-top:6px;font-size:13.5px;font-weight:600;letter-spacing:.02em}
.yearhead:hover{color:var(--accent)}
.yearhead .caret{display:inline-block;width:12px;color:var(--mut);font-size:11px}
.yearhead .ymeta{font-size:11.5px;font-weight:400;color:var(--mut)}
.yearhead .ymeta .co{color:var(--co)}
.yearhead .ymeta .hits{color:var(--accent)}
.yearweeks{margin-bottom:4px}
.weeklink{display:flex;justify-content:space-between;align-items:center;gap:8px;
  padding:9px 11px;border:1px solid var(--line);border-radius:9px;margin-bottom:7px;background:var(--panel);color:var(--ink)}
.weeklink:hover{border-color:#37414f;text-decoration:none}
.weeklink.active{border-color:var(--accent);background:var(--panel2)}
.weeklink.nomatch{opacity:.42}
.weeklink.nomatch:hover{opacity:.7}
.weeklink.outofscope{opacity:.5}
.weeklink.outofscope:hover{opacity:.8}
.weeklink.pending .badges{opacity:.6}
.weeklink.allweeks{margin-top:6px;border-color:var(--accent)}
.weeklink.allweeks .wr{font-weight:600}
.weeklink .wr{font-size:13.5px}
.badges{display:flex;gap:5px;flex-shrink:0}
.b{font-size:11px;padding:1px 7px;border-radius:20px;background:#2a3140;color:var(--mut)}
.b.tot{background:#2a3140}
.b.high{background:rgba(103,217,155,.16);color:var(--hi)}
.b.medium{background:rgba(143,182,255,.16);color:var(--med)}
.b.other{background:#2a3140;color:var(--mut)}
.b.loading{background:#2a3140;color:var(--mut);opacity:.7}
.b.coauthor{background:rgba(255,207,92,.18);color:var(--co)}
.legend{margin-top:14px;display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:11px;padding:2px 9px;border-radius:20px}
.chip.coauthor{background:rgba(255,207,92,.18);color:var(--co)}
.chip.high{background:rgba(103,217,155,.16);color:var(--hi)}
.chip.medium{background:rgba(143,182,255,.16);color:var(--med)}
.foot{color:var(--mut);font-size:11.5px;margin-top:16px}
.weekhead h2{margin:0 0 2px;font-size:21px}
.wstats{margin:0 0 18px;color:var(--mut);font-size:13.5px}
.wstats .hl{color:var(--co);font-weight:600}
.tag-prog{font-size:12px;vertical-align:middle;background:rgba(110,168,254,.18);color:var(--accent);
  padding:2px 9px;border-radius:20px;letter-spacing:.04em;text-transform:uppercase}
.progress{margin:0 0 18px;padding:9px 13px;border:1px solid rgba(110,168,254,.4);
  border-radius:9px;background:rgba(110,168,254,.08);color:#bcd2ff;font-size:13px}
.progress::first-letter{color:var(--accent)}
.weeklink .dot{color:var(--accent);font-size:10px;vertical-align:middle}
.bucket{margin-bottom:26px}
.bhead{font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--mut);
  border-bottom:1px solid var(--line);padding-bottom:6px;margin:0 0 14px;display:flex;align-items:center;gap:8px}
.bhead .ct{background:#2a3140;color:var(--mut);font-size:11px;padding:0 8px;border-radius:20px;letter-spacing:0}
.bhead.collapsible{cursor:pointer}
.bhead.collapsible:hover{color:var(--ink)}
.bbody.hidden{display:none}
.bucket.coauthor .bhead{color:var(--co)}
.bucket.high .bhead{color:var(--hi)}
.entry{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:15px 17px;margin-bottom:12px}
.entry.b-coauthor{border-color:rgba(255,207,92,.55);background:linear-gradient(180deg,rgba(255,207,92,.06),var(--panel))}
.entry.b-high{border-left:3px solid var(--hi)}
.cobanner,.cobanner.co{display:none}
.cobanner{display:block;color:var(--co);font-weight:600;font-size:12.5px;margin-bottom:6px}
.entry h3{margin:0 0 6px;font-size:16px;line-height:1.4}
.authors{color:var(--mut);font-size:13.5px;margin-bottom:8px}
.authors .co{color:var(--co)}
.meta{font-size:12px;color:var(--mut);display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px}
.cat{background:#252b36;padding:1px 7px;border-radius:5px;font-size:11px}
.cat.prim{background:rgba(110,168,254,.18);color:var(--accent)}
.idlink{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px}
.abs summary{cursor:pointer;color:var(--mut);font-size:13px;outline:none}
.abs summary:hover{color:var(--ink)}
.abs p{margin:8px 0 0;color:#c3c9d4;font-size:13.5px}
.entry-week{display:inline-block;margin-bottom:8px;font-size:11.5px;
  color:var(--mut);background:#222834;padding:1px 9px;border-radius:20px}
.entry-week:hover{color:var(--ink);text-decoration:none}
.loadmore{display:block;width:100%;margin:6px 0 0;padding:11px;border:1px dashed var(--line);
  border-radius:10px;background:var(--panel);color:var(--accent);cursor:pointer;font-size:13.5px}
.loadmore:hover{border-color:var(--accent);background:var(--panel2)}
.kws{margin-top:9px;display:flex;flex-wrap:wrap;gap:5px}
.kw{font-size:11px;background:#222834;color:#9fb4d8;padding:1px 8px;border-radius:20px}
.empty{color:var(--mut);padding:30px 0}
@media(max-width:820px){.layout{grid-template-columns:1fr}#sidebar{position:static}}
"""


if __name__ == "__main__":
    build()
