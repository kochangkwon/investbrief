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

export default function ArchivePage() {
  const [list, setList] = useState<BriefSummary[]>([]);
  const [selected, setSelected] = useState<DailyBrief | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchBriefList(30).then(setList).finally(() => setLoading(false));
  }, []);

  async function handleSelect(date: string) {
    const brief = await fetchBriefByDate(date);
    setSelected(brief);
  }

  if (loading) {
    return <div className="flex items-center justify-center py-32 text-gray-400 text-sm animate-pulse">로딩 중...</div>;
  }

  return (
    <div className="space-y-5">
      <h1 className="text-lg font-bold text-gray-800">📅 아카이브</h1>

      {list.length === 0 ? (
        <div className="text-center py-20 text-gray-400 text-sm">저장된 브리프가 없습니다</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4">
          <div className="space-y-1.5">
            {list.map((item) => (
              <button
                key={item.id}
                onClick={() => handleSelect(item.date)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-all ${
                  selected?.date === item.date
                    ? "bg-gray-900 text-white shadow"
                    : "bg-white border border-gray-100 text-gray-700 hover:bg-gray-50 shadow-sm"
                }`}
              >
                <div className="font-medium">{item.date}</div>
                <div className={`text-xs mt-0.5 truncate ${selected?.date === item.date ? "text-gray-300" : "text-gray-400"}`}>
                  {item.news_summary}
                </div>
              </button>
            ))}
          </div>

          <div className="space-y-4">
            {selected ? (
              <>
                <MarketOverview global_market={selected.global_market} domestic_market={selected.domestic_market} />
                <NewsSection summary={selected.news_summary} newsRaw={selected.news_raw} />
                <DisclosureList disclosures={selected.disclosures} />
                <WatchlistCheck items={selected.watchlist_check as any} />
              </>
            ) : (
              <div className="flex items-center justify-center py-20 text-gray-400 text-sm">
                ← 날짜를 선택하세요
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
