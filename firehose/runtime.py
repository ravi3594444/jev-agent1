"""Config, corpus and agent loading, shared by every front end.

The HTTP bridge (server.py) and the MCP server (mcp_server.py) both need the
same three things: the config file, the scored corpus reloaded whenever the
scorer has written a newer one, and a lazily built agent that closes over it.
Keeping that here means the two cannot drift apart.

langchain is imported inside `agent()` rather than at module scope, so the
corpus half works on a machine that only installed the stdlib requirements.
"""
from __future__ import annotations

import os
import tomllib
from typing import Any

from .corpus import Corpus

CONFIG_PATH = os.environ.get("FIREHOSE_CONFIG", "config.toml")
MOCK = os.environ.get("FIREHOSE_MOCK", "").lower() in {"1", "true", "yes"}

_state: dict[str, Any] = {"agent": None, "saver": None, "corpus": None, "mtime": 0.0}


def config() -> dict:
    with open(CONFIG_PATH, "rb") as fh:
        return tomllib.load(fh)


def results_path() -> str:
    cfg = config()
    return os.path.join(cfg.get("run", {}).get("output_dir", "out"), "results.jsonl")


def backend() -> str:
    return config().get("run", {}).get("backend", "aimlapi")


def corpus() -> Corpus:
    """Reload when the scorer has written a newer file - runs are out of band."""
    path = results_path()
    mtime = os.path.getmtime(path) if os.path.exists(path) else 0.0
    if _state["corpus"] is None or mtime != _state["mtime"]:
        _state["corpus"] = Corpus.from_jsonl(path)
        _state["mtime"] = mtime
        _state["agent"] = None          # rebuild so tools close over fresh data
    return _state["corpus"]


def mtime() -> float:
    return float(_state["mtime"])


def agent() -> Any:
    c = corpus()
    if _state["agent"] is None:
        from .agent import build_agent

        cfg = config()
        acfg = cfg.get("agent", {})
        a, saver = build_agent(
            c,
            backend=cfg.get("run", {}).get("backend", "aimlapi"),
            mock=MOCK,
            checkpoint_path=acfg.get("checkpoint_path", "state/agent.sqlite"),
            model=acfg.get("model"),
            base_url=acfg.get("base_url"),
            temperature=float(acfg.get("temperature", 0.3)),
        )
        _state["agent"], _state["saver"] = a, saver
    return _state["agent"]


def tools() -> dict[str, Any]:
    """The agent's own four tools, by name, so a caller can use one directly."""
    from .agent import build_tools

    return {t.name: t for t in build_tools(corpus(), backend=backend(), mock=MOCK)}
