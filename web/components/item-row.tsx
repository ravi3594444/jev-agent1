"use client";

import { ExternalLinkIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { type Item, scoreOf } from "@/lib/firehose";
import { cn } from "@/lib/utils";

const VERDICT_VARIANT = {
  drop: "outline",
  keep: "default",
  review: "secondary",
} as const;

export type ItemRowProps = {
  item: Item;
  className?: string;
};

/**
 * One scored record. AI Elements has no component for a ranked corpus row, so
 * this is built from the same shadcn primitives the rest of the kit uses.
 */
export const ItemRow = ({ item, className }: ItemRowProps) => {
  const measure = scoreOf(item);
  const verdict = item.verdict as keyof typeof VERDICT_VARIANT | undefined;
  const meta = [item.source, item.stream, item.signals].filter(Boolean).join(" · ");

  return (
    <div className={cn("space-y-2 rounded-md border bg-card p-3", className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          {item.url ? (
            <a
              className="flex items-start gap-1.5 font-medium text-sm hover:underline"
              href={item.url}
              rel="noreferrer"
              target="_blank"
            >
              <span className="line-clamp-2">{item.title}</span>
              <ExternalLinkIcon className="mt-0.5 size-3 shrink-0 text-muted-foreground" />
            </a>
          ) : (
            <p className="line-clamp-2 font-medium text-sm">{item.title}</p>
          )}
          {meta && <p className="line-clamp-1 text-muted-foreground text-xs">{meta}</p>}
        </div>
        {verdict && (
          <Badge className="shrink-0 capitalize" variant={VERDICT_VARIANT[verdict] ?? "outline"}>
            {verdict}
          </Badge>
        )}
      </div>

      {measure && (
        <div className="flex items-center gap-2">
          <span className="w-24 shrink-0 truncate text-muted-foreground text-xs">
            {measure.label}
          </span>
          <Progress className="h-1.5" value={Math.max(0, Math.min(1, measure.value)) * 100} />
          <span className="w-10 shrink-0 text-right font-mono text-xs tabular-nums">
            {measure.value.toFixed(2)}
          </span>
        </div>
      )}
    </div>
  );
};
