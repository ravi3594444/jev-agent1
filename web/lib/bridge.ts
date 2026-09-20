/**
 * Server-side only. The bridge's address and token live here and never reach
 * the browser - every call the UI makes goes through a route handler in
 * app/api, so there is no CORS to configure and no host to expose.
 */
import "server-only";

export const BRIDGE = process.env.FIREHOSE_BRIDGE ?? "http://127.0.0.1:8000";

const TOKEN = process.env.FIREHOSE_TOKEN ?? "";

export const bridgeHeaders = (extra: Record<string, string> = {}): Record<string, string> =>
  TOKEN ? { ...extra, authorization: `Bearer ${TOKEN}` } : extra;

/** A GET the browser asked for, proxied verbatim. Never throws. */
export const bridgeGet = async (path: string): Promise<Response> => {
  try {
    const r = await fetch(`${BRIDGE}${path}`, { cache: "no-store", headers: bridgeHeaders() });
    if (!r.ok) {
      return new Response(JSON.stringify({ error: `bridge ${r.status}` }), {
        headers: { "content-type": "application/json" },
        status: 502,
      });
    }
    return new Response(await r.text(), {
      headers: { "cache-control": "no-store", "content-type": "application/json" },
    });
  } catch {
    return new Response(JSON.stringify({ error: "bridge unreachable" }), {
      headers: { "content-type": "application/json" },
      status: 502,
    });
  }
};
