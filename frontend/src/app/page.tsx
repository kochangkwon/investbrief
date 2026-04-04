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
    setGenerating(true);
    setError("");
    try {
      const result = await generateBrief();
      setBrief(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "브리프 생성 실패");
    } finally {
      setGenerating(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <div className="animate-pulse text-gray-400 text-sm">로딩 중...</div>
      </div>
    );
  }

  if (!brief) {
    return (
      <div className="flex flex-col items-center justify-center py-32">
        <div className="text-4xl mb-4">☀️</div>
        <p className="text-gray-500 mb-5 text-sm">오늘의 브리프가 아직 없습니다</p>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="bg-gray-900 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-800 disabled:opacity-40 transition-all"
        >
          {generating ? (
            <span className="flex items-center gap-2">
              <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              생성 중... (약 30초)
            </span>
          ) : (
            "브리프 생성하기"
          )}
        </button>
        {error && <p className="text-rose-500 text-xs mt-3">{error}</p>}
      </div>
    );
  }

  async function handleRegenerate() {
    if (!confirm("오늘의 브리프를 새로 생성합니다. 계속할까요?")) return;
    setGenerating(true);
    setError("");
    try {
      const result = await generateBrief();
      setBrief(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "브리프 재생성 실패");
    } finally {
      setGenerating(false);
    }
  }

  const today = new Date(brief.date + "T00:00:00");
  const dayNames = ["일", "월", "화", "수", "목", "금", "토"];
  const dateStr = `${today.getFullYear()}. ${today.getMonth() + 1}. ${today.getDate()}. (${dayNames[today.getDay()]})`;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-gray-800">오늘의 투자 브리프</h1>
          <p className="text-xs text-gray-400 mt-0.5">{dateStr}</p>
        </div>
        <button
          onClick={handleRegenerate}
          disabled={generating}
          className="bg-gray-900 text-white px-4 py-2 rounded-lg text-xs font-medium hover:bg-gray-800 disabled:opacity-40 transition-all"
        >
          {generating ? (
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              생성 중...
            </span>
          ) : (
            "🔄 브리프 재생성"
          )}
        </button>
      </div>
      {error && <p className="text-rose-500 text-xs">{error}</p>}

      <MarketOverview global_market={brief.global_market} domestic_market={brief.domestic_market} />
      <NewsSection summary={brief.news_summary} newsRaw={brief.news_raw} />
      <DisclosureList disclosures={brief.disclosures} />
      <WatchlistCheck items={brief.watchlist_check as any} />
    </div>
  );
}
