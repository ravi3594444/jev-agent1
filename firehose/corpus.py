"""The scored corpus the agent reasons over.

A run writes results to JSONL; the agent loads them back and can also ask Jev
brand-new questions across every item it holds.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class Record:
    id: str
    title: str
    url: str
    summary: str
    source: str
    stream: str
    published: str
    verdict: str
    relevance: float
    certainty: float
    rank: float
    reason: str
    answers: dict[str, Any]

    @property
    def blob(self) -> str:
        return f"{self.title}\n{self.summary}\n{self.source}"

    def brief(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "stream": self.stream,
            "verdict": self.verdict,
            "relevance": self.relevance,
            "certainty": self.certainty,
            "signals": self.reason,
        }

    def full(self) -> dict:
        return {**self.brief(), "published": self.published, "summary": self.summary[:1500],
                "rank": self.rank, "answers": self.answers}


class Corpus:
    def __init__(self, records: list[Record]) -> None:
        self.records = records
        self._by_id = {r.id: r for r in records}

    # -- loading -----------------------------------------------------------
    @classmethod
    def from_jsonl(cls, path: str) -> "Corpus":
        rows: list[Record] = []
        if not os.path.exists(path):
            return cls([])
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                rows.append(
                    Record(
                        id=d.get("id", ""), title=d.get("title", ""), url=d.get("url", ""),
                        summary=d.get("summary", ""), source=d.get("source", ""),
                        stream=d.get("stream", ""), published=d.get("published", ""),
                        verdict=d.get("verdict", ""), relevance=float(d.get("relevance", 0)),
                        certainty=float(d.get("certainty", 0)), rank=float(d.get("rank", 0)),
                        reason=d.get("reason", ""), answers=d.get("answers", {}),
                    )
                )
        return cls(rows)

    # -- access ------------------------------------------------------------
    def get(self, item_id: str) -> Record | None:
        return self._by_id.get(item_id)

    def filter(self, verdict: str | None = None, stream: str | None = None) -> list[Record]:
        out = self.records
        if verdict and verdict != "any":
            out = [r for r in out if r.verdict == verdict]
        if stream and stream != "any":
            out = [r for r in out if r.stream == stream]
        return out

    def search(
        self,
        query: str = "",
        verdict: str | None = None,
        stream: str | None = None,
        limit: int = 12,
    ) -> list[Record]:
        pool = self.filter(verdict, stream)
        if not query.strip():
            return sorted(pool, key=lambda r: r.rank, reverse=True)[:limit]
        terms = [t for t in re.findall(r"[\w+#.-]{2,}", query.lower())]

        def hits(r: Record) -> int:
            blob = r.blob.lower()
            return sum(blob.count(t) for t in terms)

        scored = [(hits(r), r) for r in pool]
        scored = [(h, r) for h, r in scored if h > 0]
        scored.sort(key=lambda hr: (hr[0], hr[1].rank), reverse=True)
        return [r for _, r in scored[:limit]]

    def counts(self) -> dict[str, Any]:
        by_verdict: dict[str, int] = {}
        by_stream: dict[str, int] = {}
        for r in self.records:
            by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
            by_stream[r.stream] = by_stream.get(r.stream, 0) + 1
        return {"total": len(self.records), "by_verdict": by_verdict, "by_stream": by_stream}

    def __len__(self) -> int:
        return len(self.records)
