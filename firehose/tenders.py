"""Tender-board fetchers: TED (EU), UK FTS, UK Contracts Finder, SAM.gov (US).

All stdlib. Each returns `Item`s in the same shape as the RSS/HN fetchers.

Verified behaviour that drives the odd-looking code below:
  * TED is POST-with-JSON-body, keyless, and filters CPV server-side. Its text
    fields are multilingual dicts ({"eng": "..."}), not strings - that is the
    single biggest source of crashes.
  * The two UK services are keyless OCDS release packages, cursor-paginated,
    with NO server-side CPV filter - we pull a date window and filter locally.
    Contracts Finder signals rate limiting with 403, not 429. Honour Retry-After.
  * SAM.gov needs a free key, requires postedFrom/postedTo as MM/dd/yyyy, and
    misspells the deadline field as `reponseDeadLine`. Its `description` is a URL
    that would cost another call per notice, so we do not follow it.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from .sources import UA, Item, clean_text

# CPV families worth watching for technical-services work.
# CPV is hierarchical and TED does NOT expand parents, so these are enumerated.
DEFAULT_CPV = [
    "72000000",  # IT services: consulting, software development, internet, support
    "72200000",  # software programming and consultancy
    "72300000",  # data services
    "72500000",  # computer-related services
    "72600000",  # computer support and consultancy
    "48000000",  # software packages and information systems
]

# NAICS equivalents for SAM.gov (one call each - the API takes a single ncode)
DEFAULT_NAICS = ["541511", "541512"]


def _json_get(url: str, timeout: float = 30.0, tries: int = 4) -> Any:
    """GET JSON, honouring Retry-After. Contracts Finder uses 403 for throttling."""
    delay = 2.0
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429, 503) and attempt < tries - 1:
                wait = float(exc.headers.get("Retry-After") or delay)
                time.sleep(min(wait, 60.0))
                delay *= 2
                continue
            raise
        except urllib.error.URLError:
            if attempt < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def _json_post(url: str, payload: dict, timeout: float = 30.0, tries: int = 4) -> Any:
    delay = 2.0
    for attempt in range(tries):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429, 503) and attempt < tries - 1:
                time.sleep(min(float(exc.headers.get("Retry-After") or delay), 60.0))
                delay *= 2
                continue
            raise
        except urllib.error.URLError:
            if attempt < tries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def _lang(value: Any, prefer: str = "eng") -> str:
    """TED text fields are {"eng": "..."} or {"eng": ["..."]} - flatten defensively."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_lang(v, prefer) for v in value if v)
    if isinstance(value, dict):
        for key in (prefer, "en", "eng"):
            if key in value:
                return _lang(value[key], prefer)
        for v in value.values():
            got = _lang(v, prefer)
            if got:
                return got
    return str(value)


def _since(days: int) -> date:
    return date.today() - timedelta(days=max(1, days))


# --------------------------------------------------------------------------
# TED - EU. POST, keyless, server-side CPV.
# --------------------------------------------------------------------------
TED_URL = "https://api.ted.europa.eu/v3/notices/search"


def fetch_ted(
    limit: int = 40,
    days: int = 7,
    cpv: list[str] | None = None,
    countries: list[str] | None = None,
    timeout: float = 30.0,
) -> list[Item]:
    codes = cpv or DEFAULT_CPV
    clause = " OR ".join(f"classification-cpv={c}" for c in codes)
    query = f"({clause}) AND publication-date>={_since(days).strftime('%Y%m%d')}"
    if countries:
        query += " AND (" + " OR ".join(f"buyer-country={c}" for c in countries) + ")"
    query += " SORT BY publication-date DESC"

    payload = {
        "query": query,
        "fields": ["publication-number", "notice-title", "description-lot", "publication-date",
                   "deadline", "buyer-name", "buyer-country", "classification-cpv", "notice-type"],
        "page": 1,
        "limit": min(limit, 100),
        "scope": "ACTIVE",
        "paginationMode": "PAGE_NUMBER",
    }
    data = _json_post(TED_URL, payload, timeout=timeout)

    out: list[Item] = []
    for n in (data.get("notices") or [])[:limit]:
        pub = str(n.get("publication-number") or "")
        title = _lang(n.get("notice-title"))
        if not title:
            continue
        buyer = _lang(n.get("buyer-name"))
        desc = _lang(n.get("description-lot"))
        deadline = _lang(n.get("deadline"))
        bits = [b for b in (desc, f"Buyer: {buyer}" if buyer else "",
                            f"Deadline: {deadline}" if deadline else "",
                            f"Country: {_lang(n.get('buyer-country'))}") if b]
        out.append(Item(
            title=clean_text(title),
            url=f"https://ted.europa.eu/en/notice/{pub}" if pub else "",
            summary=clean_text(" · ".join(bits))[:1200],
            source="TED (EU)",
            published=str(n.get("publication-date") or ""),
            extra={"publication_number": pub, "deadline": deadline, "buyer": buyer},
        ))
    return out


# --------------------------------------------------------------------------
# UK - OCDS release packages. Same shape for both services.
# --------------------------------------------------------------------------
FTS_URL = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
CF_URL = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"


def _cpv_matches(tender: dict, prefixes: tuple[str, ...]) -> bool:
    """Neither UK service filters CPV server-side, so we do it here."""
    if not prefixes:
        return True
    pools: list[dict] = []
    if isinstance(tender.get("classification"), dict):
        pools.append(tender["classification"])
    pools.extend(c for c in (tender.get("additionalClassifications") or []) if isinstance(c, dict))
    for it in tender.get("items") or []:
        if isinstance(it, dict):
            if isinstance(it.get("classification"), dict):
                pools.append(it["classification"])
            pools.extend(c for c in (it.get("additionalClassifications") or []) if isinstance(c, dict))
    for c in pools:
        cid = str(c.get("id") or "")
        if cid.startswith(prefixes):
            return True
    return False


def _ocds_items(
    base: str,
    params: dict[str, str],
    limit: int,
    source: str,
    notice_url: str,
    cpv_prefixes: tuple[str, ...],
    timeout: float,
    max_pages: int = 5,
) -> list[Item]:
    url = base + "?" + urllib.parse.urlencode(params)
    out: list[Item] = []
    pages = 0
    while url and pages < max_pages and len(out) < limit:
        data = _json_get(url, timeout=timeout)
        pages += 1
        for rel in data.get("releases") or []:
            tender = rel.get("tender") or {}
            title = tender.get("title") or rel.get("description") or ""
            if not title or not _cpv_matches(tender, cpv_prefixes):
                continue
            buyer = ((rel.get("buyer") or {}).get("name")) or ""
            deadline = ((tender.get("tenderPeriod") or {}).get("endDate")) or ""
            value = tender.get("value") or {}
            link = ""
            for l in rel.get("links") or []:
                if isinstance(l, dict) and l.get("rel") == "canonical":
                    link = l.get("href", "")
                    break
            if not link:
                for d in tender.get("documents") or []:
                    href = (d or {}).get("url", "")
                    if notice_url.split("//")[-1].split("/")[0] in href:
                        link = href
                        break
            if not link and rel.get("id"):
                link = f"{notice_url}{rel['id']}"
            bits = [clean_text(tender.get("description") or "")]
            if buyer:
                bits.append(f"Buyer: {buyer}")
            if deadline:
                bits.append(f"Deadline: {deadline}")
            if value.get("amount"):
                bits.append(f"Value: {value.get('amount')} {value.get('currency', '')}".strip())
            out.append(Item(
                title=clean_text(title),
                url=link,
                summary=" · ".join(b for b in bits if b)[:1200],
                source=source,
                published=str(tender.get("datePublished") or rel.get("date") or ""),
                extra={"ocid": rel.get("ocid"), "deadline": deadline, "buyer": buyer,
                       "value": value.get("amount")},
            ))
            if len(out) >= limit:
                break
        url = ((data.get("links") or {}).get("next")) or ""
    return out[:limit]


def fetch_fts(limit: int = 40, days: int = 7, cpv: list[str] | None = None,
              timeout: float = 30.0) -> list[Item]:
    """UK Find a Tender (above-threshold). Dates must be exactly 19 chars, no Z."""
    start = _since(days).strftime("%Y-%m-%dT00:00:00")
    end = date.today().strftime("%Y-%m-%dT23:59:59")
    prefixes = tuple(c[:2] for c in (cpv or DEFAULT_CPV))
    return _ocds_items(
        FTS_URL,
        {"updatedFrom": start, "updatedTo": end, "limit": "100", "stages": "tender"},
        limit, "UK Find a Tender",
        "https://www.find-tender.service.gov.uk/Notice/", prefixes, timeout,
    )


def fetch_contracts_finder(limit: int = 40, days: int = 7, cpv: list[str] | None = None,
                           timeout: float = 30.0) -> list[Item]:
    """UK Contracts Finder (below-threshold / England-centric). 403 means throttled."""
    start = _since(days).strftime("%Y-%m-%dT00:00:00")
    end = date.today().strftime("%Y-%m-%dT23:59:59")
    prefixes = tuple(c[:2] for c in (cpv or DEFAULT_CPV))
    return _ocds_items(
        CF_URL,
        {"publishedFrom": start, "publishedTo": end, "limit": "100", "stages": "tender"},
        limit, "UK Contracts Finder",
        "https://www.contractsfinder.service.gov.uk/Notice/", prefixes, timeout,
    )


# --------------------------------------------------------------------------
# SAM.gov - US federal. Free key required.
# --------------------------------------------------------------------------
SAM_URLS = [
    "https://api.sam.gov/opportunities/v2/search",
    "https://api.sam.gov/prod/opportunities/v2/search",  # the docs disagree; try both
]


def fetch_sam(
    api_key: str,
    limit: int = 40,
    days: int = 7,
    naics: list[str] | None = None,
    timeout: float = 30.0,
) -> list[Item]:
    if not api_key:
        raise RuntimeError("SAM.gov needs a free API key - set SAM_API_KEY (sam.gov > Account Details)")
    posted_from = _since(days).strftime("%m/%d/%Y")
    posted_to = date.today().strftime("%m/%d/%Y")
    out: list[Item] = []
    seen: set[str] = set()

    for code in (naics or DEFAULT_NAICS):
        params = {
            "api_key": api_key,
            "postedFrom": posted_from,
            "postedTo": posted_to,
            "limit": str(min(limit, 100)),
            "offset": "0",
            "ncode": code,
        }
        qs = urllib.parse.urlencode(params)
        data = None
        last_err: Exception | None = None
        for base in SAM_URLS:
            try:
                data = _json_get(f"{base}?{qs}", timeout=timeout, tries=2)
                break
            except urllib.error.HTTPError as exc:
                last_err = exc
                if exc.code == 404:
                    continue          # wrong base path - try the other
                raise
        if data is None:
            raise RuntimeError(f"SAM.gov unreachable on both documented paths: {last_err}")

        for n in data.get("opportunitiesData") or []:
            nid = str(n.get("noticeId") or "")
            if not nid or nid in seen:
                continue
            seen.add(nid)
            # `description` is a URL needing another authenticated call - skip it and
            # build the summary from the structured fields we already have.
            deadline = n.get("reponseDeadLine") or ""   # sic: misspelled upstream
            buyer = n.get("fullParentPathName") or ""
            bits = [f"Buyer: {buyer.replace('.', ' > ')}" if buyer else "",
                    f"Type: {n.get('type', '')}",
                    f"NAICS {code}",
                    f"Deadline: {deadline}" if deadline else "",
                    f"Set-aside: {n.get('typeOfSetAside')}" if n.get("typeOfSetAside") else ""]
            out.append(Item(
                title=clean_text(n.get("title") or ""),
                url=n.get("uiLink") or "",
                summary=" · ".join(b for b in bits if b)[:1200],
                source="SAM.gov (US federal)",
                published=str(n.get("postedDate") or ""),
                extra={"notice_id": nid, "deadline": deadline, "naics": code,
                       "solicitation": n.get("solicitationNumber")},
            ))
            if len(out) >= limit:
                return out
    return out
