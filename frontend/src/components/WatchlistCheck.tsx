"use client";

import { useState } from "react";

interface WatchlistItem {
  stock_code: string;
  stock_name: string;
  price: { close: number; change: number; change_pct: number } | null;
  news: string[];
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
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      {/* 요약 (항상 표시) — 클릭으로 토글 */}
      <button
        onClick={() => hasDetail && setOpen(!open)}
        className={`w-full text-left p-4 ${hasDetail ? "cursor-pointer hover:bg-gray-50/50 transition-colors" : ""}`}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm text-gray-800">{item.stock_name}</span>
            <span className="text-[11px] text-gray-300">{item.stock_code}</span>
          </div>
          <div className="flex items-center gap-2">
            {price && (
              <div className="text-right">
                <span className="font-semibold text-sm tabular-nums">
                  {price.close.toLocaleString()}원
                </span>
                <span
                  className={`text-xs font-medium ml-1.5 tabular-nums ${
                    isUp ? "text-rose-500" : isDown ? "text-blue-500" : "text-gray-400"
                  }`}
                >
                  {isUp ? "▲" : isDown ? "▼" : "—"} {Math.abs(price.change_pct).toFixed(2)}%
                </span>
              </div>
            )}
            {hasDetail && (
              <span className="text-gray-300 text-xs ml-1">{open ? "▲" : "▼"}</span>
            )}
          </div>
        </div>

        <div className="flex flex-wrap gap-x-3 mt-1.5 text-xs text-gray-400">
          {item.news.length > 0 && <span>뉴스 {item.news.length}건</span>}
          {item.news.length === 0 && <span>뉴스 없음</span>}
          {item.disclosures.length > 0 && <span>공시 {item.disclosures.length}건</span>}
          {item.disclosures.length === 0 && <span>공시 없음</span>}
        </div>
      </button>

      {/* 상세 (펼침) */}
      {open && (
        <div className="border-t border-gray-100 px-4 py-3 bg-gray-50/30 space-y-3">
          {/* 뉴스 상세 */}
          {item.news.length > 0 && (
            <div>
              <div className="text-[11px] font-semibold text-gray-400 mb-1.5">📰 뉴스</div>
              <ul className="space-y-1">
                {item.news.map((title, i) => (
                  <li key={i} className="text-sm text-gray-700 leading-relaxed">
                    • {title}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 공시 상세 */}
          {item.disclosures.length > 0 && (
            <div>
              <div className="text-[11px] font-semibold text-gray-400 mb-1.5">📋 공시</div>
              <ul className="space-y-1">
                {item.disclosures.map((d, i) => (
                  <li key={i} className="text-sm text-gray-700 leading-relaxed">
                    {d.importance} {d.title}
                  </li>
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
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        🔍 관심종목 체크
      </h2>
      <div className="space-y-2">
        {items.map((item) => (
          <StockCard key={item.stock_code} item={item} />
        ))}
      </div>
    </section>
  );
}
