"use client";

import type { MarketItem } from "@/lib/api";

const GLOBAL_ORDER = ["sp500", "nasdaq", "dow", "nikkei", "shanghai"];
const INDICATOR_ORDER = ["vix", "usdkrw", "wti", "gold", "us10y"];

function MarketCard({ item }: { item: MarketItem }) {
  const isUp = item.change_pct > 0;
  const isDown = item.change_pct < 0;

  return (
    <div className="bg-white rounded-xl border border-gray-100 p-3 text-center shadow-sm hover:shadow transition-shadow">
      <div className="text-[11px] text-gray-400 font-medium mb-1">{item.label}</div>
      <div className="font-semibold text-[15px] tabular-nums">{item.close.toLocaleString()}</div>
      <div
        className={`text-xs font-semibold mt-0.5 tabular-nums ${
          isUp ? "text-rose-500" : isDown ? "text-blue-500" : "text-gray-400"
        }`}
      >
        {isUp ? "▲" : isDown ? "▼" : "—"} {Math.abs(item.change_pct).toFixed(2)}%
      </div>
    </div>
  );
}

function IndicatorRow({ items }: { items: MarketItem[] }) {
  if (items.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
      {items.map((item) => {
        const isUp = item.change_pct > 0;
        const isDown = item.change_pct < 0;
        const color = isUp ? "text-rose-500" : isDown ? "text-blue-500" : "text-gray-400";
        return (
          <span key={item.label}>
            {item.label}{" "}
            <span className="font-medium text-gray-700">{item.close.toLocaleString()}</span>{" "}
            <span className={`font-medium ${color}`}>
              {isUp ? "+" : ""}{item.change_pct.toFixed(2)}%
            </span>
          </span>
        );
      })}
    </div>
  );
}

export default function MarketOverview({
  global_market,
  domestic_market,
}: {
  global_market: Record<string, MarketItem>;
  domestic_market: Record<string, MarketItem>;
}) {
  const globalCards = GLOBAL_ORDER.filter((k) => k in global_market).map((k) => global_market[k]);
  const indicators = INDICATOR_ORDER.filter((k) => k in global_market).map((k) => global_market[k]);
  const domesticCards = Object.values(domestic_market);

  if (globalCards.length === 0 && domesticCards.length === 0) {
    return (
      <div className="bg-white rounded-xl border border-gray-100 p-6 text-center text-sm text-gray-400">
        시장 데이터를 아직 수집하지 못했습니다
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {globalCards.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            🌍 글로벌 시장
          </h2>
          <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">{globalCards.map((i) => <MarketCard key={i.label} item={i} />)}</div>
          {indicators.length > 0 && (
            <div className="mt-2 px-1">
              <IndicatorRow items={indicators} />
            </div>
          )}
        </section>
      )}
      {domesticCards.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            📊 국내 시장
          </h2>
          <div className="grid grid-cols-2 gap-2 max-w-[240px]">
            {domesticCards.map((i) => <MarketCard key={i.label} item={i} />)}
          </div>
        </section>
      )}
    </div>
  );
}
