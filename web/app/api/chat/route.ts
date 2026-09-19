import { createUIMessageStream, createUIMessageStreamResponse } from "ai";

export const maxDuration = 300;

const BRIDGE = process.env.FIREHOSE_BRIDGE ?? "http://127.0.0.1:8000";
const TOKEN = process.env.FIREHOSE_TOKEN ?? "";

/** Server-side only — the bridge token never reaches the browser. */
function bridgeHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return TOKEN ? { ...extra, authorization: `Bearer ${TOKEN}` } : extra;
}

type BridgeEvent =
  | { type: "text"; delta: string }
  | { type: "reasoning"; delta: string }
  | { type: "tool-start"; id: string; name: string; args: unknown }
  | { type: "tool-end"; id: string; name: string; result: unknown }
  | { type: "error"; message: string }
  | { type: "done" };

/**
 * Translates the bridge's newline-JSON into the AI SDK's UI message stream.
 * The SDK's own writer produces the wire format, so nothing here hand-rolls it.
 */
export async function POST(req: Request) {
  const body = (await req.json()) as {
    messages?: Array<{ parts?: Array<{ type: string; text?: string }> }>;
    id?: string;
  };

  const last = body.messages?.[body.messages.length - 1];
  const prompt =
    last?.parts
      ?.filter((p) => p.type === "text")
      .map((p) => p.text ?? "")
      .join("") ?? "";

  const stream = createUIMessageStream({
    execute: async ({ writer }) => {
      writer.write({ type: "start" });

      let upstream: Response;
      try {
        upstream = await fetch(`${BRIDGE}/api/chat`, {
          method: "POST",
          headers: bridgeHeaders({ "content-type": "application/json" }),
          body: JSON.stringify({ message: prompt, thread: body.id ?? "web" }),
        });
      } catch {
        writer.write({
          type: "error",
          errorText: `Cannot reach the bridge at ${BRIDGE}. Is uvicorn running?`,
        });
        writer.write({ type: "finish" });
        return;
      }

      if (!upstream.ok || !upstream.body) {
        writer.write({
          type: "error",
          errorText: `Bridge returned ${upstream.status} ${upstream.statusText}`,
        });
        writer.write({ type: "finish" });
        return;
      }

      // one block at a time per kind; closed whenever something interrupts, reopened after
      const blockId = () => `b${Math.random().toString(36).slice(2, 9)}`;

      let textId: string | null = null;
      const openText = () => {
        if (textId === null) {
          textId = blockId();
          writer.write({ type: "text-start", id: textId });
        }
        return textId;
      };
      const closeText = () => {
        if (textId !== null) {
          writer.write({ type: "text-end", id: textId });
          textId = null;
        }
      };

      let reasoningId: string | null = null;
      const openReasoning = () => {
        if (reasoningId === null) {
          reasoningId = blockId();
          writer.write({ type: "reasoning-start", id: reasoningId });
        }
        return reasoningId;
      };
      const closeReasoning = () => {
        if (reasoningId !== null) {
          writer.write({ type: "reasoning-end", id: reasoningId });
          reasoningId = null;
        }
      };

      const reader = upstream.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const handle = (line: string) => {
        if (!line.trim()) return;
        let evt: BridgeEvent;
        try {
          evt = JSON.parse(line) as BridgeEvent;
        } catch {
          return;
        }
        switch (evt.type) {
          case "text":
            closeReasoning();
            writer.write({ type: "text-delta", id: openText(), delta: evt.delta });
            break;
          case "reasoning":
            closeText();
            writer.write({ type: "reasoning-delta", id: openReasoning(), delta: evt.delta });
            break;
          case "tool-start":
            closeText();
            closeReasoning();
            writer.write({
              type: "tool-input-available",
              toolCallId: evt.id,
              toolName: evt.name,
              input: evt.args,
              // the browser has no tool definitions - these are declared dynamic so
              // the SDK creates a dynamic-tool part instead of discarding the chunk
              dynamic: true,
            });
            break;
          case "tool-end":
            writer.write({
              type: "tool-output-available",
              toolCallId: evt.id,
              output: evt.result,
              dynamic: true,
            });
            break;
          case "error":
            closeText();
            closeReasoning();
            writer.write({ type: "error", errorText: evt.message });
            break;
          case "done":
            closeText();
            closeReasoning();
            break;
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) handle(line);
      }
      if (buffer) handle(buffer);

      closeText();
      closeReasoning();
      writer.write({ type: "finish" });
    },
    onError: (error) => (error instanceof Error ? error.message : String(error)),
  });

  return createUIMessageStreamResponse({ stream });
}
