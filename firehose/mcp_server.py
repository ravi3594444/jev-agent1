"""MCP server: lets another agent use Jev and the scored corpus as tools.

The web UI talks to the agent. This is the other direction - it hands the same
four tools, plus the agent itself, to any MCP client: Claude Desktop, Claude
Code, Cursor, or another agent you wrote.

    python3 -m firehose mcp                  # stdio, for a local client
    python3 -m firehose mcp --http --port 8765   # streamable HTTP, for a remote one

The tools are not reimplemented here. `runtime.tools()` builds the very objects
the LangGraph agent is given, and this module invokes those, so an MCP client
and the web agent can never disagree about what `ask_jev` does.

Three of the five tools need nothing but the stdlib and a scored corpus.
`ask_jev` and `ask_agent` reach the model, so they import langchain lazily and
say so plainly if it is not installed.
"""
from __future__ import annotations

import json
import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import runtime

INSTRUCTIONS = """\
Firehose is a daily pipeline that reads tenders, feeds and forums, and scores
every item with Jev, a model that returns typed decisions instead of prose.

Use `search_items` to look through what was scored, `get_item` for the full
detail of one, and `corpus_stats` for the shape of the day.

`ask_jev` is the one worth knowing about: it asks a brand new typed question
across every stored item in one batch - roughly 100ms per item, in parallel,
for a fraction of a cent. Prefer it over reading items one at a time. It
answers yes/no with a probability (`noul`), picks a label (`choice`), or rates
on an ordered scale (`score`).

`ask_agent` hands the question to the Firehose agent itself, which will use all
of the above and reply in prose. Use it for open questions; use the tools above
when you want the data.
"""

mcp = MCPServer(name="firehose", instructions=INSTRUCTIONS, version="0.1.0")

UNAVAILABLE = (
    "This tool needs the agent half installed: pip install -r requirements.txt. "
    "search_items, get_item and corpus_stats work without it."
)


def _call(name: str, **kwargs: Any) -> Any:
    """Invoke one of the agent's own LangChain tools."""
    try:
        tool = runtime.tools()[name]
    except ImportError:
        return {"error": UNAVAILABLE}
    return tool.invoke(kwargs)


# --------------------------------------------------------------- corpus tools
@mcp.tool()
def search_items(
    query: str = "",
    verdict: str = "keep",
    stream: str = "any",
    limit: int = 12,
) -> list[dict]:
    """Search the items Jev scored today.

    Args:
        query: words to match against title, summary and source. Empty returns
            the highest-ranked items.
        verdict: keep, review, drop, or any.
        stream: a stream id such as leads or tech, or any.
        limit: how many rows to return, at most 40.
    """
    rows = runtime.corpus().search(
        query=query, verdict=verdict, stream=stream, limit=min(max(limit, 1), 40)
    )
    return [r.brief() for r in rows]


@mcp.tool()
def get_item(item_id: str) -> dict:
    """Full detail for one scored item: its summary and every typed answer Jev gave it."""
    rec = runtime.corpus().get(item_id)
    return rec.full() if rec else {"error": f"no item with id {item_id!r}"}


@mcp.tool()
def corpus_stats() -> dict:
    """How many items are stored, split by verdict and by stream."""
    return runtime.corpus().counts()


# ------------------------------------------------------------- the model half
@mcp.tool()
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
    """Ask a NEW typed question across the stored items, in one fast batch.

    This is the reason to use Firehose over a search box: it runs the question
    over every matching item in parallel for a fraction of a cent, and returns
    a number per item rather than a paragraph.

    Args:
        question: the question to ask of each item.
        kind: noul for yes/no with a probability, choice to pick a label, or
            score to rate on an ordered scale.
        options: for kind=choice, a map of {label: what it means}, at least two.
        levels: for kind=score, ordered level descriptions, lowest first.
        verdict: narrow to keep, review, drop, or any.
        stream: narrow to one stream id, or any.
        query: narrow to items matching these words first.
        limit: how many items to ask about, at most 200.
    """
    return _call(
        "ask_jev",
        question=question,
        kind=kind,
        options=options,
        levels=levels,
        verdict=verdict,
        stream=stream,
        query=query,
        limit=limit,
    )


@mcp.tool()
def ask_agent(message: str, thread: str = "mcp") -> str:
    """Put an open question to the Firehose agent and get its written answer.

    The agent decides for itself which of the tools above to use. Threads are
    remembered, so passing the same `thread` continues a conversation.
    """
    try:
        graph = runtime.agent()
    except ImportError:
        return UNAVAILABLE

    final: Any = None
    for chunk in graph.stream(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread}},
        stream_mode="values",
    ):
        messages = chunk.get("messages", [])
        if messages:
            final = messages[-1]

    return (getattr(final, "content", "") or "").strip() or "(the agent said nothing)"


# ------------------------------------------------------------------ resources
@mcp.resource("firehose://corpus/stats", mime_type="application/json")
def stats_resource() -> str:
    """Today's corpus, by verdict and by stream."""
    return json.dumps(runtime.corpus().counts(), indent=2)


@mcp.resource("firehose://corpus/keep", mime_type="application/json")
def keep_resource() -> str:
    """Everything Jev kept today, highest ranked first."""
    rows = runtime.corpus().search(verdict="keep", limit=200)
    return json.dumps([r.brief() for r in rows], indent=2)


@mcp.resource("firehose://item/{item_id}", mime_type="application/json")
def item_resource(item_id: str) -> str:
    """One scored item in full."""
    rec = runtime.corpus().get(item_id)
    return json.dumps(rec.full() if rec else {"error": f"no item with id {item_id!r}"}, indent=2)


def main(http: bool = False, host: str = "127.0.0.1", port: int = 8765) -> None:
    if http:
        # Bound to loopback unless told otherwise, because these tools spend
        # real money. Put a proxy and auth in front before exposing it.
        mcp.run("streamable-http", host=host, port=port)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main(http=os.environ.get("FIREHOSE_MCP_HTTP", "").lower() in {"1", "true", "yes"})
