"use client";

import type { ChatStatus, UIMessage } from "ai";
import { CheckIcon, CopyIcon, MessagesSquareIcon, RefreshCcwIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtSearchResult,
  ChainOfThoughtSearchResults,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse,
  MessageToolbar,
} from "@/components/ai-elements/message";
import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input";
import { Reasoning, ReasoningContent, ReasoningTrigger } from "@/components/ai-elements/reasoning";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Source, Sources, SourcesContent, SourcesTrigger } from "@/components/ai-elements/sources";
import { Suggestion, Suggestions } from "@/components/ai-elements/suggestion";
import { Tool, ToolContent, ToolHeader, ToolInput, ToolOutput } from "@/components/ai-elements/tool";
import { ItemRow } from "@/components/item-row";
import { Button } from "@/components/ui/button";
import {
  headline,
  isToolPart,
  type Item,
  itemsFrom,
  summarise,
  type ToolPart,
  toolMeta,
  toolNameOf,
} from "@/lib/firehose";
import { useItems } from "@/lib/use-firehose";

const STARTERS = [
  "What should I look at first today?",
  "Which leads have a deadline in the next 30 days?",
  "Anything here about agent evaluation or reliability?",
  "Summarise the review pile — what is the model unsure about?",
];

type AnyPart = ToolPart & { text?: string };

/** AI Elements' default says "1 seconds"; everything else about it is right. */
const thinkingMessage = (streaming: boolean, duration?: number) => {
  if (streaming || duration === 0) return <Shimmer duration={1}>Thinking…</Shimmer>;
  if (duration === undefined) return <p>Thought about it</p>;
  return <p>{`Thought for ${duration} second${duration === 1 ? "" : "s"}`}</p>;
};

const stepStatus = (state?: string): "complete" | "active" | "pending" => {
  if (state === "output-available" || state === "output-error") return "complete";
  if (state === "input-streaming") return "pending";
  return "active";
};

/**
 * What Jev actually kept today, on the opening screen. Only mounted where the
 * dashboard rail is not - otherwise the first thing you see is an empty chat
 * telling you it could answer questions, which is not the same as an answer.
 */
const OpeningPile = ({ onOpenDashboard }: { onOpenDashboard: () => void }) => {
  const { items, loading, failed } = useItems("keep", 6);

  if (failed || (!loading && items.length === 0)) return null;

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
          Kept today
        </h3>
        <Button className="h-auto p-0 text-xs" onClick={onOpenDashboard} size="sm" variant="link">
          the whole pile
        </Button>
      </div>

      {loading ? (
        <Shimmer duration={1}>Reading the pile…</Shimmer>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <ItemRow item={item} key={item.id} />
          ))}
        </div>
      )}
    </section>
  );
};

const Composer = ({
  status,
  showStarters,
  onSubmit,
  onSuggest,
  onStop,
}: {
  status: ChatStatus;
  showStarters: boolean;
  onSubmit: (message: PromptInputMessage) => void;
  onSuggest: (suggestion: string) => void;
  onStop: () => void;
}) => (
  <div className="mx-auto grid w-full max-w-3xl shrink-0 gap-3 px-4 pb-4">
    {showStarters && (
      <Suggestions>
        {STARTERS.map((starter) => (
          <Suggestion key={starter} onClick={onSuggest} suggestion={starter} />
        ))}
      </Suggestions>
    )}

    <PromptInput onSubmit={onSubmit}>
      <PromptInputBody>
        <PromptInputTextarea placeholder="Ask about anything Jev read today…" />
      </PromptInputBody>
      <PromptInputFooter>
        <PromptInputTools>
          <span className="px-1 text-muted-foreground text-xs">
            Enter to send · Shift+Enter for a new line
          </span>
        </PromptInputTools>
        <PromptInputSubmit onStop={onStop} status={status} />
      </PromptInputFooter>
    </PromptInput>
  </div>
);

const Opening = ({ className }: { className?: string }) => (
  <ConversationEmptyState
    className={className}
    description="Firehose can search what was scored, open any item, and — the useful part — ask Jev a brand new typed question across the whole corpus in about a second."
    icon={<MessagesSquareIcon className="size-8" />}
    title="Ask about everything Jev read today"
  />
);

const CopyAction = ({ text }: { text: string }) => {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(() => {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {
        /* clipboard blocked - nothing useful to say about it */
      });
  }, [text]);

  return (
    <MessageAction onClick={copy} tooltip={copied ? "Copied" : "Copy reply"}>
      {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
    </MessageAction>
  );
};

/** The agent's work for one turn: every tool call, as a thinking trace. */
const ToolTrace = ({ parts, live }: { parts: AnyPart[]; live: boolean }) => {
  const done = parts.filter((p) => p.state === "output-available").length;

  // open while the turn is working, then fold away once the answer is there -
  // the same manners the Reasoning element has. A manual toggle stays put.
  const [open, setOpen] = useState(live);
  const settled = useRef(false);

  useEffect(() => {
    if (live) {
      setOpen(true);
      return;
    }
    if (settled.current) return;
    settled.current = true;
    const timer = setTimeout(() => setOpen(false), 1200);
    return () => clearTimeout(timer);
  }, [live]);

  return (
    <ChainOfThought className="mb-4" onOpenChange={setOpen} open={open}>
      <ChainOfThoughtHeader>
        {live && done < parts.length ? (
          <Shimmer duration={1}>{`Working — ${done} of ${parts.length} steps`}</Shimmer>
        ) : (
          `Worked through ${parts.length} step${parts.length === 1 ? "" : "s"}`
        )}
      </ChainOfThoughtHeader>
      <ChainOfThoughtContent>
        {parts.map((part, i) => {
          const name = toolNameOf(part) ?? "tool";
          const meta = toolMeta(name);
          const items = part.state === "output-available" ? itemsFrom(name, part.output) : [];
          const note = summarise(name, part.input, part.output);

          return (
            <ChainOfThoughtStep
              description={part.state === "output-available" ? note : meta.blurb}
              icon={meta.icon}
              key={part.toolCallId ?? i}
              label={headline(name, part.input)}
              status={stepStatus(part.state)}
            >
              {items.length > 0 && (
                <ChainOfThoughtSearchResults>
                  {items.slice(0, 5).map((item: Item) => (
                    <ChainOfThoughtSearchResult key={item.id}>
                      <span className="max-w-52 truncate">{item.title}</span>
                    </ChainOfThoughtSearchResult>
                  ))}
                  {items.length > 5 && (
                    <ChainOfThoughtSearchResult>+{items.length - 5} more</ChainOfThoughtSearchResult>
                  )}
                </ChainOfThoughtSearchResults>
              )}

              <Tool defaultOpen={false}>
                <ToolHeader
                  state={(part.state ?? "input-available") as never}
                  title={meta.title}
                  toolName={name}
                  type="dynamic-tool"
                />
                <ToolContent>
                  <ToolInput input={part.input} />
                  <ToolOutput errorText={part.errorText} output={part.output} />
                </ToolContent>
              </Tool>
            </ChainOfThoughtStep>
          );
        })}
      </ChainOfThoughtContent>
    </ChainOfThought>
  );
};

export type ChatPanelProps = {
  messages: UIMessage[];
  status: ChatStatus;
  error?: Error;
  /** true where no dashboard rail is showing, so the pile belongs here instead */
  showPile: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onRetry: () => void;
  onOpenDashboard: () => void;
};

export const ChatPanel = ({
  messages,
  status,
  error,
  showPile,
  onSend,
  onStop,
  onRetry,
  onOpenDashboard,
}: ChatPanelProps) => {
  const busy = status === "submitted" || status === "streaming";

  const submit = useCallback(
    (message: PromptInputMessage) => {
      const text = message.text?.trim();
      if (text && !busy) onSend(text);
    },
    [busy, onSend],
  );

  const suggest = useCallback(
    (suggestion: string) => {
      if (!busy) onSend(suggestion);
    },
    [busy, onSend],
  );

  // The conversation sticks to the bottom, which is right for a chat and wrong
  // for an opening screen: you would land halfway down the pile. So the opening
  // screen that carries the pile is a plain scroller of its own.
  if (messages.length === 0 && showPile) {
    return (
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-4">
            <Opening className="pb-0" />
            <OpeningPile onOpenDashboard={onOpenDashboard} />
          </div>
        </div>
        <Composer
          onStop={onStop}
          onSubmit={submit}
          onSuggest={suggest}
          showStarters
          status={status}
        />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <Conversation>
        <ConversationContent className="mx-auto w-full max-w-3xl">
          {messages.length === 0 && <Opening className="min-h-[55vh]" />}

          {messages.map((message, index) => {
            const parts = (message.parts ?? []) as AnyPart[];
            const text = parts
              .filter((p) => p.type === "text")
              .map((p) => p.text ?? "")
              .join("");

            if (message.role === "user") {
              return (
                <Message from="user" key={message.id}>
                  <MessageContent>{text}</MessageContent>
                </Message>
              );
            }

            const toolParts = parts.filter(isToolPart);
            const reasoning = parts
              .filter((p) => p.type === "reasoning")
              .map((p) => p.text ?? "")
              .join("");
            const live = busy && index === messages.length - 1;

            const sources = new Map<string, Item>();
            for (const part of toolParts) {
              for (const item of itemsFrom(toolNameOf(part) ?? "", part.output)) {
                if (item.url) sources.set(item.url, item);
              }
            }

            return (
              <Message from="assistant" key={message.id}>
                <MessageContent>
                  {reasoning && (
                    <Reasoning isStreaming={live && !text}>
                      <ReasoningTrigger getThinkingMessage={thinkingMessage} />
                      <ReasoningContent>{reasoning}</ReasoningContent>
                    </Reasoning>
                  )}

                  {toolParts.length > 0 && <ToolTrace live={live} parts={toolParts} />}

                  {sources.size > 0 && (
                    <Sources>
                      <SourcesTrigger count={sources.size} />
                      <SourcesContent>
                        {[...sources.values()].map((item) => (
                          <Source href={item.url} key={item.url} title={item.title} />
                        ))}
                      </SourcesContent>
                    </Sources>
                  )}

                  {text && <MessageResponse>{text}</MessageResponse>}

                  {!text && live && toolParts.length === 0 && (
                    <Shimmer duration={1}>Reading the corpus…</Shimmer>
                  )}
                </MessageContent>

                {text && !live && (
                  <MessageToolbar>
                    <MessageActions>
                      <CopyAction text={text} />
                      <MessageAction onClick={onRetry} tooltip="Ask again">
                        <RefreshCcwIcon className="size-4" />
                      </MessageAction>
                    </MessageActions>
                  </MessageToolbar>
                )}
              </Message>
            );
          })}

          {status === "submitted" && (
            <Message from="assistant">
              <MessageContent>
                <Shimmer duration={1}>Thinking…</Shimmer>
              </MessageContent>
            </Message>
          )}

          {/* no red to lean on, so an error is marked by a heavy rule and a label */}
          {error && (
            <div className="rounded-md border border-l-[3px] border-l-foreground bg-muted/50 p-3 text-sm">
              <p className="font-medium text-foreground">
                <span className="mr-2 font-mono text-muted-foreground text-xs uppercase">error</span>
                {error.message || "Something went wrong."}
              </p>
              <p className="mt-1 text-muted-foreground text-xs">
                Check that the bridge is running:{" "}
                <code className="font-mono">uvicorn firehose.server:app --port 8000</code>
              </p>
            </div>
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      <Composer
        onStop={onStop}
        onSubmit={submit}
        onSuggest={suggest}
        showStarters={messages.length === 0}
        status={status}
      />
    </div>
  );
};
