"use client";

import { LayersIcon, RefreshCwIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

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
import { Task, TaskContent, TaskItem, TaskItemFile, TaskTrigger } from "@/components/ai-elements/task";
import { ItemRow } from "@/components/item-row";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  headline,
  type Item,
  type Stats,
  summarise,
  type ToolPart,
  toolMeta,
  toolNameOf,
  VERDICTS,
} from "@/lib/firehose";

const useStats = () => {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    fetch("/api/stats", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: Stats) => setStats(d))
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  return { load, loading, stats };
};

/**
 * Verdict split. AI Elements has no stat or chart element, so this is the one
 * piece built by hand - on the same primitives, direct-labelled so a colour
 * never carries the meaning alone.
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
  items: Item[];
  onClose?: () => void;
};

export const Dashboard = ({ activity, items, onClose }: DashboardProps) => {
  const { stats, loading, load } = useStats();

  const spend = useMemo(
    () =>
      activity.reduce((sum, part) => {
        const out = part.output as { cost_usd?: number } | null;
        return sum + (typeof out?.cost_usd === "number" ? out.cost_usd : 0);
      }, 0),
    [activity],
  );

  return (
    <Artifact className="h-full rounded-none border-0 shadow-none">
      <ArtifactHeader>
        <div className="min-w-0">
          <ArtifactTitle>Today&apos;s corpus</ArtifactTitle>
          <ArtifactDescription>
            {stats ? `${stats.total} items scored` : loading ? "loading…" : "bridge unreachable"}
            {stats?.mock ? " · mock data" : ""}
          </ArtifactDescription>
        </div>
        <ArtifactActions>
          <ArtifactAction
            disabled={loading}
            icon={RefreshCwIcon}
            onClick={load}
            tooltip="Refresh stats"
          />
          {onClose && <ArtifactClose onClick={onClose} />}
        </ArtifactActions>
      </ArtifactHeader>

      <ArtifactContent className="space-y-6">
        {stats ? (
          <>
            <Section title="Verdicts">
              <VerdictSplit stats={stats} />
            </Section>
            <Section title="Streams">
              <Streams stats={stats} />
            </Section>
          </>
        ) : (
          loading && <Shimmer duration={1}>Counting the corpus…</Shimmer>
        )}

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

        <Separator />

        <Section title={`Items surfaced${items.length ? ` (${items.length})` : ""}`}>
          {items.length === 0 ? (
            <p className="flex items-center gap-2 text-muted-foreground text-sm">
              <LayersIcon className="size-4" />
              Items the agent opens or ranks collect here.
            </p>
          ) : (
            <div className="space-y-2">
              {items.slice(0, 24).map((item) => (
                <ItemRow item={item} key={item.id} />
              ))}
              {items.length > 24 && (
                <p className="text-muted-foreground text-xs">+{items.length - 24} more</p>
              )}
            </div>
          )}
        </Section>
      </ArtifactContent>
    </Artifact>
  );
};
