"use client";

import React, { useEffect, useState } from "react";

type Stats = {
  total: number;
  by_verdict?: Record<string, number>;
  mock?: boolean;
};

const BRIDGE_PROXY = "/api/stats";

export default function StatsBar() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch(BRIDGE_PROXY)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: Stats) => alive && setStats(d))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  if (failed || !stats) return null;
  const v = stats.by_verdict ?? {};

  return (
    <div className="pills">
      <span className="pill"><i style={{ background: "var(--good)" }} />keep <b>{v.keep ?? 0}</b></span>
      <span className="pill"><i style={{ background: "var(--warning)" }} />review <b>{v.review ?? 0}</b></span>
      <span className="pill"><i style={{ background: "var(--neutral)" }} />dropped <b>{v.drop ?? 0}</b></span>
      <span className="pill">scored <b>{stats.total}</b></span>
    </div>
  );
}
