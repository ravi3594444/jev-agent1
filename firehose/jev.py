"""The Jev layer, built on the official `langchain-typesafe` integration.

Why this file exists at all when the package does the work:

  * Your key is from AI/ML API, which hosts Jev at `/v1/decisions`.
    `TypeSafeClassifier` hardcodes `/v1/systemone`, so we subclass and swap the
    path. Everything else - payload shape, response validation, LangSmith
    tracing - comes from the package unchanged.
  * A `--mock` classifier so the whole pipeline runs offline with no key.
  * Two helpers (`certainty`, `score_fraction`) that turn typed answers into the
    single comparable number the gating needs.

Question types (Noul / Choice / Score) are re-exported straight from the
package - we do not redefine them.
"""
from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from langchain_typesafe import (  # re-exported for the rest of the app
    Choice,
    ChoiceAnswer,
    Noul,
    NoulAnswer,
    NoulCriteria,
    Score,
    ScoreAnswer,
    TypeSafeClassifier,
)
from langchain_typesafe.types import ClassificationResponse, Usage

__all__ = [
    "Choice", "Noul", "NoulCriteria", "Score",
    "certainty", "score_fraction", "make_classifier", "MockClassifier",
    "PRICE_PER_MTOK_IN", "RunStats", "noul", "choice", "score",
]

# Jev bills input tokens only. Output is free.
PRICE_PER_MTOK_IN = 0.042

BACKENDS = {
    "aimlapi": {
        "base_url": "https://api.aimlapi.com",
        "path": "/v1/decisions",
        "model": "typesafe/jev",
        "key_envs": ["AIMLAPI_API_KEY", "AIML_API_KEY"],
    },
    "typesafe": {
        "base_url": "https://api.typesafe.ai",
        "path": "/v1/systemone",
        "model": "jev-latest",
        "key_envs": ["TYPESAFE_API_KEY"],
    },
}


class AimlapiClassifier(TypeSafeClassifier):
    """Jev via AI/ML API. Identical payload, different route."""

    @property
    def _endpoint(self) -> str:  # type: ignore[override]
        return f"{self.base_url.rstrip('/')}/v1/decisions"


# --------------------------------------------------------------------------
# convenience builders (thin wrappers so config stays plain dicts/lists)
# --------------------------------------------------------------------------
def noul(instructions: str, true_desc: Any = None, false_desc: Any = None) -> Noul:
    crit = NoulCriteria(true=true_desc, false=false_desc) if (true_desc or false_desc) else None
    return Noul(instructions=instructions, criteria=crit)


def choice(instructions: str, criteria: dict[str, Any]) -> Choice:
    return Choice(instructions=instructions, criteria=criteria)


def score(instructions: str, levels: list[Any]) -> Score:
    return Score(instructions=instructions, criteria=levels)


# --------------------------------------------------------------------------
# answer helpers
# --------------------------------------------------------------------------
def certainty(answer: Any) -> float:
    """One comparable 0..1 certainty for any answer type.

    Choice and Score carry a calibrated `confidence`. Noul deliberately does not,
    so we use distance from the coin flip: 0.5 -> 0.0, 0.0 or 1.0 -> 1.0.
    """
    if answer is None:
        return 0.0
    if isinstance(answer, NoulAnswer) or getattr(answer, "type", None) == "noul":
        return abs(float(answer.noul) - 0.5) * 2.0
    return float(getattr(answer, "confidence", 0.0) or 0.0)


def score_fraction(answer: Any) -> float:
    """Normalise a Score answer to 0..1 whatever its number of levels."""
    if answer is None:
        return 0.0
    legend = getattr(answer, "legend", None) or {}
    top = max(len(legend) - 1, 1)
    return min(max(float(getattr(answer, "score", 0.0)) / top, 0.0), 1.0)


def level_label(answer: Any) -> str:
    legend = getattr(answer, "legend", None) or {}
    if not legend:
        return f"{getattr(answer, 'score', 0):.2f}"
    idx = int(round(float(answer.score)))
    idx = min(max(idx, min(legend)), max(legend))
    return str(legend.get(idx, idx))


# --------------------------------------------------------------------------
# run statistics
# --------------------------------------------------------------------------
@dataclass
class RunStats:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    errors: int = 0
    wall_ms: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)

    def add(self, resp: ClassificationResponse) -> None:
        self.calls += 1
        u: Usage = resp.usage
        self.input_tokens += int(u.input_tokens or 0)
        self.output_tokens += int(u.output_tokens or 0)

    @property
    def cost_usd(self) -> float:
        return self.input_tokens / 1_000_000 * PRICE_PER_MTOK_IN

    @property
    def mean_ms(self) -> float:
        return sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0.0


# --------------------------------------------------------------------------
# offline mock
# --------------------------------------------------------------------------
class MockClassifier:
    """Set-cosine heuristic that mimics the classifier interface.

    Not an emulation of Jev - it exists only so the pipeline can be run and
    inspected end to end before a key is wired in. It scores an item by how much
    it leans toward the `true` criteria versus the `false` criteria, which is the
    one property that makes the gating demo behave sensibly offline.

    Duck-types `.invoke()` and `.batch()` so nothing downstream knows the difference.
    """

    STOP = frozenset("""
    the and for with that this from are was were has have had not but you your our their its
    into over under about after before their there here which when where what who whom whose
    all any both each few more most other some such only own same than too very can will just
    should now also may might must would could been being does did doing they them his her she
    him out off down while these those then once because until against between during through
    """.split())

    def __init__(self, questions: dict[str, Any]) -> None:
        self.questions = questions
        self.model = "typesafe/jev (mock)"

    @classmethod
    def _terms(cls, blob: Any) -> set[str]:
        toks = re.findall(r"[a-z][a-z0-9+#.-]{2,}", str(blob).lower())
        return {t for t in toks if t not in cls.STOP}

    @staticmethod
    def _cosine(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / (len(a) * len(b)) ** 0.5

    @staticmethod
    def _sigmoid(x: float) -> float:
        import math
        return 1.0 / (1.0 + math.exp(-x))

    def invoke(self, state: Any, config: Any = None, **_: Any) -> ClassificationResponse:
        text = str(state)
        words = self._terms(text)
        rng = random.Random(int(hashlib.sha256(text.encode()).hexdigest()[:8], 16))
        sim = lambda blob: self._cosine(words, self._terms(blob))

        answers: dict[str, Any] = {}
        for qid, q in self.questions.items():
            kind = getattr(q, "type", None)
            hint = str(getattr(q, "instructions", ""))
            if kind == "noul":
                crit = getattr(q, "criteria", None)
                pos = getattr(crit, "true", None) if crit else None
                neg = getattr(crit, "false", None) if crit else None
                # contrast between the two sides is what discriminates
                s_pos = sim(pos if pos else hint)
                s_neg = sim(neg if neg else "")
                # with little lexical evidence either way, sit near 0.5 on purpose:
                # that is what turns into a low-certainty REVIEW downstream
                evidence = min(1.0, max(s_pos, s_neg) / 0.12)
                lean = (s_pos - s_neg) * evidence
                p = self._sigmoid(lean * 30.0 + rng.uniform(-0.15, 0.15))
                answers[qid] = NoulAnswer(type="noul", noul=round(min(0.985, max(0.015, p)), 3))
            elif kind == "choice":
                crit = dict(getattr(q, "criteria", {}) or {})
                raw = {k: sim(f"{k} {v or ''}") for k, v in crit.items()}
                exp = {k: pow(2.718281828, v * 30.0 + rng.uniform(-0.15, 0.15)) for k, v in raw.items()}
                total = sum(exp.values()) or 1.0
                probs = {k: round(v / total, 4) for k, v in exp.items()}
                best = max(probs, key=probs.get)
                ranked = sorted(probs.values(), reverse=True)
                spread = ranked[0] - (ranked[1] if len(ranked) > 1 else 0.0)
                answers[qid] = ChoiceAnswer(
                    type="choice", choice=best, probabilities=probs,
                    confidence=round(min(0.98, max(0.30, 0.42 + spread * 1.4)), 3),
                )
            elif kind == "score":
                levels = [str(x) for x in (getattr(q, "criteria", []) or [])]
                top = max(len(levels) - 1, 1)
                sims = [sim(lv) for lv in levels]
                weight = sum(sims) or 1.0
                val = sum(i * s for i, s in enumerate(sims)) / weight
                val = min(float(top), max(0.0, val + rng.uniform(-0.25, 0.25)))
                probs = {i: round((s / weight) if weight else 1 / len(levels), 4)
                         for i, s in enumerate(sims)}
                answers[qid] = ScoreAnswer(
                    type="score", score=round(val, 3),
                    legend={i: lv for i, lv in enumerate(levels)},
                    probabilities=probs,
                    confidence=round(min(0.97, max(0.35, 0.45 + max(sims) * 12)), 3),
                )
        return ClassificationResponse(
            model=self.model,
            answers=answers,
            usage=Usage(input_tokens=max(1, len(text) // 4), output_tokens=0),
        )

    def batch(self, states: Iterable[Any], config: Any = None, **_: Any) -> list[ClassificationResponse]:
        return [self.invoke(s) for s in states]


# --------------------------------------------------------------------------
# factory
# --------------------------------------------------------------------------
def make_classifier(
    questions: dict[str, Any],
    backend: str = "aimlapi",
    model: str | None = None,
    api_key: str | None = None,
    timeout: float = 30.0,
    mock: bool = False,
) -> Any:
    """Return something with `.invoke(state)` and `.batch(states)`."""
    import os

    if mock:
        return MockClassifier(questions)
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}; pick one of {sorted(BACKENDS)}")
    cfg = BACKENDS[backend]

    if api_key is None:
        for env in cfg["key_envs"]:
            if os.environ.get(env):
                api_key = os.environ[env]
                break
    if not api_key:
        raise RuntimeError(
            f"no API key for backend {backend!r}; set one of {cfg['key_envs']} "
            f"or run with --mock"
        )

    cls = AimlapiClassifier if backend == "aimlapi" else TypeSafeClassifier
    return cls(
        questions=questions,
        model=model or cfg["model"],
        api_key=api_key,
        base_url=cfg["base_url"],
        timeout=timeout,
    )
