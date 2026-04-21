"use client";

import { useEffect, useState } from "react";
import { fetchBriefList, fetchBriefByDate } from "@/lib/api";
import type { DailyBrief } from "@/lib/api";
import MarketOverview from "@/components/MarketOverview";
import NewsSection from "@/components/NewsSection";
import DisclosureList from "@/components/DisclosureList";
import WatchlistCheck from "@/components/WatchlistCheck";

interface BriefSummary {
  id: number;
  date: string;
  news_summary: string;
  created_at: string;
}

/** news_summary에서 마크다운 헤딩/볼드/리스트 기호를 벗기고 첫 유의미한 문장을 뽑는다 */
function extractHeadline(summary: string): string {
  if (!summary) return "";
  const lines = summary.split("\n");
  for (const raw of lines) {
    let line = raw.trim();
    if (!line) continue;
    // 헤딩(#, ##, ###), 리스트(-, *, •, 1.), 블록인용(>) 프리픽스 제거
    line = line.replace(/^#{1,6}\s*/, "");
    line = line.replace(/^[-*•]\s+/, "");
    line = line.replace(/^\d+[.)]\s+/, "");
    line = line.replace(/^>\s*/, "");
    // "1. 핵심 이슈", "핵심 이슈:", "요약:" 같은 섹션 레이블은 스킵
    if (/^(핵심\s*이슈|요약|오늘의\s*브리프|summary|today)[:\s]*$/i.test(line)) continue;
    // 인라인 마크다운 제거
    line = line.replace(/\*\*(.+?)\*\*/g, "$1").replace(/\*(.+?)\*/g, "$1");
    line = line.replace(/`([^`]+)`/g, "$1");
    if (line.length < 4) continue;
    return line;
  }
  return summary.replace(/[#*`>]/g, "").trim().split("\n")[0] ?? "";
}

export default function ArchivePage() {
  const [list, setList] = useState<BriefSummary[]>([]);
  const [selected, setSelected] = useState<DailyBrief | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchBriefList(30).then(setList).finally(() => setLoading(false));
  }, []);

  async function handleSelect(date: string) {
    setSelected(await fetchBriefByDate(date));
  }

  if (loading) return <div className="py-32 text-center ib-faint ib-mono text-sm">LOADING...</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-4">
        <h1 className="ib-serif" style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-0.015em", margin: 0 }}>
          아카이브 · 서사로 읽기
        </h1>
        <div className="ib-mono ib-dim" style={{ fontSize: 11, letterSpacing: "0.1em" }}>
          VOL.{String(list.length).padStart(3, "0")} · 총 {list.length}편
        </div>
      </div>

      {list.length === 0 ? (
        <div className="py-20 text-center ib-faint text-sm">저장된 브리프가 없습니다</div>
      ) : (
        <div className="grid gap-6" style={{ gridTemplateColumns: "240px 1fr" }}>
          {/* Index */}
          <aside className="sticky top-[76px] self-start">
            <div className="ib-label mb-2">INDEX</div>
            <div className="space-y-1">
              {list.map((item) => {
                const on = selected?.date === item.date;
                const d = new Date(item.date + "T00:00:00");
                const mm = d.getMonth() + 1;
                const dd = d.getDate();
                return (
                  <button
                    key={item.id}
                    onClick={() => handleSelect(item.date)}
                    className="w-full text-left ib-mono"
                    style={{
                      padding: "5px 8px",
                      color: on ? "var(--ib-ink)" : "var(--ib-ink-dim)",
                      background: on ? "var(--ib-bg-sunk)" : "transparent",
                      borderLeft: `2px solid ${on ? "var(--ib-warn)" : "transparent"}`,
                      fontSize: 12,
                    }}
                  >
                    <div className="flex justify-between">
                      <span>· {String(mm).padStart(2,"0")}/{String(dd).padStart(2,"0")}</span>
                      <span className="ib-faint" style={{ fontSize: 10 }}>
                        {["일","월","화","수","목","금","토"][d.getDay()]}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>

          {/* Timeline */}
          <section>
            {selected ? (
              <BriefEntry brief={selected} />
            ) : (
              // 전체 목록 편집 톤
              <div className="space-y-0" style={{ borderTop: "1px solid var(--ib-ink)" }}>
                {list.map((item, idx) => {
                  const d = new Date(item.date + "T00:00:00");
                  const weekday = ["SUN","MON","TUE","WED","THU","FRI","SAT"][d.getDay()];
                  const firstLine = extractHeadline(item.news_summary);
                  const isLatest = idx === 0;
                  return (
                    <article
                      key={item.id}
                      className="grid gap-6 py-6 cursor-pointer"
                      style={{
                        gridTemplateColumns: "140px 1fr auto",
                        borderBottom: "1px solid var(--ib-line)",
                      }}
                      onClick={() => handleSelect(item.date)}
                    >
                      <div className="ib-mono ib-dim" style={{ fontSize: 11, letterSpacing: "0.1em" }}>
                        <span className="ib-serif block" style={{
                          fontSize: 40, fontWeight: 700, lineHeight: 1,
                          color: isLatest ? "var(--ib-warn)" : "var(--ib-ink)",
                          letterSpacing: "-0.02em", marginBottom: 2,
                        }}>{String(d.getDate()).padStart(2,"0")}</span>
                        <span>{weekday} · {d.getMonth()+1}월</span>
                      </div>
                      <div>
                        <h2 className="ib-serif" style={{
                          margin: "0 0 8px", fontSize: 22, fontWeight: 700,
                          letterSpacing: "-0.01em", lineHeight: 1.25,
                          textWrap: "pretty" as any,
                        }}>
                          {isLatest && (
                            <span className="ib-mono" style={{
                              fontSize: 10, background: "var(--ib-warn)", color: "var(--ib-bg)",
                              padding: "2px 6px", marginRight: 8, letterSpacing: "0.14em", verticalAlign: "middle",
                            }}>LATEST</span>
                          )}
                          {firstLine || "(요약 없음)"}
                        </h2>
                      </div>
                      <div className="ib-mono ib-faint" style={{ fontSize: 10, letterSpacing: "0.1em", whiteSpace: "nowrap" }}>
                        READ →
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function BriefEntry({ brief }: { brief: DailyBrief }) {
  const d = new Date(brief.date + "T00:00:00");
  const weekday = ["SUN","MON","TUE","WED","THU","FRI","SAT"][d.getDay()];

  return (
    <div className="space-y-5">
      <div className="grid gap-6 pb-6" style={{
        gridTemplateColumns: "140px 1fr",
        borderTop: "1px solid var(--ib-ink)",
        borderBottom: "1px solid var(--ib-line)",
        paddingTop: 26,
      }}>
        <div className="ib-mono ib-dim" style={{ fontSize: 11, letterSpacing: "0.1em" }}>
          <span className="ib-serif ib-warn-c block" style={{
            fontSize: 40, fontWeight: 700, lineHeight: 1, letterSpacing: "-0.02em", marginBottom: 2,
          }}>{String(d.getDate()).padStart(2,"0")}</span>
          <span>{weekday} · {d.getMonth()+1}월</span>
          <div className="ib-faint" style={{ fontSize: 10, marginTop: 6 }}>{brief.date}</div>
        </div>
        <div>
          <h2 className="ib-serif" style={{ margin: "0 0 8px", fontSize: 26, fontWeight: 700, letterSpacing: "-0.01em", lineHeight: 1.2 }}>
            {extractHeadline(brief.news_summary)}
          </h2>
        </div>
      </div>
      <NewsSection summary={brief.news_summary} newsRaw={brief.news_raw} />
      <div className="grid gap-3.5" style={{ gridTemplateColumns: "7fr 5fr" }}>
        <DisclosureList disclosures={brief.disclosures} />
        <div className="space-y-3.5">
          <MarketOverview global_market={brief.global_market} domestic_market={brief.domestic_market} />
          <WatchlistCheck items={brief.watchlist_check as any} />
        </div>
      </div>
    </div>
  );
}
