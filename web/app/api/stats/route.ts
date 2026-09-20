import { bridgeGet } from "@/lib/bridge";

/** Proxy so the browser never talks to the bridge directly (no CORS, no exposed host). */
export async function GET() {
  return bridgeGet("/api/stats");
}
