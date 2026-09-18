"""Fetch -> score -> gate. Plain Python on purpose.

This half is an embarrassingly parallel map over items: no branches, no cycles,
no state carried between items. A graph framework would add per-item overhead to
an operation whose whole selling point is ~100ms, so it stays a straight loop.
The agent half is where LangGraph earns its keep.

The gating is the part that matters. Jev returns calibrated confidence, so:
    high relevance AND confident   -> KEEP   (show me)
    borderline, or not confident   -> REVIEW (I'll glance at these)
    low relevance AND confident    -> DROP   (never shown)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from . import questions as qsets
from .jev import RunStats, certainty, level_label, make_classifier, score_fraction
from .sources import Item, fetch_stream, now_iso

KEEP, REVIEW, DROP = "keep", "review", "drop"


@dataclass
class Result:
    item: Item
    verdict: str
    relevance: float
    certainty: float
    rank: float
    answers: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            **self.item.to_dict(),
            "verdict": self.verdict,
            "relevance": round(self.relevance, 3),
            "certainty": round(self.certainty, 3),
            "rank": round(self.rank, 3),
            "reason": self.reason,
            "error": self.error,
            "answers": {
                k: (v.model_dump(mode="json") if hasattr(v, "model_dump") else v)
                for k, v in self.answers.items()
            },
        }


class SeenStore:
    """Remembers item ids across runs so nothing is fetched or paid for twice."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.seen: dict[str, str] = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    self.seen = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self.seen = {}

    def is_new(self, item_id: str) -> bool:
        return item_id not in self.seen

    def mark(self, item_id: str) -> None:
        self.seen.setdefault(item_id, now_iso())

    def save(self, keep_last: int = 20000) -> None:
        if len(self.seen) > keep_last:
            newest = sorted(self.seen.items(), key=lambda kv: kv[1], reverse=True)[:keep_last]
            self.seen = dict(newest)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.seen, fh, indent=0)


def describe(answers: dict[str, Any]) -> str:
    """Human line assembled from typed answers. No model writes this text."""
    bits: list[str] = []
    for qid, a in answers.items():
        if qid == "relevant":
            continue
        kind = getattr(a, "type", None)
        if kind == "choice":
            bits.append(f"{qid}: {a.choice} ({a.confidence:.0%})")
        elif kind == "score":
            bits.append(f"{qid}: {level_label(a)}")
        elif kind == "noul":
            p = float(a.noul)
            bits.append(f"{qid}: yes ({p:.0%})" if p >= 0.6 else
                        f"{qid}: no ({1 - p:.0%})" if p <= 0.4 else f"{qid}: unclear")
    return " · ".join(bits)


def gate(answers: dict[str, Any], gates: dict) -> tuple[str, float, float, float]:
    """Return (verdict, relevance, certainty, rank)."""
    rel = answers.get("relevant")
    p = float(getattr(rel, "noul", 0.0)) if rel is not None else 0.0
    cert = certainty(rel)

    keep_at = float(gates.get("keep", 0.72))
    drop_at = float(gates.get("drop", 0.45))
    min_cert = float(gates.get("min_certainty", 0.60))

    if cert < min_cert:
        verdict = REVIEW           # not sure enough to act either way
    elif p >= keep_at:
        verdict = KEEP
    elif p < drop_at:
        verdict = DROP
    else:
        verdict = REVIEW

    # a configured "dead" label (an already-awarded contract, say) can never be a
    # silent KEEP - it drops to REVIEW so a wrong call is still recoverable
    demote: dict[str, list[str]] = gates.get("demote_choices", {}) or {}
    for qid, labels in demote.items():
        a = answers.get(qid)
        if a is not None and getattr(a, "type", None) == "choice" \
                and a.choice in labels and float(a.confidence) >= min_cert \
                and verdict == KEEP:
            verdict = REVIEW

    # a label that disqualifies the item outright, however relevant it looked -
    # a freelancer advertising themselves is not a client, at any score
    reject: dict[str, list[str]] = gates.get("drop_choices", {}) or {}
    for qid, labels in reject.items():
        a = answers.get(qid)
        if a is not None and getattr(a, "type", None) == "choice" and a.choice in labels:
            verdict = DROP if float(a.confidence) >= min_cert else REVIEW

    quality, weight = 0.0, 0.0
    for qid in ("fit", "importance"):
        a = answers.get(qid)
        if a is not None:
            conf = float(getattr(a, "confidence", 0.5) or 0.5)
            quality += score_fraction(a) * conf
            weight += conf
    quality = quality / weight if weight else 0.5

    boost = 0.0
    for qid in ("time_sensitive", "actionable"):
        a = answers.get(qid)
        if a is not None:
            boost += (float(a.noul) - 0.5) * 0.12

    return verdict, p, cert, p * 0.55 + quality * 0.45 + boost


def run_stream(
    stream_id: str,
    stream_cfg: dict,
    gates: dict,
    backend: str = "aimlapi",
    limit_per_source: int = 40,
    seen: SeenStore | None = None,
    workers: int = 8,
    mock: bool = False,
    stats: RunStats | None = None,
    timeout: float = 60.0,
) -> tuple[list[Result], list[str]]:
    items, warnings = fetch_stream(
        stream_id, stream_cfg.get("sources", []), limit_per_source,
        max_age_days=int(stream_cfg.get("max_age_days", 0) or 0),
    )

    if seen is not None:
        fresh = [i for i in items if seen.is_new(i.id)]
        skipped = len(items) - len(fresh)
        if skipped:
            warnings.append(f"{stream_id}: skipped {skipped} already scored in an earlier run")
        items = fresh

    if not items:
        return [], warnings

    qs = qsets.build(stream_cfg.get("question_set", "tech"), stream_cfg)
    clf = make_classifier(qs, backend=backend, mock=mock, timeout=timeout)

    stats = stats or RunStats()
    started = time.perf_counter()
    try:
        # return_exceptions keeps one slow or failed call from costing the whole
        # run - a single timeout loses that item, not the stream
        responses = clf.batch(
            [i.as_state() for i in items],
            config={"max_concurrency": max(1, workers)},
            return_exceptions=True,
        )
    except Exception as exc:
        warnings.append(f"{stream_id}: scoring failed ({exc.__class__.__name__}: {exc})")
        return [], warnings
    elapsed = (time.perf_counter() - started) * 1000
    stats.wall_ms += elapsed
    stats.latencies_ms.append(elapsed / max(len(items), 1))

    results: list[Result] = []
    failed: list[str] = []
    for item, resp in zip(items, responses):
        if isinstance(resp, BaseException):
            # not marked as seen, so the next run retries it rather than losing it
            failed.append(f"{resp.__class__.__name__}")
            stats.errors += 1
            continue
        stats.add(resp)
        answers = resp.answers
        verdict, p, cert, rank = gate(answers, gates)
        results.append(Result(item=item, verdict=verdict, relevance=p, certainty=cert,
                              rank=rank, answers=answers, reason=describe(answers)))
        if seen is not None:
            seen.mark(item.id)

    if failed:
        kinds = ", ".join(sorted(set(failed)))
        warnings.append(
            f"{stream_id}: {len(failed)} of {len(items)} item(s) could not be scored "
            f"({kinds}) - they stay unseen and will be retried next run"
        )

    results.sort(key=lambda r: r.rank, reverse=True)
    return results, warnings
