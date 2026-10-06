#!/usr/bin/env python3
"""
Update the lab's publication list automatically.

1. Pulls the curated list of works from ORCID (Scopus and Crossref push new
   papers into ORCID for you).
2. Adds anything OpenAlex attributes to the same ORCID iD that ORCID is missing.
3. Enriches every paper with full author lists, venue, open-access link and
   citation counts from OpenAlex.
4. Applies your manual tweaks from data/pub_overrides.json.
5. Writes data/publications.json and _publications.md (included by
   publications.qmd).

Uses only the Python standard library, so nothing needs installing.
If both APIs fail, the previous publication list is kept unchanged.

Usage:
    python scripts/fetch_publications.py            # fetch + rebuild
    python scripts/fetch_publications.py --render   # rebuild markdown only
"""

import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "data", "pub_config.json")
OVERRIDES_PATH = os.path.join(ROOT, "data", "pub_overrides.json")
JSON_OUT = os.path.join(ROOT, "data", "publications.json")
MD_OUT = os.path.join(ROOT, "_publications.md")
RECENT_OUT = os.path.join(ROOT, "_recent_publications.md")

ORCID_API = "https://pub.orcid.org/v3.0"
OPENALEX_API = "https://api.openalex.org"

# OpenAlex work types worth listing (drops datasets, paratext, errata, ...)
KEEP_TYPES = {"article", "review", "book-chapter", "book", "letter", "preprint"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_json(url, headers=None, retries=3):
    headers = {"Accept": "application/json",
               "User-Agent": "lab-website-publication-updater/1.0",
               **(headers or {})}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == retries - 1:
                raise
            print(f"  retrying ({e}) ...", file=sys.stderr)
            time.sleep(3 * (attempt + 1))


def norm_doi(doi):
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi or None


def norm_title(t):
    t = html.unescape(t or "")
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def clean_title(t):
    t = html.unescape(t or "").strip()
    t = re.sub(r"<(/?)(i|em|sup|sub)>", r"<\1\2>", t, flags=re.I)
    t = re.sub(r"<(?!/?(i|em|sup|sub)>)[^>]+>", "", t, flags=re.I)  # keep italics only
    return re.sub(r"\s+", " ", t).rstrip(".")


def key_of(p):
    return ("doi:" + p["doi"]) if p.get("doi") else ("t:" + norm_title(p["title"]))


def dig(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


# --------------------------------------------------------------------------- #
# ORCID
# --------------------------------------------------------------------------- #
def fetch_orcid(orcid):
    print(f"ORCID: fetching works for {orcid}")
    data = get_json(f"{ORCID_API}/{orcid}/works")
    summaries = []
    for g in data.get("group", []):
        ws = g.get("work-summary") or []
        if not ws:
            continue
        # the summary with the highest display index is the one the owner prefers
        s = sorted(ws, key=lambda w: int(w.get("display-index") or 0), reverse=True)[0]
        summaries.append(s)

    # bulk endpoint (100 put-codes per call) gives contributors
    details = {}
    codes = [str(s["put-code"]) for s in summaries]
    for i in range(0, len(codes), 100):
        chunk = ",".join(codes[i:i + 100])
        try:
            bulk = get_json(f"{ORCID_API}/{orcid}/works/{chunk}")
            for b in bulk.get("bulk", []):
                w = b.get("work")
                if w:
                    details[str(w["put-code"])] = w
        except Exception as e:  # contributors are optional
            print(f"  ORCID bulk details failed: {e}", file=sys.stderr)

    pubs = []
    for s in summaries:
        doi = None
        for eid in dig(s, "external-ids", "external-id") or []:
            if (eid.get("external-id-type") or "").lower() == "doi":
                doi = norm_doi(eid.get("external-id-value"))
                break
        title = dig(s, "title", "title", "value") or ""
        year = dig(s, "publication-date", "year", "value")
        w = details.get(str(s["put-code"]), {})
        authors = [dig(c, "credit-name", "value")
                   for c in (dig(w, "contributors", "contributor") or [])]
        authors = [a for a in authors if a]
        pubs.append({
            "title": clean_title(title),
            "year": int(year) if year and str(year).isdigit() else None,
            "venue": dig(s, "journal-title", "value") or "",
            "doi": doi,
            "type": (s.get("type") or "").replace("_", "-"),
            "authors": authors,
            "url": dig(s, "url", "value"),
            "source": "orcid",
        })
    print(f"  {len(pubs)} works")
    return pubs


# --------------------------------------------------------------------------- #
# OpenAlex
# --------------------------------------------------------------------------- #
OA_SELECT = ("id,doi,title,publication_year,type,authorships,primary_location,"
             "open_access,cited_by_count,is_paratext,is_retracted,biblio")


def oa_params(extra, email):
    p = {"select": OA_SELECT, "per-page": "200", **extra}
    if email:
        p["mailto"] = email
    return urllib.parse.urlencode(p, safe=":|,")


def oa_to_pub(w):
    authors = [dig(a, "author", "display_name") for a in (w.get("authorships") or [])]
    b = w.get("biblio") or {}
    return {
        "title": clean_title(w.get("title")),
        "year": w.get("publication_year"),
        "venue": dig(w, "primary_location", "source", "display_name") or "",
        "doi": norm_doi(w.get("doi")),
        "type": w.get("type") or "",
        "authors": [a for a in authors if a],
        "volume": b.get("volume"),
        "issue": b.get("issue"),
        "pages": "–".join(x for x in [b.get("first_page"), b.get("last_page")] if x) or None,
        "oa_url": dig(w, "open_access", "oa_url"),
        "cited_by": w.get("cited_by_count"),
        "openalex": w.get("id"),
        "source": "openalex",
        "_paratext": w.get("is_paratext"),
        "_retracted": w.get("is_retracted"),
    }


def fetch_openalex_by_orcid(orcid, email):
    print("OpenAlex: fetching works linked to the ORCID iD")
    pubs, cursor = [], "*"
    while cursor:
        url = f"{OPENALEX_API}/works?" + oa_params(
            {"filter": f"author.orcid:{orcid}", "cursor": cursor}, email)
        data = get_json(url)
        pubs += [oa_to_pub(w) for w in data.get("results", [])]
        cursor = dig(data, "meta", "next_cursor")
        if not data.get("results"):
            break
    print(f"  {len(pubs)} works")
    return pubs


def fetch_openalex_by_dois(dois, email):
    out = {}
    dois = sorted(set(d for d in dois if d))
    for i in range(0, len(dois), 50):
        chunk = "|".join(dois[i:i + 50])
        url = f"{OPENALEX_API}/works?" + oa_params({"filter": f"doi:{chunk}"}, email)
        try:
            for w in get_json(url).get("results", []):
                p = oa_to_pub(w)
                if p["doi"]:
                    out[p["doi"]] = p
        except Exception as e:
            print(f"  OpenAlex DOI lookup failed: {e}", file=sys.stderr)
    return out


# --------------------------------------------------------------------------- #
# merge
# --------------------------------------------------------------------------- #
def merge(orcid_pubs, oa_pubs, oa_by_doi, include_openalex_only):
    merged = {}
    for p in orcid_pubs:
        k = key_of(p)
        if k in merged:           # ORCID sometimes has true duplicates
            continue
        rich = oa_by_doi.get(p["doi"]) if p.get("doi") else None
        if rich:
            q = dict(rich)
            q["title"] = p["title"] or rich["title"]   # keep the curated title
            q["venue"] = rich["venue"] or p["venue"]
            q["authors"] = rich["authors"] or p["authors"]
            q["source"] = "orcid+openalex"
            merged[k] = q
        else:
            merged[k] = p

    if include_openalex_only:
        titles = {norm_title(p["title"]) for p in merged.values()}
        for p in oa_pubs:
            if p.get("_paratext") or p.get("_retracted"):
                continue
            if p["type"] not in KEEP_TYPES:
                continue
            k = key_of(p)
            if k in merged or norm_title(p["title"]) in titles:
                continue
            merged[k] = p
            titles.add(norm_title(p["title"]))

    # OpenAlex often lists a preprint and the published article separately
    published = {norm_title(p["title"]) for p in merged.values() if p.get("type") != "preprint"}
    return [p for p in merged.values()
            if not (p.get("type") == "preprint" and norm_title(p["title"]) in published)]


def apply_overrides(pubs, ov):
    excl = {norm_doi(x) or x for x in ov.get("exclude", [])}
    excl_titles = {norm_title(x) for x in ov.get("exclude", [])}
    pubs = [p for p in pubs
            if p.get("doi") not in excl and norm_title(p["title"]) not in excl_titles]
    fixes = {norm_doi(k) or norm_title(k): v for k, v in ov.get("fix", {}).items()}
    for p in pubs:
        f = fixes.get(p.get("doi")) or fixes.get(norm_title(p["title"]))
        if f:
            p.update(f)
    have = {key_of(p) for p in pubs}
    for e in ov.get("extra", []):
        e = dict(e)
        e["doi"] = norm_doi(e.get("doi"))
        e.setdefault("authors", [])
        e.setdefault("source", "manual")
        if key_of(e) not in have:
            pubs.append(e)
    return pubs


# --------------------------------------------------------------------------- #
# markdown output
# --------------------------------------------------------------------------- #
def fmt_authors(authors, highlight, max_authors=12):
    def mark(a):
        a = html.escape(a)
        return f"<strong>{a}</strong>" if any(h.lower() in a.lower() for h in highlight) else a

    if len(authors) > max_authors:
        head = authors[:6]
        hl = [a for a in authors[6:-1] if any(h.lower() in a.lower() for h in highlight)]
        shown = [mark(a) for a in head] + ["…"] + [mark(a) for a in hl] + \
                (["…"] if hl else []) + [mark(authors[-1])]
        return ", ".join(shown)
    return ", ".join(mark(a) for a in authors)


def fmt_entry(p, highlight):
    parts = []
    if p.get("authors"):
        parts.append(fmt_authors(p["authors"], highlight).rstrip(".") + ".")
    title = p["title"] or "Untitled"
    parts.append(f'<span class="pub-title">{title}</span>.')
    venue = f"<em>{html.escape(p['venue'])}</em>" if p.get("venue") else ""
    vol = p.get("volume") or ""
    if vol and p.get("issue"):
        vol += f"({p['issue']})"
    tail = ", ".join(x for x in [venue, vol, p.get("pages") or ""] if x)
    if tail:
        parts.append(tail + ".")
    links = []
    if p.get("doi"):
        links.append(f'<a class="pub-link" href="https://doi.org/{p["doi"]}">DOI</a>')
    elif p.get("url"):
        links.append(f'<a class="pub-link" href="{p["url"]}">Link</a>')
    if p.get("oa_url") and (not p.get("doi") or p["doi"] not in p["oa_url"].lower()):
        links.append(f'<a class="pub-link pub-oa" href="{p["oa_url"]}">Free PDF</a>')
    if p.get("cited_by"):
        links.append(f'<span class="pub-cites">Cited {p["cited_by"]}×</span>')
    body = " ".join(parts)
    return f'<li class="pub">{body} {" ".join(links)}</li>'


def render_markdown(pubs, meta, cfg):
    highlight = cfg.get("highlight", [])
    pubs = sorted(pubs, key=lambda p: (p.get("year") or 0, norm_title(p["title"])),
                  reverse=True)
    by_year = {}
    for p in pubs:
        by_year.setdefault(p.get("year") or "In press / undated", []).append(p)

    years = [y for y in by_year if isinstance(y, int)]
    lines = [
        "<!-- AUTO-GENERATED by scripts/fetch_publications.py. Do not edit by hand; "
        "use data/pub_overrides.json instead. -->",
        "",
        f'<p class="pub-meta">{len(pubs)} publications'
        + (f" · {min(years)}–{max(years)}" if years else "")
        + f' · updated {meta.get("updated", "—")}</p>',
        "",
        '<input id="pub-search" class="form-control" type="search" '
        'placeholder="Filter by title, author, journal or year…" aria-label="Filter publications">',
        "",
    ]
    for y, items in by_year.items():
        lines.append(f'<section class="pub-year" data-year="{y}">')
        lines.append(f'<h2 class="pub-year-heading">{y}</h2>')
        lines.append('<ol class="pub-list">')
        lines += [fmt_entry(p, highlight) for p in items]
        lines.append("</ol></section>")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_recent(pubs, cfg, n):
    pubs = sorted(pubs, key=lambda p: (p.get("year") or 0), reverse=True)[:n]
    items = [fmt_entry(p, cfg.get("highlight", [])).replace('<li class="pub">',
             f'<li class="pub"><span class="pub-cites">{p.get("year") or ""}</span> ', 1)
             for p in pubs]
    return ("<!-- AUTO-GENERATED by scripts/fetch_publications.py -->\n"
            '<ul class="pub-list" style="list-style:none;padding-left:0">\n'
            + "\n".join(items) + "\n</ul>\n")


# --------------------------------------------------------------------------- #
def main():
    cfg = load_json(CONFIG_PATH, {})
    ov = load_json(OVERRIDES_PATH, {})
    orcid = cfg["orcid"]
    email = cfg.get("contact_email") or os.environ.get("OPENALEX_EMAIL", "")
    render_only = "--render" in sys.argv

    previous = load_json(JSON_OUT, {"meta": {}, "publications": []})

    if render_only:
        pubs, meta = previous["publications"], previous["meta"]
    else:
        orcid_pubs, oa_pubs = [], []
        try:
            orcid_pubs = fetch_orcid(orcid)
        except Exception as e:
            print(f"ORCID failed: {e}", file=sys.stderr)
        try:
            oa_pubs = fetch_openalex_by_orcid(orcid, email)
        except Exception as e:
            print(f"OpenAlex failed: {e}", file=sys.stderr)

        if not orcid_pubs and not oa_pubs:
            print("Both sources failed — keeping the previous list.", file=sys.stderr)
            pubs, meta = previous["publications"], previous["meta"]
        else:
            by_doi = {p["doi"]: p for p in oa_pubs if p.get("doi")}
            missing = [p["doi"] for p in orcid_pubs if p.get("doi") and p["doi"] not in by_doi]
            if missing:
                print(f"OpenAlex: looking up {len(missing)} extra DOIs")
                by_doi.update(fetch_openalex_by_dois(missing, email))
            pubs = merge(orcid_pubs, oa_pubs, by_doi,
                         cfg.get("include_openalex_only", True))
            pubs = [{k: v for k, v in p.items() if not k.startswith("_")} for p in pubs]
            meta = {"updated": dt.date.today().isoformat(), "orcid": orcid,
                    "n_orcid": len(orcid_pubs), "n_openalex": len(oa_pubs)}

            # don't churn the repo if nothing but the date changed
            if pubs_equal(pubs, previous["publications"]):
                meta["updated"] = previous["meta"].get("updated", meta["updated"])

    pubs = apply_overrides(pubs, ov)
    os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
    if not render_only:
        stored = [p for p in pubs if p.get("source") != "manual"]
        with open(JSON_OUT, "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "publications": stored}, f, ensure_ascii=False, indent=1)
    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write(render_markdown(pubs, meta, cfg))
    with open(RECENT_OUT, "w", encoding="utf-8") as f:
        f.write(render_recent(pubs, cfg, cfg.get("n_recent", 5)))
    print(f"Wrote {len(pubs)} publications to _publications.md")


def pubs_equal(a, b):
    strip = lambda ps: sorted(json.dumps({k: v for k, v in p.items() if k != "cited_by"},
                                         sort_keys=True) for p in ps)
    return strip(a) == strip(b)


if __name__ == "__main__":
    main()
