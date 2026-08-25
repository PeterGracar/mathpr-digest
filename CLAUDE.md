# CLAUDE.md

Guidance for working in this repo. See `README.md` for the full project/operations
writeup; this file focuses on architecture and conventions that aren't obvious.

## What this is

An automated weekly digest of new arXiv **math.PR** submissions, scored against
Peter Gracar's research-interest keywords and coauthor list, rendered as a static
single-page site published to GitHub Pages.

## Pipeline

```
config.py ──▶ generate_digest.py ──▶ data/week-YYYY-MM-DD.json ──▶ build_site.py ──▶ site/
```

- **`config.py`** — coauthors, weighted relevance keywords, `HIGH_THRESHOLD` /
  `MED_THRESHOLD`, `FIRST_WEEK_MONDAY`, `FINALIZE_GRACE_DAYS`.
- **`generate_digest.py`** — fetches arXiv (via the `curl` CLI; bundled Python has
  no CA bundle), scores each entry, buckets it (`own` / `coauthor` / `high` /
  `medium` / `other`), and writes one JSON file per Mon–Sun ISO week to `data/`.
  Finalized week JSONs are frozen, so `build_site.py` re-derives the `own` flag
  from author lists at build time (`_mark_own`) for weeks cached before the
  bucket existed. Idempotent,
  self-backfilling, and re-fetches non-finalized weeks. Then calls `build_site.build`.
- **`build_site.py`** — reads `data/*.json` and emits the whole site.

## Key architectural facts

- **`site/` is generated and git-ignored.** It is rebuilt on every run and shipped
  as the GitHub Pages artifact — never committed. The recurring "Digest update"
  commits on `main` only touch `data/`. **Do not** commit `site/`; edit the
  generator instead.
- **All HTML, CSS, and browser JS live inside `build_site.py`** as the
  `INDEX_HTML` and `STYLE_CSS` raw-string constants. To change anything in the UI,
  edit those strings and re-run `python3 build_site.py`. There are no separate
  `.html` / `.css` / front-end `.js` source files.
- **Theming and chrome are inherited live from gracar.org.** `index.html`
  links `https://gracar.org/style.css` before the local stylesheet and loads
  `https://gracar.org/site.js` (footer year, June pride toggle), so palette,
  fonts, banner and the system-driven (`prefers-color-scheme`) light/dark
  switch follow the homepage automatically — the banner image resolves
  relative to the remote CSS, and GitHub Pages' ~10-min cache bounds
  propagation. The **header and footer markup are the homepage's own**:
  `build()` fetches https://gracar.org/ via curl, extracts the rendered
  `.site-header` / `.site-footer`, absolutizes their links, and injects them
  at the `__SITE_HEADER__` / `__SITE_FOOTER__` placeholders
  (`_fetch_site_chrome`, with baked snapshots at the bottom of the file as
  offline fallback) — so link/text edits on the homepage reach the digest on
  the next daily build, and there is no digest-specific back link. The local
  stylesheet is linked as `style.css?v=<md5 of STYLE_CSS>` so a redeploy can
  never pair new markup with a stale cached stylesheet. `STYLE_CSS` is only
  an overlay: the digest's bucket hues (`--own/--co/--hi/--med`), layout, and
  components, expressed in the site's tokens (`--color-*`, `--text-*`, radii,
  shadows). Don't re-add copies of site chrome rules or markup here; if a
  token the overlay consumes is renamed on gracar.org, this overlay must
  follow.
- **The site is lazy-loaded.** `site/index.js` (`window.DIGEST_INDEX`) holds only
  per-week summaries — dates + `counts {own, coauthor, high, medium, other, total}`,
  **no entries**. Full entries live in `site/data/week-<monday>.js`
  (`window.DIGEST_WEEKS["<monday>"]`), injected via `<script>` on demand. Keep the
  initial payload constant as weeks accumulate — don't bake entry text into the index.

## The browser app (inside `INDEX_HTML`)

Single source of truth for "does this entry match the search":
`entryMatches(e, t)` (title + authors + matched_keywords + abstract, lowercased).
Used by the per-week view, sidebar counts, and the combined view so they never drift.

Search behaviour (current status — all implemented and on `main`):

- **Cross-week search.** Typing a term switches the main panel to a combined
  **"All weeks"** view (`selectAll` → `renderAllResults`) aggregating matches across
  weeks, each result card tagged with its week. Clearing the search returns to the
  previously-viewed week (`lastWeek`). Input is debounced ~200 ms.
- **Dynamic sidebar counts.** While searching, each week's badges show filtered
  high / medium / other (+ coauthor★) counts (`filteredCounts` + `badgesHTML`);
  zero-match weeks dim; a sidebar "All weeks" entry shows the aggregate.
- **Month aggregation.** Inside an open year, weeks at least one month old fold
  into collapsible month sub-groups (`mergeCutoff` = previous 'YYYY-MM'; weeks
  with an older monday merge, so the current and previous month stay individual).
  Month headers reuse the year-header meta (`groupMeta`: week count + ✦/★, or
  aggregated hits during search, dimming at zero); the active week's month is
  held open like its year (`openMonths`).
- **Time-windowed scope (scalability).** The combined search defaults to the last
  `WINDOW_MONTHS` (12) — only in-scope week files are fetched (`loadScope`) and
  aggregated (`scopeIndices` / `inScope` / `scopeLoaded`). An "Include older weeks"
  button (`expandScope`) widens to the full archive on demand. Dormant until the
  archive exceeds a year (then `olderCount() > 0`).
- **Lazy MathJax.** The large collapsed "Everything else" bucket is tagged
  `tex2jax_ignore` and typeset only when expanded (`collapsibleOther`).
- **Loading caption.** The "searching…" caption is driven by `refreshSearch()` from
  live state (`scopeLoaded()`), not callback bookkeeping — late loads can't strand it.

Empty weeks (no data yet) show a context message via `inProgress(w)` rather than a
blank-term search miss.

## Build & verify

```bash
python3 build_site.py                                  # regenerate site/
python3 -m http.server 8731 --directory site           # preview
```

When changing the embedded JS, check syntax and (where possible) logic without a
browser:

```bash
# extract the app script and syntax-check it
python3 - <<'PY'
import re; html=open('site/index.html').read()
open('/tmp/app.js','w').write(re.findall(r'<script>(.*?)</script>', html, re.S)[-1])
PY
node --check /tmp/app.js
```

For data/logic checks, a Node harness can load `site/index.js` + `site/data/*.js`
into a `global.window` shim and exercise helpers like `entryMatches` /
`filteredCounts` / the scope functions against the real cached weeks.

## Conventions

- Match the surrounding code style (the embedded JS is terse, single-quoted, minimal).
- Don't introduce front-end build tooling or split the generator's strings into
  separate asset files without a reason — the single-file generator is intentional.
- Commit only source (`config.py`, `generate_digest.py`, `build_site.py`, `data/`).
- Develop on a branch and open a PR; `site/` rebuilds in CI for the Pages artifact.
- The GitHub Actions workflow is `.github/workflows/daily-digest.yml`.
