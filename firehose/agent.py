"""The agent half: LangGraph + Atria, with Jev as its senses.

Division of labour, which is the whole point of pairing these two models:

    Jev    - 0.1s, $0.042/MTok, typed answers with calibrated confidence.
             Used to LOOK at things. Can look at the entire corpus on a whim.
    Atria  - reasons, plans, and writes the prose Jev structurally cannot.
             Used to THINK and to TALK.

The interesting tool is `ask_jev`: the agent can invent a brand-new typed
question at conversation time and run it across every stored item in one batch.
Asking "which of these mention a deadline inside 30 days?" over 300 items costs
a fraction of a cent and comes back in about a second. That is not a thing you
would ever do with a chat model in the loop.
"""
from __future__ import annotations

import json
import os
from typing import Any

from langchain.agents import create_agent
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from .corpus import Corpus
from .jev import certainty, choice, level_label, make_classifier, noul, score, score_fraction

ATRIA_BASE = "https://api.atria-asi.ai/v1"
ATRIA_MODEL = "Atria-Dawn-Preview"  # case-sensitive per Atria docs

SYSTEM_PROMPT = """You are the analyst sitting on top of a filtered firehose.

A fast decision model (Jev) has already read every incoming item and assigned
typed, calibrated judgements: a relevance probability, a confidence, and
per-stream signals (fit / importance / category / deadline). Verdicts are:
  keep   - relevant and the model was confident
  review - borderline, or the model was not confident enough to call it
  drop   - not relevant, confidently

Your job is the part Jev structurally cannot do: explain, compare, prioritise,
and write.

Working rules:
- Always ground claims in actual items. Cite them as [title](url).
- Prefer `search_items` first. Use `get_item` when you need the detail.
- When the user asks something the stored signals do not answer, do not guess
  and do not read every item yourself - use `ask_jev` to ask a NEW typed
  question across the corpus. It is near-instant and nearly free.
- Confidence is meaningful. Say when the model was unsure rather than papering
  over it, and treat `review` items as genuinely uncertain, not as weak keeps.
- Be concise and concrete. No filler, no restating the question."""


# --------------------------------------------------------------------------
# demo model - lets the whole stack run with no keys at all
# --------------------------------------------------------------------------
class DemoChatModel(BaseChatModel):
    """A scripted stand-in for Atria so the UI can be run without any key.

    It makes exactly one real tool call (so the tool card and the Jev round trip
    are genuinely exercised) and then writes a short answer assembled from that
    tool's actual output. It does no reasoning. It is a demo, and it says so.
    """

    @property
    def _llm_type(self) -> str:
        return "firehose-demo"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "DemoChatModel":
        return self

    @staticmethod
    def _plan(messages: list[BaseMessage]) -> AIMessage:
        # only look at THIS turn: with a checkpointer the history carries tool
        # results from earlier turns, which would make the demo skip its tool call
        start = 0
        for i, m in enumerate(messages):
            if getattr(m, "type", "") == "human":
                start = i
        turn = messages[start:]
        human = str(messages[start].content) if messages else ""
        tool_results = [m for m in turn if isinstance(m, ToolMessage)]

        if not tool_results:
            wants_jev = any(w in human.lower() for w in
                            ("deadline", "date", "soon", "which", "any ", "mention"))
            if wants_jev:
                call = {"name": "ask_jev", "id": "demo-1", "args": {
                    "question": f"This item is relevant to: {human[:160]}",
                    "kind": "noul", "verdict": "any", "limit": 40}}
            else:
                call = {"name": "search_items", "id": "demo-1", "args": {
                    "query": "", "verdict": "keep", "limit": 6}}
            return AIMessage(content="", tool_calls=[call])

        payload = tool_results[-1].content
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
        except json.JSONDecodeError:
            data = payload

        lines = ["**Demo mode** - no `ATRIA_API_KEY` is set, so this reply is assembled "
                 "mechanically rather than written by a model. The tool call above was real.\n"]
        if isinstance(data, list):
            lines.append(f"Jev kept {len(data)} item(s) worth your attention:\n")
            for row in data[:6]:
                title = row.get("title", "untitled")
                url = row.get("url") or ""
                rel = row.get("relevance")
                cert = row.get("certainty")
                bullet = f"- [{title}]({url})" if url else f"- {title}"
                if rel is not None and cert is not None:
                    bullet += f" — relevance {rel:.2f}, confidence {cert:.2f}"
                lines.append(bullet)
        elif isinstance(data, dict) and "asked" in data:
            lines.append(
                f"Asked Jev a fresh question across **{data.get('asked')}** items for "
                f"**${float(data.get('cost_usd') or 0):.6f}**. Summary: "
                f"`{json.dumps(data.get('summary', {}))}`.\n")
            for row in (data.get("results") or [])[:5]:
                title = row.get("title", "untitled")
                url = row.get("url") or ""
                p = row.get("probability")
                bullet = f"- [{title}]({url})" if url else f"- {title}"
                if p is not None:
                    bullet += f" — {float(p):.0%}"
                lines.append(bullet)
        else:
            lines.append(f"`{json.dumps(data)[:400]}`")
        lines.append("\nSet `ATRIA_API_KEY` and restart to get real analysis here.")
        return AIMessage(content="\n".join(lines))

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._plan(messages))])

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any):
        msg = self._plan(messages)
        if msg.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="", tool_calls=msg.tool_calls))
            return
        text = str(msg.content)
        for i in range(0, len(text), 18):          # chunked so the UI visibly streams
            piece = text[i:i + 18]
            if run_manager:
                run_manager.on_llm_new_token(piece)
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))


def build_tools(corpus: Corpus, backend: str = "aimlapi", mock: bool = False) -> list:
    @tool
    def search_items(query: str = "", verdict: str = "keep", stream: str = "any", limit: int = 12) -> list[dict]:
        """Search the scored items. `verdict` is keep|review|drop|any, `stream` is a
        stream id (for example leads or tech) or any. Empty query returns the
        highest-ranked items. Returns compact records; call get_item for detail."""
        rows = corpus.search(query=query, verdict=verdict, stream=stream, limit=min(limit, 40))
        return [r.brief() for r in rows]

    @tool
    def get_item(item_id: str) -> dict:
        """Full detail for one item: summary text plus every typed answer Jev gave it."""
        rec = corpus.get(item_id)
        return rec.full() if rec else {"error": f"no item with id {item_id!r}"}

    @tool
    def corpus_stats() -> dict:
        """How many items are stored, split by verdict and by stream."""
        return corpus.counts()

    @tool
    def ask_jev(
        question: str,
        kind: str = "noul",
        options: dict | None = None,
        levels: list | None = None,
        verdict: str = "any",
        stream: str = "any",
        query: str = "",
        limit: int = 60,
    ) -> dict:
        """Ask a NEW typed question across stored items using the fast decision model.

        Use this instead of reading many items yourself - it is ~100ms per item,
        runs in parallel, and costs almost nothing.

        kind:
          noul   - yes/no. Returns a probability per item. No extra args needed.
          choice - pick one label. Pass options as {"label": "what it means", ...}.
          score  - rate on an ordered scale. Pass levels as an ordered list of
                   level descriptions, lowest first (at least 2).

        verdict/stream/query narrow which items are asked about. Keep `limit`
        modest unless you really need the whole corpus.
        """
        pool = corpus.search(query=query, verdict=verdict, stream=stream, limit=min(limit, 200))
        if not pool:
            return {"error": "no items matched that filter", "asked": 0}

        kind = (kind or "noul").lower()
        if kind == "choice":
            if not options or len(options) < 2:
                return {"error": "choice needs an `options` map with at least 2 entries"}
            q = choice(question, {str(k): str(v) for k, v in options.items()})
        elif kind == "score":
            if not levels or len(levels) < 2:
                return {"error": "score needs a `levels` list with at least 2 entries"}
            q = score(question, [str(x) for x in levels])
        else:
            kind = "noul"
            q = noul(question)

        clf = make_classifier({"answer": q}, backend=backend, mock=mock)
        states = [f"TITLE: {r.title}\nSOURCE: {r.source}\nBODY: {r.summary[:900]}" for r in pool]
        responses = clf.batch(states, config={"max_concurrency": 8})

        rows: list[dict] = []
        tokens = 0
        for rec, resp in zip(pool, responses):
            a = resp.answers.get("answer")
            tokens += int(resp.usage.input_tokens or 0)
            row = {"id": rec.id, "title": rec.title, "url": rec.url,
                   "certainty": round(certainty(a), 3)}
            if kind == "noul":
                row["probability"] = round(float(a.noul), 3)
            elif kind == "choice":
                row["choice"] = a.choice
                row["confidence"] = round(float(a.confidence), 3)
            else:
                row["level"] = level_label(a)
                row["score"] = round(float(a.score), 2)
                row["normalised"] = round(score_fraction(a), 3)
            rows.append(row)

        if kind == "noul":
            rows.sort(key=lambda r: r["probability"], reverse=True)
            summary = {"yes_over_0.7": sum(1 for r in rows if r["probability"] >= 0.7),
                       "unclear_0.3_to_0.7": sum(1 for r in rows if 0.3 < r["probability"] < 0.7),
                       "no_under_0.3": sum(1 for r in rows if r["probability"] <= 0.3)}
        elif kind == "choice":
            tally: dict[str, int] = {}
            for r in rows:
                tally[r["choice"]] = tally.get(r["choice"], 0) + 1
            summary = tally
        else:
            rows.sort(key=lambda r: r["score"], reverse=True)
            summary = {"mean_normalised": round(sum(r["normalised"] for r in rows) / len(rows), 3)}

        return {
            "question": question,
            "kind": kind,
            "asked": len(rows),
            "summary": summary,
            "cost_usd": round(tokens / 1_000_000 * 0.042, 6),
            "results": rows[:40],
        }

    return [search_items, get_item, corpus_stats, ask_jev]


def build_agent(
    corpus: Corpus,
    backend: str = "aimlapi",
    mock: bool = False,
    checkpoint_path: str | None = "state/agent.sqlite",
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.3,
):
    """Returns (compiled_agent, checkpointer_context_or_None)."""
    api_key = os.environ.get("ATRIA_API_KEY")
    if not api_key:
        if not mock:
            raise RuntimeError("no ATRIA_API_KEY set - export it before starting the agent")
        llm: Any = DemoChatModel()
    else:
        llm = ChatOpenAI(
            model=model or ATRIA_MODEL,
            base_url=base_url or ATRIA_BASE,
            api_key=api_key,
            temperature=temperature,
            max_retries=3,
            timeout=180,
        )

    saver_cm = None
    checkpointer = None
    if checkpoint_path:
        from langgraph.checkpoint.sqlite import SqliteSaver

        parent = os.path.dirname(checkpoint_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        saver_cm = SqliteSaver.from_conn_string(checkpoint_path)
        checkpointer = saver_cm.__enter__()

    agent = create_agent(
        llm,
        tools=build_tools(corpus, backend=backend, mock=mock),
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    return agent, saver_cm
