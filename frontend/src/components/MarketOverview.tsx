"use client";

import type { MarketItem } from "@/lib/api";

/**
 * 터미널 티커 + 국내 지표 테이블 스타일.
 * prop 시그니처는 기존 그대로.
 */

const GLOBAL_ORDER = ["sp500", "nasdaq", "dow", "nikkei", "shanghai"];
const INDICATOR_ORDER = ["vix", "usdkrw", "wti", "gold", "us10y"];

function Delta({ pct }: { pct: number }) {
  const cls = pct > 0 ? "ib-up" : pct < 0 ? "ib-dn" : "ib-faint";
  const s = pct > 0 ? "+" : "";
  return <span className={`ib-num ${cls}`}>{s}{pct.toFixed(2)}%</span>;
}

export default function MarketOverview({
  global_market,
  domestic_market,
}: {
  global_market: Record<string, MarketItem>;
  domestic_market: Record<string, MarketItem>;
}) {
  const globalItems = GLOBAL_ORDER.filter((k) => k in global_market).map((k) => global_market[k]);
  const indicators  = INDICATOR_ORDER.filter((k) => k in global_market).map((k) => global_market[k]);
  const allTickerItems = [...globalItems, ...indicators];
  const domesticItems = Object.values(domestic_market);

  if (allTickerItems.length === 0 && domesticItems.length === 0) {
    return (
      <div className="ib-card p-6 text-center ib-faint text-sm">
        시장 데이터를 아직 수집하지 못했습니다
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Ticker strip */}
      {allTickerItems.length > 0 && (
        <div
          className="flex gap-6 overflow-x-auto"
          style={{
            background: "var(--ib-bg-sunk)",
            border: "1px solid var(--ib-line)",
            padding: "10px 14px",
            fontFamily: "var(--ib-mono)",
            fontSize: 11,
          }}
        >
          {allTickerItems.map((item) => (
            <span key={item.label} className="whitespace-nowrap inline-flex gap-2 items-baseline">
              <span className="ib-dim" style={{ letterSpacing: "0.1em" }}>{item.label}</span>
              <span className="ib-num">{item.close.toLocaleString()}</span>
              <Delta pct={item.change_pct} />
            </span>
          ))}
        </div>
      )}

      {/* 국내 시장 */}
      {domesticItems.length > 0 && (
        <section className="ib-card">
          <div className="ib-card-h flex items-center gap-2.5 px-3.5 py-2.5">
            <span className="inline-block w-2.5 h-0.5" style={{ background: "var(--ib-warn)" }} />
            <span className="ib-label">국내 시장 · 전일 종가</span>
          </div>
          <table className="w-full ib-mono" style={{ fontSize: 12 }}>
            <tbody>
              {domesticItems.map((it) => (
                <tr key={it.label} style={{ borderBottom: "1px solid var(--ib-line-soft)" }}>
                  <td className="ib-dim px-3.5 py-2">{it.label}</td>
                  <td className="ib-num text-right px-3.5 py-2">
                    {it.close.toLocaleString()} <Delta pct={it.change_pct} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
