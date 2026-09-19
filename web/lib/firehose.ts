import {
  BarChart3Icon,
  FileTextIcon,
  type LucideIcon,
  SearchIcon,
  SparklesIcon,
  WrenchIcon,
} from "lucide-react";

/** One scored item, as the bridge's `brief()` / `full()` return it. */
export type Item = {
  id: string;
  title: string;
  url?: string;
  source?: string;
  stream?: string;
  verdict?: string;
  signals?: string;
  summary?: string;
  /** search_items */
  relevance?: number;
  certainty?: number;
  /** ask_jev, kind=noul */
  probability?: number;
  /** ask_jev, kind=choice */
  choice?: string;
  confidence?: number;
  /** ask_jev, kind=score */
  level?: string;
  score?: number;
  normalised?: number;
};

export type Stats = {
  total: number;
  by_verdict?: Record<string, number>;
  by_stream?: Record<string, number>;
  streams?: Record<string, string>;
  mock?: boolean;
  updated?: number;
};

export type AskJevOutput = {
  question?: string;
  kind?: string;
  asked?: number;
  summary?: Record<string, number>;
  cost_usd?: number;
  results?: Item[];
  error?: string;
};

/** A tool part off a UIMessage, narrowed to what this app reads. */
export type ToolPart = {
  type: string;
  toolCallId?: string;
  toolName?: string;
  state?: string;
  input?: unknown;
  output?: unknown;
  errorText?: string;
};

export const TOOLS: Record<string, { title: string; blurb: string; icon: LucideIcon }> = {
  ask_jev: {
    blurb: "asking Jev a brand new typed question",
    icon: SparklesIcon,
    title: "Ask Jev",
  },
  corpus_stats: { blurb: "counting the corpus", icon: BarChart3Icon, title: "Corpus stats" },
  get_item: { blurb: "opening one item", icon: FileTextIcon, title: "Open item" },
  search_items: { blurb: "searching what Jev scored", icon: SearchIcon, title: "Search items" },
};

export const toolMeta = (name: string) =>
  TOOLS[name] ?? { blurb: "", icon: WrenchIcon, title: name };

/** `dynamic-tool` parts carry the name in a field; typed ones encode it in the type. */
export const toolNameOf = (part: ToolPart): string | null => {
  if (part.type === "dynamic-tool") return part.toolName ?? "tool";
  if (part.type.startsWith("tool-")) return part.type.slice(5);
  return null;
};

export const isToolPart = (part: { type: string }): boolean =>
  part.type === "dynamic-tool" || part.type.startsWith("tool-");

/** A one-line account of what a finished call actually did. */
export const summarise = (name: string, input: unknown, output: unknown): string => {
  const i = (input ?? {}) as Record<string, unknown>;

  if (name === "ask_jev") {
    const o = (output ?? {}) as AskJevOutput;
    if (o.error) return o.error;
    if (o.asked === undefined) return String(i.question ?? "");
    return `${o.asked} item${o.asked === 1 ? "" : "s"} asked · $${(o.cost_usd ?? 0).toFixed(6)}`;
  }

  if (name === "search_items") {
    const n = Array.isArray(output) ? output.length : undefined;
    const q = i.query ? `“${String(i.query)}”` : "top ranked";
    const scope = [i.verdict, i.stream].filter((v) => v && v !== "any").join(" · ");
    const head = scope ? `${q} · ${scope}` : q;
    return n === undefined ? head : `${head} · ${n} hit${n === 1 ? "" : "s"}`;
  }

  if (name === "get_item") return String(i.item_id ?? "");

  if (name === "corpus_stats") {
    const o = (output ?? {}) as { total?: number };
    return o.total === undefined ? "" : `${o.total} items`;
  }

  return "";
};

/** The question a call is really asking, for step labels. */
export const headline = (name: string, input: unknown): string => {
  const i = (input ?? {}) as Record<string, unknown>;
  if (name === "ask_jev" && i.question) return String(i.question);
  if (name === "search_items") return i.query ? `Search “${String(i.query)}”` : "Top ranked items";
  return toolMeta(name).title;
};

/** Rows a tool result contributes to the item list, if any. */
export const itemsFrom = (name: string, output: unknown): Item[] => {
  if (name === "search_items" && Array.isArray(output)) return output as Item[];
  if (name === "ask_jev") {
    const o = output as AskJevOutput | null;
    if (o && Array.isArray(o.results)) return o.results;
  }
  if (name === "get_item" && output && typeof output === "object" && "title" in output) {
    return [output as Item];
  }
  return [];
};

/** The number the model actually leaned on for this row, direct-labelled. */
export const scoreOf = (item: Item): { label: string; value: number } | null => {
  if (item.probability !== undefined) return { label: "probability", value: item.probability };
  if (item.normalised !== undefined) return { label: item.level ?? "score", value: item.normalised };
  if (item.confidence !== undefined) return { label: item.choice ?? "confidence", value: item.confidence };
  if (item.relevance !== undefined) return { label: "relevance", value: item.relevance };
  return null;
};

export const VERDICTS = ["keep", "review", "drop"] as const;
export type Verdict = (typeof VERDICTS)[number];
