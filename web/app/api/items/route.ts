import { bridgeGet } from "@/lib/bridge";

const VERDICTS = new Set(["keep", "review", "drop", "any"]);
const MAX_LIMIT = 200;
const DEFAULT_LIMIT = 40;

/**
 * The scored pile itself, so the UI has something to show before anyone asks a
 * question. Parameters are rebuilt rather than forwarded, so nothing the
 * browser sends reaches the bridge unchecked.
 */
export async function GET(req: Request) {
  const asked = new URL(req.url).searchParams;

  const verdict = asked.get("verdict") ?? "keep";
  const limit = Number.parseInt(asked.get("limit") ?? "", 10);

  const query = new URLSearchParams({
    limit: String(Number.isFinite(limit) ? Math.min(Math.max(limit, 1), MAX_LIMIT) : DEFAULT_LIMIT),
    q: (asked.get("q") ?? "").slice(0, 200),
    stream: (asked.get("stream") ?? "any").slice(0, 64),
    verdict: VERDICTS.has(verdict) ? verdict : "keep",
  });

  return bridgeGet(`/api/items?${query}`);
}
