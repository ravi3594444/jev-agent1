"use client";

import React, { useCallback, useEffect, useRef } from "react";

export default function Composer({
  value,
  onChange,
  onSubmit,
  busy,
  onStop,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
  onStop: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // grow with the content instead of scrolling a fixed box
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 190)}px`;
  }, [value]);

  const keyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault();
        if (!busy && value.trim()) onSubmit();
      }
    },
    [busy, value, onSubmit],
  );

  return (
    <div className="composer">
      <div className="field">
        <textarea
          ref={ref}
          rows={1}
          value={value}
          placeholder="Ask about anything Jev read today…"
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={keyDown}
          aria-label="Message"
        />
        {busy ? (
          <button className="send" onClick={onStop} style={{ background: "var(--neutral)" }}>
            Stop
          </button>
        ) : (
          <button className="send" onClick={onSubmit} disabled={!value.trim()}>
            Send
          </button>
        )}
      </div>
      <div className="hint">Enter to send · Shift+Enter for a new line</div>
    </div>
  );
}
