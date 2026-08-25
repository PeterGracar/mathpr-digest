# math.PR Weekly Digest

Automated weekly digest of new arXiv [math.PR](https://arxiv.org/list/math.PR/recent)
submissions, curated for **Peter Gracar**'s research interests
(random geometric graphs, percolation, particle systems, spread of infection)
and highlighting any submission by one of his coauthors.

## How to run / refresh

```bash
python3 generate_digest.py            # uses today's date
python3 generate_digest.py 2026-06-16 # override "today" (for testing/backfill)
```

The generator is **idempotent, self-backfilling, and self-updating**:

- It builds one digest per **Mon–Sun ISO week**, from the first week of June 2026
  (`config.FIRST_WEEK_MONDAY`) up to and including the current week.
- arXiv announces new submissions only on **weekdays (Mon–Fri)**, so a week is
  treated as **complete once its Friday has passed**. The scheduled run is daily
  on weekdays, so the first run after a week's Friday captures it as a full week.
  (A run made *before* a week's Friday — e.g. a manual mid-week run, or the
  Mon–Thu scheduled runs — builds it as a partial "in progress" digest that fills
  in on later runs.)
- A complete week is still **re-fetched on each run until it is finalized**, kept
  open for a grace period past its nominal Sunday
  (`config.FINALIZE_GRACE_DAYS`, default 2 days) so any weekend-submitted papers
  that arXiv only announces the following week are captured before freezing.
- A week is **finalized** once `(today − its Sunday) > FINALIZE_GRACE_DAYS`. Once
  finalized it is frozen and never re-fetched; before then it is refreshed.
- **Any missing past week is constructed retroactively** automatically.
- After fetching, it rebuilds the browsable site in `site/`. In-progress weeks
  are marked with an "in progress" tag, a sidebar dot, and a "data through …"
  banner.

Each week's JSON records `complete` (week fully elapsed), `finalized` (frozen),
and `data_through` (last day covered). To force a re-fetch of any week, delete
its `data/week-YYYY-MM-DD.json` and re-run.

## Viewing the site

The header carries a **"← Back to gracar.org"** link. Its target is, in order of
preference:

1. a `?from=` parameter on the incoming link — `…/mathpr-digest/?from=secret.html`
   sends you back to `https://gracar.org/secret.html`;
2. the referrer, when the browser passes a full path (see below);
3. `config.BACK_URL` (label `config.BACK_LABEL`), which defaults to the domain root.

Only URLs on the `BACK_URL` host (or a subdomain) are accepted, so a hand-crafted
`?from=` can't repoint the link off-site. The resolved target is kept in
`sessionStorage` so a reload doesn't lose it, and `?from=` is stripped from the
address bar so the referring path isn't carried along if the digest URL is shared.

**Linking from a page on gracar.org.** Browsers now trim cross-site referrers to
the bare origin by default, so a plain link lands you back at `gracar.org`, not at
the page you came from. To return to that exact page, use either form on the
linking page:

```html
<a href="https://<user>.github.io/mathpr-digest/?from=secret.html">math.PR digest</a>
<a href="https://<user>.github.io/mathpr-digest/" referrerpolicy="unsafe-url">math.PR digest</a>
```

The `?from=` form is the reliable one; `referrerpolicy` depends on the browser
honouring it and is suppressed entirely by some privacy settings.

The sidebar groups weeks under **collapsible year headers**; only the current
year is expanded by default, so the selector stays compact as years accumulate
(one collapsed line per past year). Click a year to expand/collapse it. Within
an open year, weeks **at least one month old fold into collapsible month
sub-groups** (in September, July's weeks merge; August and September stay
individually listed), each showing its week count and any ✦ own / ★ coauthor
totals — so an expanded year is ~12 month lines plus the recent weeks, not 52
rows. During a search, month headers show that month's aggregated hit count and
dim when nothing matches.

The site is **lazy-loaded** so it scales to many weeks without bloat:

- `site/index.js` (`window.DIGEST_INDEX`) holds only lightweight per-week
  summaries (dates + counts, no entries) and is loaded up front — a few KB that
  grows only ~tens of bytes per week.
- `site/data/week-*.js` (`window.DIGEST_WEEKS["<monday>"]`) holds each week's
  full entries and is fetched **on demand** when you open that week (via
  `<script>` injection, so it works from `file://` in most browsers).

So opening the page loads the index plus just the current week; older weeks load
only when clicked. Initial payload stays roughly constant no matter how many
years are archived.

Open `site/index.html` directly in a browser, or serve it (recommended; some
browsers restrict loading local `data/week-*.js` files over `file://`, in which
case the page shows a hint to serve the folder):

```bash
python3 -m http.server 8731 --directory site
```

## Running on GitHub (no local machine needed)

`.github/workflows/daily-digest.yml` runs the whole pipeline on GitHub's
infrastructure: a weekday cron (02:17 UTC, Mon–Fri), plus a push-to-`main`
trigger (so template/code edits go live immediately) and a manual "Run workflow"
button, runs `generate_digest.py`, commits the updated `data/` back to the repo
(`site/` is git-ignored and rebuilt each run), and publishes the freshly built
`site/` to **GitHub Pages** over https. No secrets are needed — arXiv's API is
public.

One-time setup:

1. Create a GitHub repo and push this folder.
   ```bash
   git init && git add -A && git commit -m "math.PR weekly digest"
   git branch -M main
   git remote add origin git@github.com:<you>/<repo>.git
   git push -u origin main
   ```
2. In the repo: **Settings → Pages → Build and deployment → Source: GitHub
   Actions**.
3. (Optional) **Actions** tab → *Daily math.PR digest* → **Run workflow** to
   trigger the first build immediately instead of waiting for the next cron.

Notes:
- GitHub Pages on a **private** repo needs a paid plan; on the **free** plan use
  a **public** repo. `config.py` holds only public info (name, coauthors, and
  keywords from gracar.org), so a public repo is fine.
- Actions cron is best-effort (UTC, may lag/skip under load); the self-backfill
  logic reconstructs any missed week on the next run.
- The weekday digest commits keep the repo active, so the scheduled workflow
  won't hit GitHub's 60-days-inactivity auto-disable.
- Once the GitHub run is confirmed working, retire the local Claude Code
  scheduled task so digests aren't produced in two places.

## Layout

| Path                  | Purpose                                                       |
|-----------------------|--------------------------------------------------------------|
| `config.py`           | Coauthors, relevance keywords/weights, thresholds, dates.    |
| `generate_digest.py`  | Fetch (arXiv API via `curl`), score, cache per-week JSON.    |
| `build_site.py`       | Render `data/*.json` → `site/{index.html, style.css, index.js, data/week-*.js}`. Holds all HTML/CSS/JS as raw strings. |
| `data/week-*.json`    | One cached digest per week (raw + scored entries).           |
| `site/`               | The generated browsable website (git-ignored; rebuilt each run). |
| `CLAUDE.md`           | Architecture + conventions guide for working in the repo.    |

## Scoring

Each submission's title+abstract is matched (word-boundary, accent-insensitive)
against weighted keywords in `config.py`. Submissions are bucketed:

- **Own** — any author matches `config.OWNER` (Peter's own papers, always first).
- **Coauthor** — any author matches `config.COAUTHORS`.
- **Highly relevant** — score ≥ `HIGH_THRESHOLD`.
- **Possibly relevant** — score ≥ `MED_THRESHOLD`.
- **Everything else** — collapsed by default in the UI.

Tune keywords/weights in `config.py`; new coauthors go in `config.COAUTHORS`.

## Notes

- arXiv filters on `submittedDate`, so each week captures genuinely *new*
  (v1) submissions announced in that window, including math.PR cross-lists.
- The bundled Python lacks a CA bundle, so network requests use the `curl` CLI.
