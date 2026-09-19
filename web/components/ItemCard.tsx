import React from "react";

export type Item = {
  id: string;
  title: string;
  url?: string;
  source?: string;
  verdict?: string;
  relevance?: number;
  certainty?: number;
  probability?: number;
  confidence?: number;
  level?: string;
  choice?: string;
  signals?: string;
};

function Bar({ label, value, hatched }: { label: string; value: number; hatched?: boolean }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <span className="bar">
      {label}
      <span className="track">
        <span
          className="fill"
          style={{
            width: `${pct}%`,
            background: hatched ? "var(--hatch)" : "var(--ink)",
          }}
        />
      </span>
      <b style={{ fontWeight: 650 }}>{value.toFixed(2)}</b>
    </span>
  );
}

/** One scored item. Numbers are direct-labelled so colour never carries meaning alone. */
export default function ItemCard({ item }: { item: Item }) {
  const relevance = item.relevance ?? item.probability;
  const certainty = item.certainty ?? item.confidence;
  const verdict = item.verdict ?? "";

  return (
    <div className="item">
      <div className="head">
        <div>
          <div className="title">
            {item.url ? (
              <a href={item.url} target="_blank" rel="noopener noreferrer">
                {item.title}
              </a>
            ) : (
              item.title
            )}
          </div>
          {(item.source || item.signals) && (
            <div className="src">{[item.source, item.signals].filter(Boolean).join(" · ")}</div>
          )}
        </div>
        {verdict && <span className={`tag ${verdict}`}>{verdict}</span>}
      </div>

      {(relevance !== undefined || certainty !== undefined || item.level || item.choice) && (
        <div className="bars">
          {relevance !== undefined && (
            <Bar label={item.probability !== undefined ? "probability" : "relevance"} value={relevance} />
          )}
          {certainty !== undefined && <Bar label="confidence" value={certainty} hatched />}
          {item.level && <span className="bar">level: <b style={{ fontWeight: 600 }}>{item.level}</b></span>}
          {item.choice && <span className="bar">choice: <b style={{ fontWeight: 600 }}>{item.choice}</b></span>}
        </div>
      )}
    </div>
  );
}
