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
  no CA bundle), scores each entry, buckets it (`coauthor` / `high` / `medium` /
  `other`), and writes one JSON file per Mon–Sun ISO week to `data/`. Idempotent,
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
- **The site is lazy-loaded.** `site/index.js` (`window.DIGEST_INDEX`) holds only
  per-week summaries — dates + `counts {coauthor, high, medium, other, total}`,
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
