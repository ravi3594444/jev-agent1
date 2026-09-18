const BRIDGE = process.env.FIREHOSE_BRIDGE ?? "http://127.0.0.1:8000";
const TOKEN = process.env.FIREHOSE_TOKEN ?? "";

/** Server-side only — the bridge token never reaches the browser. */
function bridgeHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return TOKEN ? { ...extra, authorization: `Bearer ${TOKEN}` } : extra;
}

/** Proxy so the browser never talks to the bridge directly (no CORS, no exposed host). */
export async function GET() {
  try {
    const r = await fetch(`${BRIDGE}/api/stats`, { cache: "no-store", headers: bridgeHeaders() });
    if (!r.ok) return new Response("{}", { status: 502, headers: { "content-type": "application/json" } });
    return new Response(await r.text(), {
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  } catch {
    return new Response("{}", { status: 502, headers: { "content-type": "application/json" } });
  }
}
