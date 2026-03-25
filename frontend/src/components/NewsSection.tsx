"use client";

import { useState } from "react";

/** **bold** 마크다운을 <strong>으로 변환 */
function renderBold(text: string) {
  const parts = text.split(/\*\*(.*?)\*\*/g);
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i} className="font-semibold text-gray-800">{part}</strong> : part
  );
}

export default function NewsSection({
  summary,
  newsRaw,
}: {
  summary: string;
  newsRaw: { title: string; link: string; source: string }[];
}) {
  const [showAll, setShowAll] = useState(false);

  // 요약을 "핵심 이슈"와 "업종별 동향"으로 분리
  const sectorIdx = summary.indexOf("업종별 동향");
  const mainSummary = sectorIdx > 0 ? summary.slice(0, sectorIdx) : summary;
  const sectorSummary = sectorIdx > 0 ? summary.slice(sectorIdx) : "";

  return (
    <section>
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        📰 AI 뉴스 요약
      </h2>
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="p-4">
          <div className="text-sm leading-relaxed text-gray-700 space-y-1">
            {mainSummary.split("\n").map((line, i) => {
              const trimmed = line.trim();
              if (!trimmed) return null;
              return <p key={i}>{renderBold(trimmed)}</p>;
            })}
          </div>
        </div>
        {sectorSummary && (
          <div className="border-t border-gray-100 p-4 bg-slate-50/50">
            <div className="text-sm leading-relaxed text-gray-600 space-y-1">
              {sectorSummary.split("\n").map((line, i) => {
                const trimmed = line.trim();
                if (!trimmed) return null;
                return <p key={i}>{renderBold(trimmed)}</p>;
              })}
            </div>
          </div>
        )}
        {newsRaw.length > 0 && (
          <div className="border-t border-gray-50 px-4 py-2.5 bg-gray-50/50">
            <button
              onClick={() => setShowAll(!showAll)}
              className="text-xs text-blue-500 hover:text-blue-700 font-medium transition-colors"
            >
              {showAll ? "접기 ↑" : `뉴스 원본 보기 (${newsRaw.length}건) ↓`}
            </button>
            {showAll && (
              <ul className="mt-2 space-y-1.5">
                {newsRaw.map((news, i) => (
                  <li key={i} className="text-xs leading-relaxed">
                    <a
                      href={news.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-gray-600 hover:text-blue-600 transition-colors"
                    >
                      {news.title}
                    </a>
                    <span className="text-gray-300 ml-1.5">{news.source}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
