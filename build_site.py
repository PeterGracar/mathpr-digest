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
import hashlib
import json
import os
import re
import subprocess
import unicodedata
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


def _norm(s):
    """Lowercase + strip accents — mirrors norm() in generate_digest.py."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def _mark_own(week):
    """Flag entries authored by config.OWNER and lift them into the 'own'
    bucket. New weeks arrive already flagged by score_entry(); finalized week
    JSONs are frozen, so older cached weeks are upgraded here at build time
    (in memory only — data/ is never rewritten)."""
    op = _norm(config.OWNER).split()
    for e in week.get("entries", []):
        if "own" not in e:
            e["own"] = any(op[-1] in an and op[0] in an
                           for an in (_norm(a) for a in e["authors"]))
        if e["own"]:
            e["bucket"] = "own"


def _counts(week):
    c = {"own": 0, "coauthor": 0, "high": 0, "medium": 0, "other": 0}
    for e in week["entries"]:
        c[e.get("bucket", "other")] = c.get(e.get("bucket", "other"), 0) + 1
    c["total"] = len(week["entries"])
    return c


def _fetch_site_chrome():
    """Mirror gracar.org's rendered header and footer verbatim (links, text,
    future edits included) so the digest page always matches the homepage.
    Uses the curl CLI like generate_digest (the bundled Python has no CA
    bundle); root-relative hrefs are made absolute. On any failure the baked
    snapshot at the bottom of this file is used instead."""
    try:
        html = subprocess.run(
            ["curl", "-sS", "-m", "30", "https://gracar.org/"],
            capture_output=True, text=True, check=True).stdout
        h = re.search(r'<header class="site-header">.*?</header>', html, re.S)
        f = re.search(r'<footer class="site-footer">.*?</footer>', html, re.S)
        if not h or not f:
            raise ValueError("site chrome not found in homepage HTML")
        def absolutize(s):
            return re.sub(r'\b(href|src)="/', r'\1="https://gracar.org/', s)
        return absolutize(h.group(0)), absolutize(f.group(0))
    except Exception as e:
        print(f"  ! could not mirror gracar.org chrome ({e}); using baked snapshot")
        return SITE_HEADER_FALLBACK, SITE_FOOTER_FALLBACK


def build(weeks=None):
    if weeks is None:
        weeks = load_all_weeks()
    # newest first
    weeks = sorted(weeks, key=lambda w: w["monday"], reverse=True)
    # Only surface weeks that actually have content. A brand-new week opens empty
    # — arXiv announces a week's first submissions ~a day after it starts (its
    # Monday papers land in the next run) — so it shouldn't appear in the UI (nav,
    # index, or a lazy data file) until it has at least one entry.
    weeks = [w for w in weeks if w.get("entries")]
    for w in weeks:
        _mark_own(w)
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
        "back_url": config.BACK_URL,
        "back_label": config.BACK_LABEL,
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

    header, footer = _fetch_site_chrome()
    css_v = hashlib.md5(STYLE_CSS.encode()).hexdigest()[:8]
    with open(os.path.join(SITE_DIR, "index.html"), "w") as f:
        f.write(INDEX_HTML.replace("__SITE_HEADER__", header)
                          .replace("__SITE_FOOTER__", footer)
                          .replace("__CSS_V__", css_v))
    with open(os.path.join(SITE_DIR, "style.css"), "w") as f:
        f.write(STYLE_CSS)
    print(f"  site built: {len(weeks)} week(s), lazy-loaded "
          f"-> {SITE_DIR}/index.html")


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#f8f4ee" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#111216" media="(prefers-color-scheme: dark)">
<title>math.PR Weekly Digest &middot; Peter Gracar</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,700&family=Source+Sans+3:wght@400;600;700&display=swap">
<link rel="stylesheet" href="https://gracar.org/style.css">
<link rel="stylesheet" href="style.css?v=__CSS_V__">
<script src="https://gracar.org/site.js" defer></script>
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
<a class="skip-link" href="#main">Skip to content</a>
__SITE_HEADER__

<div class="wrap page-intro">
  <h1>math.PR weekly digest</h1>
  <p class="reading-width">New submissions to <a href="https://arxiv.org/list/math.PR/recent" target="_blank" rel="noopener">arXiv math.PR</a>,
     curated for <a id="ownerLink" href="#" target="_blank" rel="noopener"></a>'s research interests
     &mdash; random geometric graphs, percolation, particle systems, and the spread of infection.</p>
</div>

<div class="layout wrap">
  <aside id="sidebar">
    <div class="search"><input id="filter" type="search" placeholder="Filter titles / authors / keywords&hellip;"></div>
    <p class="searchstat" id="searchStat" hidden>searching all weeks&hellip;</p>
    <div id="allResults"></div>
    <h2>Digests</h2>
    <nav id="weekList"></nav>
    <div class="legend">
      <span class="chip own">own paper</span>
      <span class="chip coauthor">coauthor</span>
      <span class="chip high">highly relevant</span>
      <span class="chip medium">possibly relevant</span>
    </div>
    <p class="foot" id="genStamp"></p>
  </aside>

  <main id="main"></main>
</div>

__SITE_FOOTER__

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
  {key:"own",      label:"Own papers",           cls:"own"},
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

// Author names carry diacritics ('Mönch') while config.COAUTHORS is ASCII
// ('Monch'), so fold both before comparing — mirrors norm() in generate_digest.py.
const fold = s => (s||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
// Same first+last rule as score_entry(), so the bolding can't disagree with the
// coauthor list the generator produced.
function isCoauthor(a, ca){
  const p=fold(ca).split(/\s+/), f=fold(a);
  return f.includes(p[0]) && f.includes(p[p.length-1]);
}
// Banner names: prefer the paper's own spelling ('Mönch') over the ASCII config
// entry, falling back to the config name when no author matched.
const coauthorNames = e => (e.coauthors||[]).map(ca=>(e.authors||[]).find(a=>isCoauthor(a,ca))||ca);
// The owner's own name uses the same first+last rule.
const isOwner = a => isCoauthor(a, D.owner||'');

function authorsHTML(e){
  const cos=e.coauthors||[];
  return e.authors.map(a=>
    isOwner(a)? '<strong class="own">'+esc(a)+'</strong>' :
    cos.some(ca=>isCoauthor(a,ca))? '<strong class="co">'+esc(a)+'</strong>' : esc(a)
  ).join(', ');
}

function entryCard(e){
  const card=el('article','entry b-'+e.bucket);
  const cats=e.categories.map(c=>'<span class="cat'+(c===e.primary_category?' prim':'')+'">'+esc(c)+'</span>').join('');
  const kws=(e.matched_keywords||[]).slice(0,8).map(k=>'<span class="kw">'+esc(k)+'</span>').join('');
  const own=e.own?'<div class="ownbanner">✦ Own paper</div>':'';
  const co=(e.coauthors&&e.coauthors.length)?'<div class="cobanner">★ Coauthor: '+coauthorNames(e).map(esc).join(', ')+'</div>':'';
  card.innerHTML =
    own+co+
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
// folded by the caller (use lc()), so 'monch' finds 'Mönch' and vice versa.
// The folded haystack is cached per entry — it is rebuilt on every keystroke
// across every in-scope week otherwise, and normalize() over whole abstracts is
// the expensive part.
function entryMatches(e, t){
  if(e._hay===undefined) e._hay=fold(e.title+' '+e.authors.join(' ')+' '+
                                     (e.matched_keywords||[]).join(' ')+' '+e.abstract);
  return e._hay.includes(t);
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
  const ownN=w.entries.filter(e=>e.bucket==='own').length;
  const coN=w.entries.filter(e=>e.bucket==='coauthor').length;
  head.innerHTML='<h2>'+fmtRange(w)+(inProgress(w)?' <span class="tag-prog">in progress</span>':'')+'</h2>'+
    '<p class="wstats">'+w.entries.length+(inProgress(w)?' submissions so far':' new submissions')+' to '+esc(w.category)+
    ' &middot; ISO week '+w.iso_year+'-W'+String(w.iso_week).padStart(2,'0')+
    (ownN?' &middot; <span class="hlown">'+ownN+' own</span>':'')+
    (coN?' &middot; <span class="hl">'+coN+' coauthor</span>':'')+'</p>'+
    (inProgress(w)?'<div class="progress">● Partial week — data through '+fmtDay(w.data_through)+
      '. This digest updates automatically on each run until the week closes.</div>':'');
  main.appendChild(head);

  const t=lc(term);
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
const lc = s => fold(s).trim();           // normalise a search term (folds accents)

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
  const c={own:0,coauthor:0,high:0,medium:0,other:0,total:0};
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
    return (c.own?'<span class="b own">✦'+c.own+'</span>':'')+
           (c.coauthor?'<span class="b coauthor">★'+c.coauthor+'</span>':'')+
           (c.high?'<span class="b high">'+c.high+'</span>':'')+
           '<span class="b tot">'+c.total+'</span>';
  }
  return (c.own?'<span class="b own">✦'+c.own+'</span>':'')+
         (c.coauthor?'<span class="b coauthor">★'+c.coauthor+'</span>':'')+
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
    const ownAll=items.reduce((s,i)=>s+(D.weeks[i].counts.own||0),0);
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
                               : items.length+' wk'+(ownAll?' · <span class="own">✦'+ownAll+'</span>':'')+
                                 (coAll?' · <span class="co">★'+coAll+'</span>':'');
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
  const c={own:0,coauthor:0,high:0,medium:0,other:0,total:0};
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


STYLE_CSS = r"""/* Digest-specific overlay on the live gracar.org stylesheet, which is
   linked first in index.html. Tokens (--color-*, --text-*, fonts, radii,
   shadows), the link-underline system, the header/nav/footer chrome and the
   system-driven light/dark switch are all inherited from there, so restyling
   the homepage restyles this page too. This file owns only the digest's
   bucket hues, layout, and components. */
:root{ --own:#950000; --co:#e65100; --hi:#2e7d32; --med:#1565c0 }
@media(prefers-color-scheme:dark){:root{ --own:#ff9f87; --co:#ffab40; --hi:#69f0ae; --med:#64b5f6 }}
body{font-size:var(--text-sm)}
.weeklink,.entry-week{background-image:none}
summary:focus-visible,input:focus-visible{outline:3px solid var(--color-focus);outline-offset:3px}
/* body is the site's flex column, so auto margins alone would shrink-to-fit;
   size .wrap exactly like the site sizes main */
.wrap{width:min(100% - 2rem,var(--site-max-width));margin:0 auto}
/* fallback shade if the hotlinked banner.webp fails to load (the site's
   background shorthand resets background-color, so this later rule wins) */
.site-header{background-color:#2b1310}
.page-intro{margin-top:clamp(1.5rem,3vw,2.4rem)}
/* #main is a grid cell here, not the site's centred prose column */
#main{flex:none;width:auto;margin:0;padding:0}
.layout{display:grid;grid-template-columns:320px 1fr;gap:1.6rem;padding-top:1.5rem;padding-bottom:3.5rem;align-items:start}
#sidebar{position:sticky;top:1rem}
.search input{width:100%;padding:.55rem .7rem;border-radius:var(--radius-md);border:1px solid var(--color-border);
  background:var(--color-surface);color:var(--color-text);font:400 var(--text-sm)/1.4 var(--font-body)}
.searchstat{margin:.35rem .15rem 0;font-size:var(--text-xs);color:var(--color-text-muted)}
#sidebar h2{font:600 var(--text-xs)/1.2 var(--font-body);text-transform:uppercase;letter-spacing:.08em;
  color:var(--color-text-muted);margin:1.2rem 0 .5rem}
.yearhead{width:100%;display:flex;justify-content:space-between;align-items:center;
  background:transparent;border:none;color:var(--color-text);cursor:pointer;
  padding:.45rem .25rem;margin-top:.4rem;font:600 var(--text-sm)/1.3 var(--font-body);letter-spacing:.02em}
.yearhead:hover{color:var(--color-accent)}
.yearhead .caret{display:inline-block;width:12px;color:var(--color-text-muted);font-size:var(--text-xs)}
.yearhead .ymeta{font-size:var(--text-xs);font-weight:400;color:var(--color-text-muted)}
.yearhead .ymeta .own{color:var(--own)}
.yearhead .ymeta .co{color:var(--co)}
.yearhead .ymeta .hits{color:var(--color-accent)}
.yearweeks{margin-bottom:.3rem}
.weeklink{display:flex;justify-content:space-between;align-items:center;gap:.5rem;
  padding:.55rem .7rem;border:1px solid var(--color-border);border-radius:var(--radius-md);
  margin-bottom:.45rem;background:var(--color-surface);color:var(--color-text)}
.weeklink:hover{border-color:var(--color-accent-soft)}
.weeklink.active{border-color:var(--color-accent);background:var(--color-surface-soft)}
.weeklink.nomatch{opacity:.42}
.weeklink.nomatch:hover{opacity:.7}
.weeklink.outofscope{opacity:.5}
.weeklink.outofscope:hover{opacity:.8}
.weeklink.pending .badges{opacity:.6}
.weeklink.allweeks{margin-top:.4rem;border-color:var(--color-accent)}
.weeklink.allweeks .wr{font-weight:600}
.weeklink .wr{font-size:var(--text-sm)}
.badges{display:flex;gap:4px;flex-shrink:0}
.b{font-size:var(--text-xs);font-weight:600;padding:.05rem .4rem;border-radius:999px;
  background:var(--color-surface-soft);color:var(--color-text-muted)}
.b.high{background:color-mix(in srgb,var(--hi) 14%,transparent);color:var(--hi)}
.b.medium{background:color-mix(in srgb,var(--med) 14%,transparent);color:var(--med)}
.b.loading{opacity:.7}
.b.coauthor{background:color-mix(in srgb,var(--co) 15%,transparent);color:var(--co)}
.b.own{background:color-mix(in srgb,var(--own) 14%,transparent);color:var(--own)}
.legend{margin-top:.9rem;display:flex;flex-wrap:wrap;gap:.35rem}
.chip{font-size:var(--text-xs);font-weight:600;padding:.1rem .55rem;border-radius:999px}
.chip.own{background:color-mix(in srgb,var(--own) 14%,transparent);color:var(--own)}
.chip.coauthor{background:color-mix(in srgb,var(--co) 15%,transparent);color:var(--co)}
.chip.high{background:color-mix(in srgb,var(--hi) 14%,transparent);color:var(--hi)}
.chip.medium{background:color-mix(in srgb,var(--med) 14%,transparent);color:var(--med)}
.weekhead h2{margin:0 0 .15rem;color:var(--color-text);font:700 var(--text-lg)/1.2 var(--font-heading);letter-spacing:.01em}
.wstats{margin:0 0 1.1rem;color:var(--color-text-muted);font-size:var(--text-sm)}
.wstats .hl{color:var(--co);font-weight:600}
.wstats .hlown{color:var(--own);font-weight:600}
.tag-prog{font-size:var(--text-xs);font-weight:600;vertical-align:middle;
  background:color-mix(in srgb,var(--color-accent) 14%,transparent);color:var(--color-accent);
  padding:.1rem .55rem;border-radius:999px;letter-spacing:.04em;text-transform:uppercase}
.progress{margin:0 0 1.1rem;padding:.55rem .8rem;border:1px solid color-mix(in srgb,var(--color-accent) 40%,transparent);
  border-radius:var(--radius-md);background:color-mix(in srgb,var(--color-accent) 8%,transparent);
  color:var(--color-text);font-size:var(--text-sm)}
.progress::first-letter{color:var(--color-accent)}
.weeklink .dot{color:var(--color-accent);font-size:10px;vertical-align:middle}
.bucket{margin-bottom:1.6rem}
.bhead{font:600 var(--text-xs)/1.3 var(--font-body);text-transform:uppercase;letter-spacing:.08em;
  color:var(--color-text-muted);border-bottom:1px solid var(--color-border);
  padding-bottom:.4rem;margin:0 0 .9rem;display:flex;align-items:center;gap:.5rem}
.bhead .ct{background:var(--color-surface-soft);color:var(--color-text-muted);font-size:var(--text-xs);
  padding:0 .5rem;border-radius:999px;letter-spacing:0}
.bhead.collapsible{cursor:pointer}
.bhead.collapsible:hover{color:var(--color-text)}
.bbody.hidden{display:none}
.bucket.own .bhead{color:var(--own)}
.bucket.coauthor .bhead{color:var(--co)}
.bucket.high .bhead{color:var(--hi)}
.entry{background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-lg);
  box-shadow:var(--shadow-card);padding:clamp(.9rem,1.8vw,1.2rem);margin-bottom:.8rem}
.entry.b-coauthor{border-color:color-mix(in srgb,var(--co) 45%,transparent);
  background:linear-gradient(180deg,color-mix(in srgb,var(--co) 8%,var(--color-surface)),var(--color-surface))}
.entry.b-own{border-color:color-mix(in srgb,var(--own) 50%,transparent);
  background:linear-gradient(180deg,color-mix(in srgb,var(--own) 8%,var(--color-surface)),var(--color-surface))}
.entry.b-high{border-left:3px solid var(--hi)}
.cobanner{color:var(--co);font-weight:600;font-size:var(--text-xs);margin-bottom:.35rem}
.ownbanner{color:var(--own);font-weight:600;font-size:var(--text-xs);margin-bottom:.35rem}
.entry h3{margin:0 0 .35rem;font:700 var(--text-base)/1.35 var(--font-heading);letter-spacing:.01em}
.authors{color:var(--color-text-muted);font-size:var(--text-sm);margin-bottom:.45rem}
.authors .co{color:var(--co)}
.authors .own{color:var(--own)}
.meta{font-size:var(--text-xs);color:var(--color-text-muted);display:flex;flex-wrap:wrap;gap:.35rem;align-items:center;margin-bottom:.45rem}
.cat{background:var(--color-surface-soft);padding:.05rem .5rem;border-radius:999px;font-size:var(--text-xs)}
.cat.prim{background:color-mix(in srgb,var(--color-accent) 14%,transparent);color:var(--color-accent)}
.idlink{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:var(--text-xs)}
.abs summary{cursor:pointer;color:var(--color-text-muted);font-size:var(--text-sm)}
.abs summary:hover{color:var(--color-text)}
.abs p{margin:.5rem 0 0;color:var(--color-text);font-size:var(--text-sm)}
.entry-week{display:inline-block;margin-bottom:.45rem;font-size:var(--text-xs);font-weight:600;
  color:var(--color-text-muted);background:var(--color-surface-soft);padding:.05rem .55rem;border-radius:999px}
.entry-week:hover{color:var(--color-accent)}
.loadmore{display:block;width:100%;margin:.4rem 0 0;padding:.7rem;border:1px dashed var(--color-border);
  border-radius:var(--radius-md);background:var(--color-surface);color:var(--color-accent);cursor:pointer;
  font:400 var(--text-sm)/1.4 var(--font-body)}
.loadmore:hover{border-color:var(--color-accent);background:var(--color-surface-soft)}
.kws{margin-top:.55rem;display:flex;flex-wrap:wrap;gap:.3rem}
.kw{font-size:var(--text-xs);font-weight:600;background:var(--color-surface-soft);color:var(--color-text-muted);
  padding:.05rem .5rem;border-radius:999px}
.empty{color:var(--color-text-muted);padding:1.8rem 0}
@media(max-width:820px){.layout{grid-template-columns:1fr}#sidebar{position:static}}
"""


# Baked snapshot of gracar.org's header/footer (links absolutized), used only
# when _fetch_site_chrome can't reach the live homepage. Refresh it if it has
# drifted noticeably from the site, but drift only ever shows offline.
SITE_HEADER_FALLBACK = r"""<header class="site-header">
    <div class="site-header-inner">
      <p class="site-kicker">University of Leeds · School of Mathematics</p>
      <p class="site-name"><a href="https://gracar.org/">Peter Gracar</a></p>
      <p class="site-tagline">Probability, random geometric graphs, dependent percolation, and related stochastic processes.</p>
    </div>
    <nav class="site-nav" aria-label="Primary">
      <ul>
        <li><a data-page-link="home" href="https://gracar.org/">About</a></li>
        <li><a data-page-link="research" href="https://gracar.org/research.html">Research</a></li>
        <li><a data-page-link="teaching" href="https://gracar.org/teaching.html">Teaching</a></li>
        <li><a data-page-link="contact" href="https://gracar.org/contact.html">Contact</a></li>
      </ul>
    </nav>
  </header>"""

SITE_FOOTER_FALLBACK = r"""<footer class="site-footer">
    <div class="site-footer-inner">
      <p>
        <button type="button" class="pride-toggle" data-pride-toggle hidden aria-pressed="true" title="Pride colours are on this June — toggle off">
          <span class="pride-flag" aria-hidden="true">🏳️‍🌈</span>
          <span class="pride-toggle-label">Pride colours</span>
        </button>
        <a href="https://eps.leeds.ac.uk/maths/staff/13156/dr-peter-gracar">Leeds profile</a> &middot;
        <a href="https://eps.leeds.ac.uk/maths">School of Mathematics</a> &middot;
        <a href="https://orcid.org/0000-0001-8340-8340">ORCiD</a> &middot;
        <a href="https://arxiv.org/a/gracar_p_1">arXiv</a>
      </p>
      <p><a class="secret-dot" href="https://gracar.org/secret.html" aria-label="Site index">&copy;</a> <span data-year></span> Peter Gracar &middot; University of Leeds</p>
    </div>
  </footer>"""


if __name__ == "__main__":
    build()
