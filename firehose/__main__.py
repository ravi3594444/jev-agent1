"""CLI: `run` scores the feeds, `chat` talks to the agent, `ask` is one-shot."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tomllib
from typing import Any

from .corpus import Corpus

# .jev and .pipeline pull in langchain; importing them here would make every
# subcommand need the agent half installed. `mcp` and `ask` do not.


def load_config(path: str) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def cmd_run(args: argparse.Namespace) -> int:
    from .jev import RunStats
    from .pipeline import SeenStore, run_stream
    from .report import render

    cfg = load_config(args.config)
    run_cfg = cfg.get("run", {})
    gates = cfg.get("gates", {})
    streams: dict[str, dict] = cfg.get("streams", {})
    if not streams:
        print("no [streams.*] in config", file=sys.stderr)
        return 2

    backend = args.backend or run_cfg.get("backend", "aimlapi")
    out_dir = args.out or run_cfg.get("output_dir", "out")
    state_dir = run_cfg.get("state_dir", "state")
    os.makedirs(out_dir, exist_ok=True)

    seen = None if args.no_dedupe else SeenStore(os.path.join(state_dir, "seen.json"))
    stats = RunStats()
    all_results = []
    warnings: list[str] = []

    started = time.perf_counter()
    for sid, scfg in streams.items():
        if args.stream and sid != args.stream:
            continue
        print(f"· {sid}: fetching…", file=sys.stderr)
        results, warns = run_stream(
            sid, scfg, gates,
            backend=backend,
            limit_per_source=args.limit or int(run_cfg.get("max_items_per_source", 40)),
            seen=seen,
            workers=int(run_cfg.get("workers", 8)),
            mock=args.mock,
            stats=stats,
            timeout=float(run_cfg.get("timeout", 60)),
        )
        all_results.extend(results)
        warnings.extend(warns)
        kept = sum(1 for r in results if r.verdict == "keep")
        print(f"  {len(results)} scored · {kept} kept", file=sys.stderr)

    if seen is not None:
        seen.save()
    all_results.sort(key=lambda r: r.rank, reverse=True)

    if not all_results:
        print("\nnothing new since the last run - existing digest left untouched", file=sys.stderr)
        for w in warnings:
            print(f"  ! {w}", file=sys.stderr)
        return 0

    jsonl_path = os.path.join(out_dir, "results.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as fh:
        for r in all_results:
            fh.write(json.dumps(r.to_dict(), default=str) + "\n")

    html_path = os.path.join(out_dir, "digest.html")
    names = {sid: scfg.get("name", sid) for sid, scfg in streams.items()}
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(render(all_results, stats, warnings, streams=names, mock=args.mock))

    wall = time.perf_counter() - started
    kept = sum(1 for r in all_results if r.verdict == "keep")
    review = sum(1 for r in all_results if r.verdict == "review")
    print(
        f"\n{len(all_results)} scored in {wall:.1f}s · {kept} keep · {review} review "
        f"· ${stats.cost_usd:.4f}"
        + (" · MOCK (no key used)" if args.mock else ""),
        file=sys.stderr,
    )
    for w in warnings:
        print(f"  ! {w}", file=sys.stderr)
    print(f"\n{html_path}\n{jsonl_path}")
    return 0


def _agent_for(args: argparse.Namespace, cfg: dict):
    from .agent import build_agent

    run_cfg = cfg.get("run", {})
    acfg = cfg.get("agent", {})
    out_dir = args.out or run_cfg.get("output_dir", "out")
    corpus = Corpus.from_jsonl(os.path.join(out_dir, "results.jsonl"))
    if not len(corpus):
        print("no scored items yet - run `python -m firehose run` first", file=sys.stderr)
    agent, saver = build_agent(
        corpus,
        backend=args.backend or run_cfg.get("backend", "aimlapi"),
        mock=args.mock,
        checkpoint_path=acfg.get("checkpoint_path", "state/agent.sqlite"),
        model=acfg.get("model"),
        base_url=acfg.get("base_url"),
        temperature=float(acfg.get("temperature", 0.3)),
    )
    return agent, saver, corpus


def _speak(agent: Any, text: str, thread: str) -> None:
    config = {"configurable": {"thread_id": thread}}
    last_printed = 0
    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": text}]},
        config=config,
        stream_mode="values",
    ):
        msgs = chunk.get("messages", [])
        for m in msgs[last_printed:]:
            calls = getattr(m, "tool_calls", None) or []
            for c in calls:
                name = c.get("name") if isinstance(c, dict) else getattr(c, "name", "")
                arg = c.get("args") if isinstance(c, dict) else getattr(c, "args", {})
                brief = json.dumps(arg, default=str)
                print(f"  \033[2m↳ {name}({brief[:120]})\033[0m", file=sys.stderr)
        last_printed = len(msgs)
    final = msgs[-1] if msgs else None
    print("\n" + (getattr(final, "content", "") or "").strip() + "\n")


def cmd_chat(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    agent, saver, corpus = _agent_for(args, cfg)
    counts = corpus.counts()
    print(
        f"\nFirehose agent · {counts['total']} items "
        f"({counts['by_verdict'].get('keep', 0)} keep, {counts['by_verdict'].get('review', 0)} review)\n"
        "Ask anything. It can re-question the whole corpus with Jev on the fly.\n"
        "Ctrl-C or 'exit' to quit.\n"
    )
    try:
        while True:
            try:
                text = input("\033[1myou ›\033[0m ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text.lower() in {"exit", "quit", ":q"}:
                break
            try:
                _speak(agent, text, args.thread)
            except Exception as exc:
                print(f"  ! {exc.__class__.__name__}: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print()
    finally:
        if saver is not None:
            saver.__exit__(None, None, None)
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    agent, saver, _ = _agent_for(args, cfg)
    try:
        _speak(agent, args.question, args.thread)
    finally:
        if saver is not None:
            saver.__exit__(None, None, None)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Serve the corpus and the agent to other agents over MCP."""
    os.environ.setdefault("FIREHOSE_CONFIG", args.config)
    if args.mock:
        os.environ["FIREHOSE_MOCK"] = "1"
    try:
        from .mcp_server import main as serve
    except ImportError as exc:  # the SDK is an extra, not a hard requirement
        print(f"! MCP server needs the SDK: pip install 'mcp>=2'  ({exc})", file=sys.stderr)
        return 2

    where = f"http://{args.host}:{args.port}/mcp" if args.http else "stdio"
    print(f"· firehose MCP server on {where}", file=sys.stderr)
    serve(http=args.http, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("firehose", description="Read the whole river, look at what matters.")
    p.add_argument("--config", default="config.toml")
    p.add_argument("--backend", choices=["aimlapi", "typesafe"])
    p.add_argument("--mock", action="store_true", help="no API key needed; heuristic stand-in for Jev")
    p.add_argument("--out", help="output directory (default from config)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="fetch feeds, score with Jev, write the digest")
    r.add_argument("--stream", help="only run this stream id")
    r.add_argument("--limit", type=int, help="max items per source")
    r.add_argument("--no-dedupe", action="store_true", help="re-score items seen in earlier runs")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("chat", help="interactive agent over the scored items")
    c.add_argument("--thread", default="default", help="conversation id (persisted)")
    c.set_defaults(func=cmd_chat)

    a = sub.add_parser("ask", help="one-shot question to the agent")
    a.add_argument("question")
    a.add_argument("--thread", default="default")
    a.set_defaults(func=cmd_ask)

    m = sub.add_parser("mcp", help="serve the corpus and agent to other agents over MCP")
    m.add_argument("--http", action="store_true", help="streamable HTTP instead of stdio")
    m.add_argument("--host", default="127.0.0.1", help="only with --http")
    m.add_argument("--port", type=int, default=8765, help="only with --http")
    m.set_defaults(func=cmd_mcp)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"\n! {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
