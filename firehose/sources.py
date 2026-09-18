"""Feed fetchers. Zero third-party dependencies - stdlib only.

Every fetcher returns a list of Item. `Item.id` is a stable hash so the same
story is never scored twice across runs.
"""
from __future__ import annotations

import gzip
import hashlib
import time
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

# Reddit wants a descriptive, non-generic User-Agent and throttles anything that
# looks bot-shaped. This format is what they ask for.
UA = "linux:jev-firehose:1.0 (by /u/ravi3594444)"
TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Item:
    title: str
    url: str
    summary: str = ""
    source: str = ""
    stream: str = ""
    published: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        basis = (self.url or "") + "|" + self.title.strip().lower()
        return hashlib.sha1(basis.encode()).hexdigest()[:16]

    def as_state(self, max_chars: int = 1200) -> str:
        """What we hand Jev. Keep it tight - input tokens are the only billed part."""
        parts = [f"TITLE: {self.title.strip()}"]
        if self.source:
            parts.append(f"SOURCE: {self.source}")
        body = clean_text(self.summary)
        if body:
            parts.append(f"BODY: {body[:max_chars]}")
        if self.url:
            parts.append(f"URL: {self.url}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d


def clean_text(raw: str) -> str:
    if not raw:
        return ""
    txt = TAG_RE.sub(" ", raw)
    txt = html.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def _get(url: str, timeout: float = 25.0, tries: int = 3) -> bytes:
    """GET with backoff on 429/5xx. Reddit hands out 429s freely to anonymous
    traffic, and one retry after a pause usually clears it."""
    delay = 5.0
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            return data
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503) and attempt < tries - 1:
                time.sleep(float(exc.headers.get("Retry-After") or delay))
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


# --------------------------------------------------------------------------
# RSS / Atom
# --------------------------------------------------------------------------
def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def fetch_rss(url: str, limit: int = 40, source: str = "", timeout: float = 25.0) -> list[Item]:
    root = ET.fromstring(_get(url, timeout))
    label = source or urllib.parse.urlparse(url).netloc
    items: list[Item] = []

    # RSS 2.0
    for node in root.iter("item"):
        link = _text(node.find("link"))
        items.append(
            Item(
                title=_text(node.find("title")),
                url=link,
                summary=_text(node.find("description")) or _text(node.find("{*}encoded")),
                source=label,
                published=_text(node.find("pubDate")),
            )
        )
    # Atom
    if not items:
        ns = "{http://www.w3.org/2005/Atom}"
        for node in root.iter(f"{ns}entry"):
            link_el = node.find(f"{ns}link")
            href = link_el.get("href", "") if link_el is not None else ""
            items.append(
                Item(
                    title=_text(node.find(f"{ns}title")),
                    url=href,
                    summary=_text(node.find(f"{ns}summary")) or _text(node.find(f"{ns}content")),
                    source=label,
                    published=_text(node.find(f"{ns}updated")),
                )
            )
    return [i for i in items if i.title][:limit]


# --------------------------------------------------------------------------
# Hacker News (Algolia)
# --------------------------------------------------------------------------
def fetch_hn(query: str = "", limit: int = 40, min_points: int = 0, timeout: float = 25.0,
             tags: str = "story", max_age_days: int = 0) -> list[Item]:
    """`tags="comment"` searches comments - that is where HN's monthly
    "Freelancer? Seeking freelancer?" threads actually live."""
    params = {"tags": tags, "hitsPerPage": str(min(limit, 100))}
    if query:
        params["query"] = query
    numeric = []
    if min_points:
        numeric.append(f"points>{min_points}")
    if max_age_days:
        cutoff = int((datetime.now(timezone.utc) - timedelta(days=max_age_days)).timestamp())
        numeric.append(f"created_at_i>{cutoff}")
    if numeric:
        params["numericFilters"] = ",".join(numeric)
    url = "https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(params)
    data = json.loads(_get(url, timeout))
    out: list[Item] = []
    for hit in data.get("hits", []):
        comment = clean_text(hit.get("comment_text") or "")
        body = comment or clean_text(hit.get("story_text") or "")
        if comment:
            # a comment's own text IS its title - using the parent story title
            # made every reply in a thread look identical
            title = comment[:140]
        else:
            title = hit.get("title") or hit.get("story_title") or body[:110]
        if not title:
            continue
        out.append(
            Item(
                title=title,
                url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                summary=body[:1000],
                source="Hacker News",
                published=hit.get("created_at", ""),
                extra={"points": hit.get("points"), "comments": hit.get("num_comments")},
            )
        )
    return out[:limit]


# --------------------------------------------------------------------------
# local JSON fixtures (offline demo / tests)
# --------------------------------------------------------------------------
def fetch_fixture(path: str, limit: int = 100, source: str = "") -> list[Item]:
    with open(path, encoding="utf-8") as fh:
        rows = json.load(fh)
    return [
        Item(
            title=r["title"],
            url=r.get("url", ""),
            summary=r.get("summary", ""),
            source=r.get("source", source or "fixture"),
            published=r.get("published", ""),
        )
        for r in rows
    ][:limit]


# --------------------------------------------------------------------------
# dispatcher
# --------------------------------------------------------------------------
def fetch(spec: dict, limit: int) -> list[Item]:
    kind = spec.get("type", "rss")
    if kind == "rss":
        return fetch_rss(spec["url"], limit=limit, source=spec.get("name", ""))
    if kind == "hn":
        return fetch_hn(spec.get("query", ""), limit=limit,
                        min_points=int(spec.get("min_points", 0)),
                        tags=spec.get("tags", "story"),
                        max_age_days=int(spec.get("max_age_days", 0)))
    if kind == "fixture":
        return fetch_fixture(spec["path"], limit=limit, source=spec.get("name", ""))
    if kind == "reddit":
        return fetch_reddit(spec.get("subreddit", ""), spec.get("query", ""), limit=limit)
    if kind == "remoteok":
        return fetch_remoteok(spec.get("tags"), limit=limit)
    if kind == "apify":
        import os
        return fetch_apify(
            spec["actor"],
            os.environ.get(spec.get("token_env", "APIFY_TOKEN"), ""),
            actor_input=spec.get("input"),
            limit=limit,
            fields=spec.get("fields"),
            source=spec.get("name", ""),
        )

    # tender boards live in their own module (imported lazily so the RSS/HN path
    # stays dependency-free and fast)
    if kind in {"ted", "fts", "contracts_finder", "sam"}:
        import os

        from . import tenders

        days = int(spec.get("days", 7))
        cpv = spec.get("cpv")
        if kind == "ted":
            return tenders.fetch_ted(limit=limit, days=days, cpv=cpv,
                                     countries=spec.get("countries"))
        if kind == "fts":
            return tenders.fetch_fts(limit=limit, days=days, cpv=cpv)
        if kind == "contracts_finder":
            return tenders.fetch_contracts_finder(limit=limit, days=days, cpv=cpv)
        key = os.environ.get(spec.get("key_env", "SAM_API_KEY"), "")
        return tenders.fetch_sam(key, limit=limit, days=days, naics=spec.get("naics"))

    raise ValueError(f"unknown source type {kind!r}")


def fetch_stream(stream_id: str, specs: list[dict], limit_per_source: int,
                 max_age_days: int = 0) -> tuple[list[Item], list[str]]:
    """Fetch every source in a stream. Returns (items, warnings)."""
    seen: set[str] = set()
    items: list[Item] = []
    warnings: list[str] = []
    for spec in specs:
        label = spec.get("name") or spec.get("url") or spec.get("query") or spec.get("type")
        try:
            got = fetch(spec, limit_per_source)
        except Exception as exc:
            warnings.append(f"{stream_id}: could not fetch {label} ({exc.__class__.__name__}: {exc})")
            continue
        age_limit = int(spec.get("max_age_days", max_age_days) or 0)
        got, stale = drop_stale(got, age_limit)
        if stale:
            warnings.append(f"{stream_id}: skipped {stale} stale item(s) from {label}")
        for it in got:
            it.stream = stream_id
            if it.id in seen:
                continue
            seen.add(it.id)
            items.append(it)
    return items, warnings


def parse_when(value: str) -> datetime | None:
    """Best-effort date parsing across RSS, Atom, ISO and epoch formats."""
    if not value:
        return None
    text = str(value).strip()
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        except (ValueError, OSError):
            return None
    try:
        dt = parsedate_to_datetime(text)          # RFC 822: RSS pubDate
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def drop_stale(items: list[Item], max_age_days: int) -> tuple[list[Item], int]:
    """Remove anything older than the cutoff. Items with no parsable date are
    KEPT - an unknown date is not evidence of staleness, and some feeds omit it."""
    if not max_age_days:
        return items, 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    fresh, dropped = [], 0
    for it in items:
        when = parse_when(it.published)
        if when is not None and when < cutoff:
            dropped += 1
            continue
        fresh.append(it)
    return fresh, dropped


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Freelance / client-work sources
# --------------------------------------------------------------------------
_REDDIT_LAST = 0.0
REDDIT_MIN_GAP = 8.0   # seconds between Reddit requests; 2.5 earned a 429 on 11 of 12


def fetch_reddit(subreddit: str = "", query: str = "", limit: int = 40,
                 timeout: float = 25.0) -> list[Item]:
    """Reddit's .rss endpoints still work unauthenticated.

    They rate-limit anonymous traffic, so a real User-Agent (we send one), a
    slow schedule, and spacing requests all matter. With a dozen Reddit sources
    in one stream, firing them back to back is the quickest way to get a 429,
    so requests are spaced by REDDIT_MIN_GAP.
    """
    global _REDDIT_LAST
    wait = REDDIT_MIN_GAP - (time.monotonic() - _REDDIT_LAST)
    if wait > 0:
        time.sleep(wait)
    _REDDIT_LAST = time.monotonic()

    if subreddit and query:
        url = (f"https://www.reddit.com/r/{subreddit}/search.rss?"
               + urllib.parse.urlencode({"q": query, "restrict_sr": "1", "sort": "new"}))
        label = f"r/{subreddit} ({query})"
    elif subreddit:
        url = f"https://www.reddit.com/r/{subreddit}/new.rss"
        label = f"r/{subreddit}"
    else:
        url = "https://www.reddit.com/search.rss?" + urllib.parse.urlencode(
            {"q": query, "sort": "new"})
        label = f"reddit: {query}"
    return fetch_rss(url, limit=limit, source=label, timeout=timeout)


def fetch_remoteok(tags: list[str] | None = None, limit: int = 40,
                   timeout: float = 25.0) -> list[Item]:
    """RemoteOK's free JSON feed. First array element is a legal notice, not a job.

    Their terms ask that aggregators credit RemoteOK and link to the original
    post, which is what `url` below does.
    """
    url = "https://remoteok.com/api"
    if tags:
        url += "?" + urllib.parse.urlencode({"tags": ",".join(tags)})
    rows = json.loads(_get(url, timeout))
    out: list[Item] = []
    for row in rows:
        if not isinstance(row, dict) or "legal" in row or not row.get("position"):
            continue
        company = row.get("company") or ""
        bits = [clean_text(row.get("description") or "")[:900]]
        if company:
            bits.insert(0, f"Company: {company}")
        if row.get("tags"):
            bits.append("Tags: " + ", ".join(str(t) for t in row["tags"][:10]))
        if row.get("salary_min"):
            bits.append(f"Salary: {row.get('salary_min')}-{row.get('salary_max')}")
        out.append(Item(
            title=clean_text(f"{row['position']}" + (f" at {company}" if company else "")),
            url=row.get("url") or row.get("apply_url") or "",
            summary=" · ".join(b for b in bits if b)[:1200],
            source="RemoteOK",
            published=str(row.get("date") or ""),
            extra={"company": company, "tags": row.get("tags")},
        ))
        if len(out) >= limit:
            break
    return out


def fetch_apify(
    actor: str,
    token: str,
    actor_input: dict | None = None,
    limit: int = 40,
    fields: dict[str, list[str]] | None = None,
    source: str = "",
    timeout: float = 180.0,
) -> list[Item]:
    """Run any Apify actor and turn its dataset rows into Items.

    Deliberately generic: every actor emits a different shape, so `fields` maps
    our three slots onto candidate keys and we take the first that exists.

    Note the timeout - actors are minutes, not milliseconds, unlike every other
    source here. And they cost money per run, so schedule accordingly.
    """
    if not token:
        raise RuntimeError("Apify needs a token - set APIFY_TOKEN")
    url = (f"https://api.apify.com/v2/acts/{urllib.parse.quote(actor, safe='')}"
           f"/run-sync-get-dataset-items?" + urllib.parse.urlencode({"token": token, "limit": limit}))
    req = urllib.request.Request(
        url,
        data=json.dumps(actor_input or {}).encode(),
        method="POST",
        headers={"User-Agent": UA, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rows = json.loads(r.read())

    picks = fields or {}
    title_keys = picks.get("title", ["title", "text", "caption", "name", "fullText", "content"])
    url_keys = picks.get("url", ["url", "link", "postUrl", "permalink", "twitterUrl"])
    text_keys = picks.get("text", ["text", "fullText", "caption", "description", "content", "body"])

    def first(row: dict, keys: list[str]) -> str:
        for k in keys:
            v = row.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return ""

    out: list[Item] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        body = clean_text(first(row, text_keys))
        title = clean_text(first(row, title_keys)) or body[:110]
        if not title:
            continue
        author = row.get("authorName") or row.get("username") or row.get("ownerUsername") or ""
        out.append(Item(
            title=title[:300],
            url=first(row, url_keys),
            summary=(f"Author: {author} · " if author else "") + body[:1100],
            source=source or f"Apify/{actor}",
            published=str(row.get("timestamp") or row.get("createdAt") or row.get("date") or ""),
            extra={"actor": actor, "author": author},
        ))
        if len(out) >= limit:
            break
    return out
