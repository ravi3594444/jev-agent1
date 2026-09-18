"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import React, { useEffect, useRef, useState } from "react";

import Composer from "./Composer";
import Markdown from "./Markdown";
import StatsBar from "./StatsBar";
import ToolCard from "./ToolCard";

const STARTERS = [
  "What should I look at first today?",
  "Which leads have a deadline in the next 30 days?",
  "Anything here about agent evaluation or reliability?",
  "Summarise the review pile — what is the model unsure about?",
];

type AnyPart = {
  type: string;
  text?: string;
  toolName?: string;
  input?: unknown;
  output?: unknown;
  state?: string;
  errorText?: string;
};

function toolNameOf(part: AnyPart): string | null {
  if (part.type === "dynamic-tool") return part.toolName ?? "tool";
  if (part.type.startsWith("tool-")) return part.type.slice(5);
  return null;
}

export default function Chat() {
  const [input, setInput] = useState("");
  const streamRef = useRef<HTMLDivElement>(null);

  const { messages, sendMessage, status, stop, error } = useChat({
    id: "web",
    transport: new DefaultChatTransport({ api: "/api/chat" }),
  });

  const busy = status === "submitted" || status === "streaming";

  // keep the newest turn in view while tokens arrive
  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, status]);

  const send = (text?: string) => {
    const body = (text ?? input).trim();
    if (!body || busy) return;
    void sendMessage({ text: body });
    setInput("");
  };

  const toggleTheme = () => {
    const root = document.documentElement;
    const isDark =
      root.getAttribute("data-theme") === "dark" ||
      (!root.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const next = isDark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try {
      localStorage.setItem("fh-theme", next);
    } catch {
      /* private mode - theme just won't persist */
    }
  };

  return (
    <div className="shell">
      <header className="topbar">
        <h1>Firehose</h1>
        <StatsBar />
        <span className="spacer" />
        <button className="ghost" onClick={toggleTheme}>
          Theme
        </button>
      </header>

      <div className="stream" ref={streamRef}>
        {messages.length === 0 && (
          <div className="empty">
            <h2>Ask about everything Jev read today.</h2>
            <p>
              It can search what was scored, open any item, and — the useful part — ask Jev a brand
              new typed question across the whole corpus in about a second.
            </p>
            <div className="starters">
              {STARTERS.map((s) => (
                <button key={s} className="starter" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => {
          const parts = (m.parts ?? []) as AnyPart[];
          if (m.role === "user") {
            const text = parts.filter((p) => p.type === "text").map((p) => p.text ?? "").join("");
            return (
              <div className="turn user" key={m.id}>
                <div className="bubble">{text}</div>
              </div>
            );
          }
          return (
            <div className="turn" key={m.id}>
              <div className="who">Analyst</div>
              {parts.map((part, i) => {
                const tool = toolNameOf(part);
                if (tool) {
                  const state =
                    part.state === "output-available"
                      ? "done"
                      : part.state === "output-error"
                        ? "error"
                        : "running";
                  return (
                    <ToolCard
                      key={i}
                      name={tool}
                      input={part.input}
                      output={part.output}
                      state={state as "running" | "done" | "error"}
                      errorText={part.errorText}
                    />
                  );
                }
                if (part.type === "text" && part.text) {
                  return <Markdown key={i} text={part.text} />;
                }
                return null;
              })}
            </div>
          );
        })}

        {status === "submitted" && (
          <div className="turn">
            <div className="who">Analyst</div>
            <span className="typing">
              <i />
              <i />
              <i />
            </span>
          </div>
        )}

        {error && (
          <div className="err">
            {error.message || "Something went wrong."} — check that the bridge is running
            (<code>uvicorn firehose.server:app --port 8000</code>).
          </div>
        )}
      </div>

      <Composer value={input} onChange={setInput} onSubmit={() => send()} busy={busy} onStop={stop} />
    </div>
  );
}
