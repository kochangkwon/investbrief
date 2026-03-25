"use client";

import { useState } from "react";
import type { Disclosure } from "@/lib/api";

const IMPORTANCE_ORDER = ["🔴", "🟡", "🟢", "⚪"];
const IMPORTANCE_BG: Record<string, string> = {
  "🔴": "bg-red-50 border-red-100",
  "🟡": "bg-amber-50 border-amber-100",
  "🟢": "bg-emerald-50 border-emerald-100",
  "⚪": "",
};

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
    <section>
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        📋 공시 ({disclosures.length}건)
      </h2>
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <ul className="divide-y divide-gray-50">
          {display.map((d, i) => (
            <li
              key={i}
              className={`px-4 py-2.5 text-sm ${IMPORTANCE_BG[d.importance] || ""}`}
            >
              <div className="flex items-start gap-2">
                <span className="shrink-0 mt-0.5">{d.importance}</span>
                <span className="font-medium text-gray-800 shrink-0">{d.corp_name}</span>
                {d.rcept_no ? (
                  <a
                    href={dartUrl(d.rcept_no)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-gray-500 hover:text-blue-600 transition-colors truncate"
                  >
                    {d.title}
                    <span className="text-[10px] text-gray-300 ml-1 hidden sm:inline">↗</span>
                  </a>
                ) : (
                  <span className="text-gray-500 truncate">{d.title}</span>
                )}
              </div>
            </li>
          ))}
        </ul>
        {disclosures.length > display.length && (
          <div className="border-t border-gray-50 px-4 py-2 bg-gray-50/50">
            <button
              onClick={() => setShowAll(!showAll)}
              className="text-xs text-blue-500 hover:text-blue-700 font-medium"
            >
              {showAll ? "접기 ↑" : `전체 보기 (${disclosures.length}건) ↓`}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
