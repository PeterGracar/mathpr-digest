#!/usr/bin/env python3
"""
Weekly math.PR arXiv digest generator for Peter Gracar.

Idempotent and re-runnable:
  * Determines every completed Mon-Sun week from FIRST_WEEK_MONDAY up to the
    most recent completed Sunday (strictly before "today").
  * Fetches new submissions to math.PR for any week not already cached in
    data/, scores them against Peter's research interests, flags his own
    papers and coauthors, and writes data/week-YYYY-MM-DD.json.
  * Rebuilds the browsable HTML site in site/ from all cached weeks.

This means missing past digests are constructed retroactively on every run.

Network access uses the `curl` CLI (the bundled Python has no CA bundle).
Usage:  python3 generate_digest.py [YYYY-MM-DD as "today" override]
"""
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import config

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SITE_DIR = os.path.join(HERE, "site")

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "o": "http://arxiv.org/schemas/atom",
    "os": "http://a9.com/-/spec/opensearch/1.1/",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def norm(s):
    """Lowercase + strip accents for robust matching."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def monday_of(d):
    return d - timedelta(days=d.weekday())


def weeks_to_build(today):
    """All Mon-Sun weeks from FIRST_WEEK_MONDAY through the week that contains
    `today`. The current week is included even though it is only partial; it is
    re-fetched on each run until finalized (see build_week)."""
    first = monday_of(datetime.strptime(config.FIRST_WEEK_MONDAY, "%Y-%m-%d").date())
    this_monday = monday_of(today)
    weeks = []
    m = first
    while m <= this_monday:
        weeks.append((m, m + timedelta(days=6)))
        m += timedelta(days=7)
    return weeks


def curl_get(params, retries=3):
    args = ["curl", "-sS", "-m", "90", "-G", "https://export.arxiv.org/api/query"]
    for k, v in params.items():
        args += ["--data-urlencode", f"{k}={v}"]
    last_err = ""
    for attempt in range(retries):
        p = subprocess.run(args, capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout
        last_err = p.stderr or "empty response"
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"arXiv API request failed: {last_err}")


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------
def fetch_week(monday, sunday):
    lo = monday.strftime("%Y%m%d") + "0000"
    hi = sunday.strftime("%Y%m%d") + "2359"
    query = f"cat:{config.CATEGORY} AND submittedDate:[{lo} TO {hi}]"
    entries = []
    start = 0
    page = 100
    total = None
    while True:
        xml = curl_get({
            "search_query": query,
            "start": str(start),
            "max_results": str(page),
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        })
        root = ET.fromstring(xml)
        if total is None:
            total = int(root.find("os:totalResults", NS).text)
        batch = root.findall("a:entry", NS)
        if not batch:
            break
        for e in batch:
            entries.append(parse_entry(e))
        start += page
        if start >= total:
            break
        time.sleep(3)  # be polite to arXiv
    # de-dup by id (paging can occasionally overlap)
    seen, uniq = set(), []
    for e in entries:
        if e["id"] not in seen:
            seen.add(e["id"])
            uniq.append(e)
    return uniq, total


def parse_entry(e):
    def txt(tag):
        node = e.find(tag, NS)
        return node.text.strip() if node is not None and node.text else ""

    # strip the version suffix ('…v2') so the id and links always point at the
    # latest revision of the article rather than the announced version
    arxiv_id = re.sub(r"v\d+$", "", txt("a:id").split("/abs/")[-1])
    authors = [a.find("a:name", NS).text.strip()
               for a in e.findall("a:author", NS)
               if a.find("a:name", NS) is not None]
    cats = [c.get("term") for c in e.findall("a:category", NS)]
    prim = e.find("o:primary_category", NS)
    primary = prim.get("term") if prim is not None else (cats[0] if cats else "")
    return {
        "id": arxiv_id,
        "title": " ".join(txt("a:title").split()),
        "abstract": " ".join(txt("a:summary").split()),
        "authors": authors,
        "published": txt("a:published"),
        "updated": txt("a:updated"),
        "primary_category": primary,
        "categories": cats,
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
    }


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------
def score_entry(e):
    hay = norm(e["title"] + " . " + e["abstract"])
    score = 0
    matched = []
    for kw, w in config.HIGH_KEYWORDS + config.MED_KEYWORDS:
        # word-boundary match so short acronyms (sis, sir) don't match inside
        # words like "analysis"/"basis"; \b sits fine around hyphenated phrases.
        pat = r"\b" + re.escape(norm(kw).strip()) + r"\b"
        if re.search(pat, hay):
            score += w
            matched.append(kw.strip())
    # own-paper / coauthor detection
    author_norm = [norm(a) for a in e["authors"]]
    op = norm(config.OWNER).split()
    own = any(op[-1] in an and op[0] in an for an in author_norm)
    coauthors_hit = []
    for ca in config.COAUTHORS:
        cn = norm(ca)
        # match on full normalised name, tolerant of middle initials / order
        parts = cn.split()
        first, last = parts[0], parts[-1]
        for an in author_norm:
            if last in an and first in an:
                coauthors_hit.append(ca)
                break
    e["score"] = score
    e["matched_keywords"] = sorted(set(matched))
    e["own"] = own
    e["coauthors"] = sorted(set(coauthors_hit))
    if own:
        e["bucket"] = "own"
    elif e["coauthors"]:
        e["bucket"] = "coauthor"
    elif score >= config.HIGH_THRESHOLD:
        e["bucket"] = "high"
    elif score >= config.MED_THRESHOLD:
        e["bucket"] = "medium"
    else:
        e["bucket"] = "other"
    return e


# --------------------------------------------------------------------------
# week JSON
# --------------------------------------------------------------------------
def week_path(monday):
    return os.path.join(DATA_DIR, f"week-{monday.isoformat()}.json")


def build_week(monday, sunday, today, force=False):
    path = week_path(monday)
    friday = monday + timedelta(days=4)
    # arXiv announces new submissions only on weekdays (Mon–Fri), so once a
    # week's Friday has passed (i.e. a Saturday-or-later run) the whole week's
    # announced content is in and the week is treated as complete.
    complete = today > friday
    # Still re-fetch for a grace period past the nominal Sunday so any weekend-
    # submitted papers that arXiv only announces the following week are captured
    # before the week is frozen.
    finalized = (today - sunday).days > config.FINALIZE_GRACE_DAYS
    # Skip only weeks already cached AND finalized. Partial (current) weeks and
    # just-completed weeks still inside the grace window are re-fetched so future
    # runs top up their data; once finalized a week is frozen forever.
    if os.path.exists(path) and not force:
        with open(path) as f:
            cached = json.load(f)
        if cached.get("finalized"):
            return cached
    tag = "partial" if not complete else ("finalizing" if not finalized else "final")
    print(f"  fetching {monday} .. {sunday} ({tag}) ...", flush=True)
    entries, total = fetch_week(monday, sunday)
    for e in entries:
        score_entry(e)
    entries.sort(key=lambda x: (x["bucket"] != "own",
                                x["bucket"] != "coauthor",
                                x["bucket"] != "high",
                                x["bucket"] != "medium",
                                -x["score"], x["published"]))
    iso = monday.isocalendar()
    data = {
        "monday": monday.isoformat(),
        "sunday": sunday.isoformat(),
        "iso_year": iso[0],
        "iso_week": iso[1],
        "category": config.CATEGORY,
        "complete": complete,
        "finalized": finalized,
        "data_through": (sunday if complete else today).isoformat(),
        "total_submissions": total,
        "fetched": len(entries),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": entries,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"    -> {len(entries)} submissions, "
          f"{sum(1 for e in entries if e.get('own'))} own, "
          f"{sum(1 for e in entries if e['coauthors'])} coauthor, "
          f"{sum(1 for e in entries if e['bucket']=='high')} high-relevance"
          f"{'' if finalized else '  (will refresh next run)'}",
          flush=True)
    return data


# --------------------------------------------------------------------------
# site build (delegated to build_site for clarity)
# --------------------------------------------------------------------------
def main():
    today = date.today()
    if len(sys.argv) > 1:
        today = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(SITE_DIR, exist_ok=True)

    weeks = weeks_to_build(today)
    print(f"Today={today}. Weeks to ensure: "
          f"{', '.join(m.isoformat() for m, _ in weeks)}")
    all_weeks = []
    for m, s in weeks:
        all_weeks.append(build_week(m, s, today))

    import build_site
    build_site.build(all_weeks)
    print("Done.")


if __name__ == "__main__":
    main()
