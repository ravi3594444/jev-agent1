"""Feed fetchers. Zero third-party dependencies - stdlib only.

Every fetcher returns a list of Item. `Item.id` is a stable hash so the same
story is never scored twice across runs.
"""
from __future__ import annotations

import gzip
import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

UA = "jev-firehose/1.0 (+feed relevance filter)"
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


def _get(url: str, timeout: float = 25.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


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
def fetch_hn(query: str = "", limit: int = 40, min_points: int = 0, timeout: float = 25.0) -> list[Item]:
    params = {"tags": "story", "hitsPerPage": str(min(limit, 100))}
    if query:
        params["query"] = query
    if min_points:
        params["numericFilters"] = f"points>{min_points}"
    url = "https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(params)
    data = json.loads(_get(url, timeout))
    out: list[Item] = []
    for hit in data.get("hits", []):
        title = hit.get("title") or hit.get("story_title") or ""
        if not title:
            continue
        out.append(
            Item(
                title=title,
                url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                summary=clean_text(hit.get("story_text") or "")[:800],
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
        return fetch_hn(spec.get("query", ""), limit=limit, min_points=int(spec.get("min_points", 0)))
    if kind == "fixture":
        return fetch_fixture(spec["path"], limit=limit, source=spec.get("name", ""))

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


def fetch_stream(stream_id: str, specs: list[dict], limit_per_source: int) -> tuple[list[Item], list[str]]:
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
        for it in got:
            it.stream = stream_id
            if it.id in seen:
                continue
            seen.add(it.id)
            items.append(it)
    return items, warnings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
