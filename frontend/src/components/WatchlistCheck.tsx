"use client";

import { useState } from "react";

interface WatchlistItem {
  stock_code: string;
  stock_name: string;
  price: { close: number; change: number; change_pct: number } | null;
  news: ({ title: string; link?: string } | string)[];
  disclosures: { title: string; importance: string }[];
  summary: string;
}

function StockCard({ item }: { item: WatchlistItem }) {
  const [open, setOpen] = useState(false);
  const price = item.price;
  const isUp = price && price.change_pct > 0;
  const isDown = price && price.change_pct < 0;
  const hasDetail = item.news.length > 0 || item.disclosures.length > 0;

  return (
    <div className="ib-card">
      <button
        onClick={() => hasDetail && setOpen(!open)}
        className={`w-full text-left p-3.5 ${hasDetail ? "cursor-pointer" : ""}`}
        style={hasDetail ? ({ transition: "background .12s" } as React.CSSProperties) : undefined}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-baseline gap-2">
            <span style={{ fontSize: 13.5, fontWeight: 600 }}>{item.stock_name}</span>
            <span className="ib-mono ib-faint" style={{ fontSize: 10 }}>{item.stock_code}</span>
          </div>
          <div className="flex items-center gap-3">
            {price && (
              <>
                <span className="ib-num" style={{ fontSize: 13 }}>{price.close.toLocaleString()}</span>
                <span className={`ib-num ${isUp ? "ib-up" : isDown ? "ib-dn" : "ib-faint"}`} style={{ fontSize: 12 }}>
                  {isUp ? "+" : ""}{price.change_pct.toFixed(2)}%
                </span>
              </>
            )}
            {hasDetail && <span className="ib-faint ib-mono" style={{ fontSize: 10 }}>{open ? "▲" : "▼"}</span>}
          </div>
        </div>
        <div className="flex gap-2 mt-2">
          {item.news.length > 0 ? (
            <span className="ib-pill b"><span className="d" />뉴스 {item.news.length}</span>
          ) : (
            <span className="ib-pill ib-faint">뉴스 없음</span>
          )}
          {item.disclosures.length > 0 ? (
            <span className="ib-pill a"><span className="d" />공시 {item.disclosures.length}</span>
          ) : (
            <span className="ib-pill ib-faint">공시 없음</span>
          )}
        </div>
      </button>
      {open && (
        <div className="px-3.5 py-3 space-y-3" style={{ borderTop: "1px solid var(--ib-line-soft)", background: "var(--ib-bg-sunk)" }}>
          {item.news.length > 0 && (
            <div>
              <div className="ib-label mb-1.5">뉴스</div>
              <ul className="space-y-1">
                {item.news.map((n, i) => {
                  const title = typeof n === "string" ? n : n.title;
                  const link = typeof n === "string" ? "" : n.link || "";
                  return (
                    <li key={i} style={{ fontSize: 13, lineHeight: 1.55 }}>
                      ·{" "}
                      {link ? (
                        <a href={link} target="_blank" rel="noopener noreferrer" className="hover:underline">{title}</a>
                      ) : title}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
          {item.disclosures.length > 0 && (
            <div>
              <div className="ib-label mb-1.5">공시</div>
              <ul className="space-y-1">
                {item.disclosures.map((d, i) => (
                  <li key={i} style={{ fontSize: 13, lineHeight: 1.55 }}>{d.importance} {d.title}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function WatchlistCheck({ items }: { items: WatchlistItem[] }) {
  if (!items || items.length === 0) return null;
  return (
    <section>
      <div className="ib-label mb-2.5">관심종목 체크</div>
      <div className="space-y-2">
        {items.map((it) => <StockCard key={it.stock_code} item={it} />)}
      </div>
    </section>
  );
}
