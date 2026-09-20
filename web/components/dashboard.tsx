"use client";

import { RefreshCwIcon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactClose,
  ArtifactContent,
  ArtifactDescription,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { Shimmer } from "@/components/ai-elements/shimmer";
import {
  Task,
  TaskContent,
  TaskItem,
  TaskItemFile,
  TaskTrigger,
} from "@/components/ai-elements/task";
import { ItemRow } from "@/components/item-row";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  headline,
  type Item,
  PILE_TABS,
  type PileTab,
  type Stats,
  summarise,
  type ToolPart,
  toolMeta,
  toolNameOf,
  VERDICTS,
} from "@/lib/firehose";
import { useItems, useStats } from "@/lib/use-firehose";

/**
 * Verdict split. AI Elements has no stat or chart element, so this is the one
 * piece built by hand - on the same primitives, direct-labelled so nothing
 * depends on a colour that this theme does not have.
 */
const VerdictSplit = ({ stats }: { stats: Stats }) => {
  const counts = stats.by_verdict ?? {};
  const total = stats.total || 1;

  return (
    <div className="space-y-3">
      {VERDICTS.map((verdict) => {
        const n = counts[verdict] ?? 0;
        return (
          <div className="space-y-1.5" key={verdict}>
            <div className="flex items-baseline justify-between text-xs">
              <span className="capitalize">{verdict}</span>
              <span className="font-mono text-muted-foreground tabular-nums">
                {n} · {Math.round((n / total) * 100)}%
              </span>
            </div>
            <Progress className="h-1.5" value={(n / total) * 100} />
          </div>
        );
      })}
    </div>
  );
};

const Streams = ({ stats }: { stats: Stats }) => {
  const rows = Object.entries(stats.by_stream ?? {}).sort((a, b) => b[1] - a[1]);
  if (rows.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {rows.map(([id, n]) => (
        <Badge className="gap-1.5 font-normal" key={id} variant="secondary">
          {stats.streams?.[id] ?? id}
          <span className="font-mono tabular-nums">{n}</span>
        </Badge>
      ))}
    </div>
  );
};

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="space-y-3">
    <h3 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">{title}</h3>
    {children}
  </section>
);

export type DashboardProps = {
  activity: ToolPart[];
  cited: Item[];
  onClose?: () => void;
};

export const Dashboard = ({ activity, cited, onClose }: DashboardProps) => {
  const [tab, setTab] = useState<PileTab>("keep");

  const stats = useStats();
  const pile = useItems(tab);

  const refresh = useCallback(() => {
    stats.reload();
    pile.reload();
  }, [stats, pile]);

  const onTabChange = useCallback((value: string) => setTab(value as PileTab), []);

  const spend = useMemo(
    () =>
      activity.reduce((sum, part) => {
        const out = part.output as { cost_usd?: number } | null;
        return sum + (typeof out?.cost_usd === "number" ? out.cost_usd : 0);
      }, 0),
    [activity],
  );

  // a row the agent touched keeps whatever the agent measured about it - an
  // ask_jev probability is more interesting than the stored relevance
  const rows = useMemo(() => {
    const byId = new Map(cited.map((item) => [item.id, item]));
    return pile.items.map((item) => {
      const seen = byId.get(item.id);
      return seen ? { ...item, ...seen, cited: true } : item;
    });
  }, [pile.items, cited]);

  const corpus = stats.data;

  return (
    <Artifact className="h-full rounded-none border-0 shadow-none">
      <ArtifactHeader>
        <div className="min-w-0">
          <ArtifactTitle>Today&apos;s corpus</ArtifactTitle>
          <ArtifactDescription>
            {corpus
              ? `${corpus.total} items scored`
              : stats.loading
                ? "loading…"
                : "bridge unreachable"}
            {corpus?.mock ? " · mock data" : ""}
          </ArtifactDescription>
        </div>
        <ArtifactActions>
          <ArtifactAction
            disabled={stats.loading || pile.loading}
            icon={RefreshCwIcon}
            onClick={refresh}
            tooltip="Refresh"
          />
          {onClose && <ArtifactClose onClick={onClose} />}
        </ArtifactActions>
      </ArtifactHeader>

      <ArtifactContent className="space-y-6">
        {corpus ? (
          <>
            <Section title="Verdicts">
              <VerdictSplit stats={corpus} />
            </Section>
            <Section title="Streams">
              <Streams stats={corpus} />
            </Section>
          </>
        ) : (
          stats.loading && <Shimmer duration={1}>Counting the corpus…</Shimmer>
        )}

        <Separator />

        <Section title="The pile">
          <Tabs onValueChange={onTabChange} value={tab}>
            <TabsList className="w-full">
              {PILE_TABS.map(({ label, value }) => (
                <TabsTrigger key={value} value={value}>
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>

          {pile.loading && rows.length === 0 && <Shimmer duration={1}>Reading the pile…</Shimmer>}

          {pile.failed && (
            <p className="text-muted-foreground text-sm">
              Could not reach the bridge. The corpus is served by{" "}
              <code className="font-mono text-xs">/api/items</code>.
            </p>
          )}

          {!(pile.loading || pile.failed) && rows.length === 0 && (
            <p className="text-muted-foreground text-sm">Nothing in this pile today.</p>
          )}

          <div className="space-y-2">
            {rows.map((item) => (
              <ItemRow cited={item.cited} item={item} key={item.id} />
            ))}
          </div>
        </Section>

        <Separator />

        <Section title="Session activity">
          {activity.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Nothing yet. Ask a question and the agent&apos;s calls show up here.
            </p>
          ) : (
            <div className="space-y-4">
              {activity.map((part, i) => {
                const name = toolNameOf(part) ?? "tool";
                const meta = toolMeta(name);
                const note = summarise(name, part.input, part.output);
                const running = part.state !== "output-available" && part.state !== "output-error";

                return (
                  <Task defaultOpen={running} key={part.toolCallId ?? i}>
                    <TaskTrigger title={headline(name, part.input)} />
                    <TaskContent>
                      <TaskItem>
                        <TaskItemFile>
                          <meta.icon className="size-3" />
                          {name}
                        </TaskItemFile>{" "}
                        {running ? meta.blurb : note || meta.blurb}
                      </TaskItem>
                    </TaskContent>
                  </Task>
                );
              })}
              {spend > 0 && (
                <p className="text-muted-foreground text-xs">
                  Typed questions this session cost{" "}
                  <span className="font-mono tabular-nums">${spend.toFixed(6)}</span>.
                </p>
              )}
            </div>
          )}
        </Section>
      </ArtifactContent>
    </Artifact>
  );
};
