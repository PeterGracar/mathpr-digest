#!/usr/bin/env python3
"""
Weekly math.PR arXiv digest generator for Peter Gracar.

Idempotent and re-runnable:
  * Determines every week (keyed by its Monday) from FIRST_WEEK_MONDAY up to
    the week containing "today".
  * Fetches the new math.PR submissions arXiv announced Monday to Friday of
    any week not already finalized in data/, scores them against Peter's
    research interests, flags his own papers and coauthors, and writes
    data/week-YYYY-MM-DD.json.
  * Rebuilds the browsable HTML site in site/ from all cached weeks.

This means missing past digests are constructed retroactively on every run.

Network access uses the `curl` CLI (the bundled Python has no CA bundle)
against arXiv's OAI-PMH endpoint (https://oaipmh.arxiv.org/oai, arXivRaw
format); the old export.arxiv.org Atom API rate-limits GitHub's shared
runner IPs for hours at a time.
Usage:  python3 generate_digest.py [YYYY-MM-DD as "today" override]
"""
import json
import os
import re
from email.utils import parsedate_to_datetime
import subprocess
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import build_site
import config
from tex2utf import tex2utf

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SITE_DIR = os.path.join(HERE, "site")

OAI_URL = "https://oaipmh.arxiv.org/oai"
NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "raw": "http://arxiv.org/OAI/arXivRaw/",
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


USER_AGENT = "mathpr-digest/1.0 (+https://github.com/PeterGracar/mathpr-digest)"


def curl_get(params, retries=8):
    """GET the arXiv OAI-PMH endpoint and return the parsed OAI-PMH root.

    Every failure mode is retried, not just a failed transfer: arXiv answers
    with a plain-text "Rate exceeded." (HTTP 429) or an HTML error page
    (HTTP 503 / maintenance) now and then, and without --fail-with-body curl
    reports those as success, so an HTTP error status, a body that is not
    well-formed XML, and a body that is XML but not an Atom feed all count as
    a failed attempt too. Returning the parsed root (rather than the raw text)
    is what lets the parse error be caught here instead of aborting the whole
    run one level up.

    Backoff: 15 s, 30 s, ... for generic failures; for 429 / 503 the wait is
    at least 60 s, 120 s, ... (about 30 min over the default 8 attempts) and
    honours a Retry-After header. Rate limiting is per IP and GitHub's runners
    share theirs, so a throttled run needs minutes, not seconds, to clear.
    The User-Agent identifies this client to arXiv, as its API terms ask."""
    with tempfile.NamedTemporaryFile(prefix="arxiv-hdr-", suffix=".txt") as hdr:
        args = ["curl", "-sS", "-m", "300", "--fail-with-body", "-A", USER_AGENT,
                "-D", hdr.name, "-G", OAI_URL]
        for k, v in params.items():
            args += ["--data-urlencode", f"{k}={v}"]
        last_err = ""
        for attempt in range(retries):
            open(hdr.name, "w").close()   # no stale headers if curl never connects
            p = subprocess.run(args, capture_output=True, text=True)
            body = p.stdout
            status, retry_after = _response_meta(hdr.name)
            if p.returncode != 0:
                last_err = (p.stderr.strip() or f"curl exit {p.returncode}")
                if body.strip():
                    last_err += f", body starts: {body.strip()[:120]!r}"
            elif not body.strip():
                last_err = "empty response"
            else:
                try:
                    root = ET.fromstring(body)
                except ET.ParseError as e:
                    last_err = f"response is not XML ({e}), starts: {body.strip()[:120]!r}"
                else:
                    if root.tag == f"{{{NS['oai']}}}OAI-PMH":
                        return root
                    last_err = f"unexpected XML root {root.tag!r}"
            print(f"    arXiv request attempt {attempt + 1}/{retries} failed: {last_err}",
                  file=sys.stderr)
            if attempt + 1 < retries:
                if status in (429, 503):
                    wait = max(60 * (attempt + 1), retry_after)
                else:
                    wait = 15 * (attempt + 1)
                wait = min(wait, 600)
                print(f"    waiting {wait} s before retrying", file=sys.stderr)
                time.sleep(wait)
    raise RuntimeError(f"arXiv API request failed after {retries} attempts: {last_err}")


def _response_meta(header_file):
    """(HTTP status, Retry-After seconds) from the headers curl dumped with -D;
    (None, 0) if there is no usable status line. Only the last status line
    counts, so a redirect's headers do not shadow the final response."""
    status, retry_after = None, 0
    try:
        with open(header_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("HTTP/"):
                    parts = line.split()
                    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
                    retry_after = 0
                elif line.lower().startswith("retry-after:"):
                    value = line.split(":", 1)[1].strip()
                    retry_after = int(value) if value.isdigit() else 0
    except OSError:
        pass
    return status, retry_after


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------
def fetch_week(monday, today):
    """Fetch every math.PR record that can belong to the week starting
    `monday`, i.e. that can have been announced (listed) Mon-Fri of it.

    OAI-PMH selects by *datestamp*, the UTC day arXiv last touched the
    record (announcing a version, adding a cross-list or journal-ref), not by
    submission time. A new paper is stamped when its announcement is
    processed, i.e. on the listing day or the evening before (mailings go
    out Sun-Thu 20:00 ET, which is Mon-Fri 00:00 EDT / 01:00 EST in UTC).
    The window therefore starts on the previous Thursday for margin, and runs
    to the week's finalization horizon so that a paper replaced during the
    grace period (which moves its datestamp) is still found by the daily
    re-fetch. It cannot run past today: the endpoint rejects `until` beyond
    tomorrow. Every record carries all its versions, so the caller can still
    derive the listing date from the v1 submission time and trim to the week.
    Unlike the old Atom API's submittedDate query, this cannot rebuild a week
    that is long past: papers touched after its horizon have moved out of
    the window. data/ is the persistent cache for that reason."""
    frm = monday - timedelta(days=4)
    until = min(today, datetime.now(timezone.utc).date(),
                monday + timedelta(days=6 + config.FINALIZE_GRACE_DAYS))
    params = {
        "verb": "ListRecords",
        "metadataPrefix": "arXivRaw",
        "set": oai_set(config.CATEGORY),
        "from": frm.isoformat(),
        "until": until.isoformat(),
    }
    entries = []
    while True:
        root = curl_get(params)
        err = root.find("oai:error", NS)
        if err is not None:
            if err.get("code") == "noRecordsMatch":
                break
            raise RuntimeError(f"OAI-PMH error {err.get('code')}: {(err.text or '').strip()}")
        for rec in root.findall("oai:ListRecords/oai:record", NS):
            e = parse_record(rec)
            if e is not None:
                entries.append(e)
        token = root.find("oai:ListRecords/oai:resumptionToken", NS)
        if token is None or not (token.text or "").strip():
            break
        params = {"verb": "ListRecords", "resumptionToken": token.text.strip()}
        time.sleep(3)  # be polite to arXiv
    # de-dup by id (a listing spanning several pages can repeat a record)
    seen, uniq = set(), []
    for e in entries:
        if e["id"] not in seen:
            seen.add(e["id"])
            uniq.append(e)
    return uniq


def oai_set(category):
    """OAI-PMH setSpec for an arXiv category: group:archive:subject, e.g.
    math.PR -> math:math:PR (physics categories sit under the physics group:
    hep-th -> physics:hep-th). Selects the category as primary or cross-list."""
    archive, _, subject = category.partition(".")
    group = "physics" if archive in PHYSICS_ARCHIVES else archive
    return ":".join(p for p in (group, archive, subject) if p)


PHYSICS_ARCHIVES = {"astro-ph", "cond-mat", "gr-qc", "hep-ex", "hep-lat", "hep-ph",
                    "hep-th", "math-ph", "nlin", "nucl-ex", "nucl-th", "physics",
                    "quant-ph"}


def parse_record(rec):
    """One OAI-PMH <record> in arXivRaw format -> entry dict, or None for a
    deleted record. Field names and formats match what the old Atom API
    fetch produced, so cached weeks and the site need no migration."""
    md = rec.find("oai:metadata/raw:arXivRaw", NS)
    if md is None:   # <header status="deleted"> carries no metadata
        return None

    def txt(tag):
        node = md.find(tag, NS)
        return node.text.strip() if node is not None and node.text else ""

    def clean(s):
        return " ".join(to_unicode(s).split())

    arxiv_id = txt("raw:id")
    versions = sorted(
        ((int(v.get("version", "v0")[1:]), v.findtext("raw:date", "", NS).strip())
         for v in md.findall("raw:version", NS)),
        key=lambda x: x[0])
    cats = dedupe_aliases(txt("raw:categories").split())
    return {
        "id": arxiv_id,
        "title": clean(txt("raw:title")),
        "abstract": clean(txt("raw:abstract")),
        "authors": split_authors(txt("raw:authors")),
        "published": iso_utc(versions[0][1]) if versions else "",
        "updated": iso_utc(versions[-1][1]) if versions else "",
        "primary_category": cats[0] if cats else "",
        "categories": cats,
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
    }


def to_unicode(tex):
    """tex2utf with one upstream gap closed: its dotless-i/j normalisation
    (\\u{\\i} -> \\u{i}) never fires because of a stray '/' in the regex, so
    Kre\\u{\\i}n came out as "Kre\\uın" where the Atom API gave "Kreĭn"."""
    tex = re.sub(r"(\\[\'`^\"~=.uvH])\{\\([ij])\}", r"\1{\2}", tex)
    return tex2utf(tex)


# arXiv stores both names of an aliased category pair (math-ph = math.MP,
# math.NA = cs.NA, ...) and arXivRaw lists both; the Atom API listed one, and
# the cache follows it. Maps the name to drop -> the name kept when both occur.
CATEGORY_ALIASES = {"math.MP": "math-ph", "cs.NA": "math.NA", "stat.TH": "math.ST",
                    "math.IT": "cs.IT", "econ.GN": "q-fin.EC", "eess.SY": "cs.SY"}


def dedupe_aliases(cats):
    return [c for c in cats if CATEGORY_ALIASES.get(c) not in cats]


def iso_utc(rfc2822):
    """'Wed, 25 Jun 2008 15:29:38 GMT' (arXivRaw version date) ->
    '2008-06-25T15:29:38Z', the Atom API's timestamp format the JSON and
    build_site.announced_on expect."""
    t = parsedate_to_datetime(rfc2822)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_SUFFIX = re.compile(r"^(Jr\.?|Sr\.?|I{2,3}|IV)$", re.I)


def split_authors(line):
    """Names from an arXiv authors line, affiliations dropped: 'A. Foo (1),
    B. Bar (1 and 2) and C. Baz ((1) Univ X (2) Univ Y)' -> ['A. Foo',
    'B. Bar', 'C. Baz']. Follows arXiv's own parse_author_affil (arxiv-base)
    in what it treats as separators, suffixes and 'et al'."""
    s = to_unicode(line)
    out, depth = [], 0        # drop parenthesised material, nested too
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif depth == 0:
            out.append(ch)
    s = re.sub(r",?\s+(and|&)\s+", ",", "".join(out))
    names = []
    for part in re.split(r"[,;:]", s):
        name = re.sub(r"\.(\S)", r". \1", part)   # O.I. Marichev -> O. I. Marichev
        name = " ".join(name.replace("{", "").replace("}", "").split())
        if not name or re.match(r"^et\.?\s+al\.?$", name, re.I):
            continue
        if _SUFFIX.match(name) and names:
            names[-1] += ", " + name
        else:
            names.append(name)
    return names


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
    e["announced"] = build_site.announced_on(e["published"])
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
    # A week's digest is the set of papers arXiv announced (listed) Monday to
    # Friday of that week. arXiv lists new submissions only on weekdays, so
    # once the Friday has passed (a Saturday-or-later run) the week's content
    # is in and the week is treated as complete.
    complete = today > friday
    # Still re-fetch for a grace period past the nominal Sunday so a late API
    # index update (or a holiday-shifted mailing) is captured before freezing.
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
    entries = fetch_week(monday, today)
    for e in entries:
        score_entry(e)
    # keep only papers listed Mon–Fri of this week; the fetch window's edges
    # belong to the neighbouring weeks (Thursday-afternoon submissions are
    # listed the following Monday)
    lo, hi = monday.isoformat(), friday.isoformat()
    entries = [e for e in entries if lo <= e["announced"] <= hi]
    # bucket, then announcement date, then score, then submission time — the
    # same key build_site applies at build time, so JSON and site never differ
    entries.sort(key=build_site.entry_sort_key)
    iso = monday.isocalendar()
    data = {
        "monday": monday.isoformat(),
        "sunday": sunday.isoformat(),
        "iso_year": iso[0],
        "iso_week": iso[1],
        "category": config.CATEGORY,
        "complete": complete,
        "finalized": finalized,
        "data_through": (friday if complete else today).isoformat(),
        "total_submissions": len(entries),
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

    build_site.build(all_weeks)
    print("Done.")


if __name__ == "__main__":
    main()
