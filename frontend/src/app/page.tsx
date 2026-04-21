"use client";

import { useEffect, useState } from "react";
import type { DailyBrief } from "@/lib/api";
import { fetchTodayBrief, generateBrief } from "@/lib/api";
import MarketOverview from "@/components/MarketOverview";
import NewsSection from "@/components/NewsSection";
import DisclosureList from "@/components/DisclosureList";
import WatchlistCheck from "@/components/WatchlistCheck";

export default function HomePage() {
  const [brief, setBrief] = useState<DailyBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchTodayBrief()
      .then((data) => setBrief(data))
      .catch(() => setError("브리프 조회 실패"))
      .finally(() => setLoading(false));
  }, []);

  async function handleGenerate() {
    setGenerating(true); setError("");
    try { setBrief(await generateBrief()); }
    catch (e) { setError(e instanceof Error ? e.message : "브리프 생성 실패"); }
    finally { setGenerating(false); }
  }

  if (loading) return <div className="py-32 text-center ib-faint ib-mono text-sm">LOADING...</div>;

  if (!brief) {
    return (
      <div className="flex flex-col items-center justify-center py-32 gap-4">
        <div className="ib-label">NO BRIEF TODAY</div>
        <p className="ib-dim text-sm">오늘의 브리프가 아직 없습니다</p>
        <button onClick={handleGenerate} disabled={generating} className="ib-btn ib-btn--primary">
          {generating ? "GENERATING... (~30s)" : "▶ 브리프 생성"}
        </button>
        {error && <p className="ib-dn text-xs ib-mono">{error}</p>}
      </div>
    );
  }

  async function handleRegenerate() {
    if (!confirm("오늘의 브리프를 새로 생성합니다. 계속할까요?")) return;
    setGenerating(true); setError("");
    try { setBrief(await generateBrief()); }
    catch (e) { setError(e instanceof Error ? e.message : "재생성 실패"); }
    finally { setGenerating(false); }
  }

  const today = new Date(brief.date + "T00:00:00");
  const dayNames = ["일","월","화","수","목","금","토"];
  const dateStr = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,"0")}-${String(today.getDate()).padStart(2,"0")} ${dayNames[today.getDay()]}`;

  return (
    <div className="space-y-4">
      {/* Head */}
      <div className="flex items-baseline gap-4">
        <h1 className="ib-serif" style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-0.015em", margin: 0 }}>
          오늘의 브리프
        </h1>
        <div className="ib-mono ib-dim" style={{ fontSize: 11, letterSpacing: "0.08em" }}>
          {dateStr}
        </div>
        <div className="ml-auto flex gap-2 items-center">
          <button onClick={handleRegenerate} disabled={generating} className="ib-btn">
            {generating ? "GEN..." : "↻ REGEN"}
          </button>
        </div>
      </div>
      {error && <p className="ib-dn ib-mono" style={{ fontSize: 11 }}>{error}</p>}

      <div className="grid gap-3.5" style={{ gridTemplateColumns: "7fr 5fr" }}>
        <div className="space-y-3.5 min-w-0">
          <NewsSection summary={brief.news_summary} newsRaw={brief.news_raw} />
          <DisclosureList disclosures={brief.disclosures} />
        </div>
        <div className="space-y-3.5 min-w-0">
          <MarketOverview global_market={brief.global_market} domestic_market={brief.domestic_market} />
          <WatchlistCheck items={brief.watchlist_check as any} />
        </div>
      </div>
    </div>
  );
}
