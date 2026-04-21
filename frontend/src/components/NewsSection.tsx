"use client";

import { useState } from "react";

/** **bold** → <strong> */
function renderBold(text: string) {
  const parts = text.split(/\*\*(.*?)\*\*/g);
  return parts.map((p, i) =>
    i % 2 === 1 ? <strong key={i} style={{ color: "var(--ib-ink)", fontWeight: 600 }}>{p}</strong> : p
  );
}

/** 마크다운 헤딩/리스트 프리픽스 제거 */
function stripPrefix(line: string): string {
  return line
    .replace(/^#{1,6}\s*/, "")
    .replace(/^[-*•]\s+/, "")
    .replace(/^\d+[.)]\s+/, "")
    .replace(/^>\s*/, "")
    .trim();
}

/** 섹션 레이블("1. 핵심 이슈", "요약:", 등)인지 */
function isSectionLabel(line: string): boolean {
  const s = line.replace(/\*\*/g, "").trim();
  return /^(핵심\s*이슈|요약|오늘의\s*브리프|업종별\s*동향|summary|today)[:\s]*$/i.test(s);
}

export default function NewsSection({
  summary,
  newsRaw,
}: {
  summary: string;
  newsRaw: { title: string; link: string; source: string }[];
}) {
  const [showAll, setShowAll] = useState(false);

  // 마크다운 프리픽스 벗기고, 섹션 레이블 줄은 skip
  const lines = summary
    .split("\n")
    .map((l) => stripPrefix(l))
    .filter((l) => l && !isSectionLabel(l));
  const oneLiner = lines[0] ?? "";
  const rest = lines.slice(1);

  // 업종별 동향 분리
  const sectorIdx = rest.findIndex((l) => l.includes("업종별 동향"));
  const mainLines = sectorIdx >= 0 ? rest.slice(0, sectorIdx) : rest;
  const sectorLines = sectorIdx >= 0 ? rest.slice(sectorIdx) : [];

  return (
    <section className="space-y-3.5">
      {/* Hero one-liner */}
      {oneLiner && (
        <div
          className="grid gap-5 items-center"
          style={{
            gridTemplateColumns: "auto 1fr",
            padding: "18px 22px",
            background: "var(--ib-paper)",
            border: "1px solid var(--ib-line)",
            borderLeft: "3px solid var(--ib-warn)",
          }}
        >
          <div>
            <div className="ib-mono ib-warn-c" style={{ fontSize: 10, letterSpacing: "0.2em" }}>ONE LINE · AI</div>
            <div className="ib-label" style={{ marginTop: 6 }}>CLAUDE SONNET 4</div>
          </div>
          <div className="ib-serif" style={{ fontSize: 22, fontWeight: 500, letterSpacing: "-0.01em", lineHeight: 1.25 }}>
            {renderBold(oneLiner)}
          </div>
        </div>
      )}

      {/* AI 뉴스 요약 */}
      <section className="ib-card">
        <div className="ib-card-h flex items-center gap-2.5 px-3.5 py-2.5">
          <span className="inline-block w-2.5 h-0.5" style={{ background: "var(--ib-warn)" }} />
          <span className="ib-label">AI 뉴스 요약</span>
          <span className="ml-auto ib-label" style={{ letterSpacing: "0.08em" }}>{newsRaw.length}건 기반</span>
        </div>
        <div className="p-3.5">
          <div className="space-y-1.5" style={{ fontSize: 14, lineHeight: 1.55, color: "var(--ib-ink-dim)" }}>
            {mainLines.map((line, i) => <p key={i}>{renderBold(line)}</p>)}
          </div>
          {sectorLines.length > 0 && (
            <div className="mt-3 pt-3 space-y-1.5" style={{ borderTop: "1px dashed var(--ib-line)", color: "var(--ib-ink-dim)", fontSize: 13, lineHeight: 1.55 }}>
              {sectorLines.map((line, i) => <p key={i}>{renderBold(line)}</p>)}
            </div>
          )}
        </div>
        {newsRaw.length > 0 && (
          <div className="px-3.5 py-2.5" style={{ borderTop: "1px solid var(--ib-line-soft)", background: "var(--ib-bg-sunk)" }}>
            <button
              onClick={() => setShowAll(!showAll)}
              className="ib-mono ib-info-c"
              style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase" }}
            >
              {showAll ? "접기 ↑" : `뉴스 원본 ${newsRaw.length}건 ↓`}
            </button>
            {showAll && (
              <ul className="mt-2.5 space-y-1.5">
                {newsRaw.map((n, i) => (
                  <li key={i} style={{ fontSize: 12, lineHeight: 1.55 }}>
                    <a href={n.link} target="_blank" rel="noopener noreferrer" className="ib-dim hover:underline">
                      {n.title}
                    </a>
                    <span className="ib-faint ib-mono ml-1.5" style={{ fontSize: 10 }}>· {n.source}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>
    </section>
  );
}
