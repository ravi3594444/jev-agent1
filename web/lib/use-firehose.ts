"use client";

import { useCallback, useEffect, useState } from "react";

import type { Item, Stats, Verdict } from "@/lib/firehose";

type Load<T> = { data: T | null; loading: boolean; failed: boolean; reload: () => void };

const useEndpoint = <T,>(url: string): Load<T> => {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    setLoading(true);

    fetch(url, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: T) => {
        if (!alive) return;
        setData(d);
        setFailed(false);
      })
      .catch(() => alive && setFailed(true))
      .finally(() => alive && setLoading(false));

    return () => {
      // a slow response for an abandoned filter must not overwrite the new one
      alive = false;
    };
  }, [url, nonce]);

  return { data, failed, loading, reload };
};

export const useStats = () => useEndpoint<Stats>("/api/stats");

/**
 * True below Tailwind's `lg`, once mounted. Used to decide what to *render*
 * rather than what to hide, so the narrow layout does not pay for the wide
 * one's data. The server render says false; the rail owns the pile there.
 */
export const useBelowLg = () => {
  const [below, setBelow] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1023.98px)");
    const sync = () => setBelow(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  return below;
};

/** The scored pile for one verdict - what the corpus holds, before anyone asks. */
export const useItems = (verdict: Verdict | "any", limit = 40) => {
  const { data, ...rest } = useEndpoint<{ items?: Item[] }>(
    `/api/items?verdict=${verdict}&limit=${limit}`,
  );
  return { items: data?.items ?? [], ...rest };
};
