"use client";

import React from "react";
import ItemCard, { type Item } from "./ItemCard";

type State = "running" | "done" | "error";

const HUMAN: Record<string, string> = {
  search_items: "searching what Jev scored",
  get_item: "opening one item",
  corpus_stats: "counting the corpus",
  ask_jev: "asking Jev a new question",
};

function summarise(name: string, input: unknown, output: unknown): string {
  const i = (input ?? {}) as Record<string, unknown>;
  const o = (output ?? {}) as Record<string, unknown>;
  if (name === "ask_jev") {
    const asked = typeof o.asked === "number" ? o.asked : undefined;
    const cost = typeof o.cost_usd === "number" ? o.cost_usd : undefined;
    if (asked === undefined) return String(i.question ?? "");
    return `${asked} items · $${(cost ?? 0).toFixed(6)}`;
  }
  if (name === "search_items") {
    const n = Array.isArray(output) ? output.length : undefined;
    const q = i.query ? `“${String(i.query)}”` : "top ranked";
    return n === undefined ? q : `${q} · ${n} hit${n === 1 ? "" : "s"}`;
  }
  return "";
}

/** Rows a tool result can contribute to the visual list, if any. */
function itemsFrom(name: string, output: unknown): Item[] {
  if (name === "search_items" && Array.isArray(output)) return output as Item[];
  if (name === "ask_jev") {
    const o = output as { results?: Item[] } | null;
    if (o && Array.isArray(o.results)) return o.results.slice(0, 8);
  }
  if (name === "get_item" && output && typeof output === "object" && "title" in output) {
    return [output as Item];
  }
  return [];
}

export default function ToolCard({
  name,
  input,
  output,
  state,
  errorText,
}: {
  name: string;
  input: unknown;
  output: unknown;
  state: State;
  errorText?: string;
}) {
  const items = state === "done" ? itemsFrom(name, output) : [];
  const note = state === "running" ? "running…" : state === "error" ? "failed" : summarise(name, input, output);

  // open while it runs or if it failed; collapse once there is an answer to read,
  // so the work is visible without burying the reply
  return (
    <details className="tool" open={state !== "done"}>
      <summary>
        <span className={`dot ${state === "running" ? "run" : state === "error" ? "fail" : "done"}`} />
        <span className="name">{name}</span>
        <span className="note">{HUMAN[name] ?? ""}{note ? ` · ${note}` : ""}</span>
      </summary>

      <div className="body">
        {state === "error" && errorText && <div className="err">{errorText}</div>}

        {items.length > 0 && (
          <>
            <div className="label">results</div>
            <div className="items">
              {items.slice(0, 6).map((it, idx) => (
                <ItemCard key={it.id ?? idx} item={it} />
              ))}
            </div>
            {items.length > 6 && (
              <div className="src" style={{ marginTop: 6 }}>+{items.length - 6} more</div>
            )}
          </>
        )}

        <div className="label">input</div>
        <pre>{JSON.stringify(input ?? {}, null, 2)}</pre>

        {state === "done" && items.length === 0 && (
          <>
            <div className="label">output</div>
            <pre>{JSON.stringify(output ?? null, null, 2).slice(0, 4000)}</pre>
          </>
        )}
      </div>
    </details>
  );
}
