"use client";

import { useState } from "react";
import type { Disclosure } from "@/lib/api";

const IMPORTANCE_ORDER = ["🔴", "🟡", "🟢", "⚪"];
const IMPORTANCE_TO_SIGNAL: Record<string, "g" | "r" | "a" | ""> = {
  "🔴": "r",
  "🟡": "a",
  "🟢": "g",
  "⚪": "",
};
const SIGNAL_LABEL: Record<string, string> = { r: "위험", a: "주의", g: "호재", "": "정보" };

function dartUrl(rcept_no: string) {
  return `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${rcept_no}`;
}

export default function DisclosureList({ disclosures }: { disclosures: Disclosure[] }) {
  const [showAll, setShowAll] = useState(false);
  if (disclosures.length === 0) return null;

  const sorted = [...disclosures].sort(
    (a, b) => IMPORTANCE_ORDER.indexOf(a.importance) - IMPORTANCE_ORDER.indexOf(b.importance)
  );
  const important = sorted.filter((d) => d.importance !== "⚪");
  const display = showAll ? sorted : important.length > 0 ? important.slice(0, 10) : sorted.slice(0, 5);

  return (
    <section className="ib-card">
      <div className="ib-card-h flex items-center gap-2.5 px-3.5 py-2.5">
        <span className="inline-block w-2.5 h-0.5" style={{ background: "var(--ib-warn)" }} />
        <span className="ib-label">주요 공시 · DART</span>
        <span className="ml-auto ib-label" style={{ letterSpacing: "0.08em" }}>{disclosures.length}건</span>
      </div>
      <table className="w-full" style={{ fontFamily: "var(--ib-mono)", fontSize: 12, borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ background: "var(--ib-bg-sunk)", color: "var(--ib-ink-faint)" }}>
            <th className="text-left px-3 py-2" style={{ fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", fontWeight: 500, width: 80 }}>신호</th>
            <th className="text-left px-3 py-2" style={{ fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", fontWeight: 500, width: 140 }}>종목</th>
            <th className="text-left px-3 py-2" style={{ fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", fontWeight: 500 }}>공시</th>
          </tr>
        </thead>
        <tbody>
          {display.map((d, i) => {
            const sig = IMPORTANCE_TO_SIGNAL[d.importance] ?? "";
            const label = SIGNAL_LABEL[sig];
            return (
              <tr key={i} style={{ borderBottom: "1px solid var(--ib-line-soft)" }}>
                <td className="px-3 py-2 align-top">
                  <span className={`ib-pill ${sig}`}><span className="d" />{label}</span>
                </td>
                <td className="px-3 py-2 align-top">
                  <div style={{ color: "var(--ib-ink)" }}>{d.corp_name}</div>
                  <div className="ib-faint" style={{ fontSize: 10 }}>{d.stock_code}</div>
                </td>
                <td className="px-3 py-2 align-top">
                  {d.rcept_no ? (
                    <a href={dartUrl(d.rcept_no)} target="_blank" rel="noopener noreferrer" style={{ color: "var(--ib-ink)" }} className="hover:underline">
                      {d.title}
                    </a>
                  ) : (
                    <span style={{ color: "var(--ib-ink)" }}>{d.title}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {disclosures.length > display.length && (
        <div className="px-3.5 py-2.5" style={{ borderTop: "1px solid var(--ib-line-soft)", background: "var(--ib-bg-sunk)" }}>
          <button
            onClick={() => setShowAll(!showAll)}
            className="ib-mono ib-info-c"
            style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase" }}
          >
            {showAll ? "접기 ↑" : `전체 ${disclosures.length}건 ↓`}
          </button>
        </div>
      )}
    </section>
  );
}
