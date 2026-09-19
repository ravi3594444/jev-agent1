"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { PanelRightIcon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { ChatPanel } from "@/components/chat-panel";
import { Dashboard } from "@/components/dashboard";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { isToolPart, type Item, itemsFrom, type ToolPart, toolNameOf } from "@/lib/firehose";

export const Workspace = () => {
  const [dashboardOpen, setDashboardOpen] = useState(false);

  const { messages, sendMessage, status, stop, error, regenerate } = useChat({
    id: "web",
    transport: new DefaultChatTransport({ api: "/api/chat" }),
  });

  const send = useCallback((text: string) => void sendMessage({ text }), [sendMessage]);
  const retry = useCallback(() => void regenerate(), [regenerate]);
  const closeDashboard = useCallback(() => setDashboardOpen(false), []);
  const toggleDashboard = useCallback(() => setDashboardOpen((open) => !open), []);

  // newest call first - the dashboard reads as a live feed
  const activity = useMemo(
    () =>
      messages
        .flatMap((m) => ((m.parts ?? []) as ToolPart[]).filter(isToolPart))
        .reverse(),
    [messages],
  );

  const items = useMemo(() => {
    const seen = new Map<string, Item>();
    for (const part of activity) {
      for (const item of itemsFrom(toolNameOf(part) ?? "", part.output)) {
        if (!seen.has(item.id)) seen.set(item.id, item);
      }
    }
    return [...seen.values()];
  }, [activity]);

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
        <h1 className="font-semibold text-sm tracking-tight">Firehose</h1>
        <p className="hidden text-muted-foreground text-sm sm:block">
          everything Jev read today
        </p>
        <span className="flex-1" />
        <Button
          aria-label="Toggle dashboard"
          className="lg:hidden"
          onClick={toggleDashboard}
          size="icon-sm"
          type="button"
          variant="ghost"
        >
          <PanelRightIcon className="size-4" />
        </Button>
        <ThemeToggle />
      </header>

      <div className="flex min-h-0 flex-1">
        <ChatPanel
          error={error}
          messages={messages}
          onRetry={retry}
          onSend={send}
          onStop={stop}
          status={status}
        />

        <aside className="hidden w-96 shrink-0 border-l lg:block">
          <Dashboard activity={activity} items={items} />
        </aside>

        {dashboardOpen && (
          <div className="fixed inset-0 z-50 bg-background lg:hidden">
            <Dashboard activity={activity} items={items} onClose={closeDashboard} />
          </div>
        )}
      </div>
    </div>
  );
};
