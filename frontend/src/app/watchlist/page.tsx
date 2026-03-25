"use client";

import { useEffect, useRef, useState } from "react";
import { fetchWatchlist, addWatchlist, removeWatchlist, searchStocks } from "@/lib/api";
import type { WatchlistItem, SearchResult } from "@/lib/api";

export default function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [memo, setMemo] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  async function load() {
    const data = await fetchWatchlist();
    setItems(data);
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  function handleQueryChange(value: string) {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!value.trim()) {
      setResults([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      const res = await searchStocks(value.trim());
      setResults(res);
      setSearching(false);
    }, 300);
  }

  async function handleAdd(stock: SearchResult) {
    setError("");
    try {
      await addWatchlist(stock.stock_code, stock.stock_name, memo.trim() || undefined);
      setQuery("");
      setResults([]);
      setMemo("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "추가 실패");
    }
  }

  async function handleRemove(stock_code: string) {
    await removeWatchlist(stock_code);
    load();
  }

  if (loading) {
    return <div className="flex items-center justify-center py-32 text-gray-400 text-sm animate-pulse">로딩 중...</div>;
  }

  return (
    <div className="space-y-5">
      <h1 className="text-lg font-bold text-gray-800">🔍 관심종목</h1>

      {/* 종목 검색 */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-visible">
        <div className="p-4">
          <div className="flex gap-2 flex-col sm:flex-row">
            <div className="relative flex-1">
              <input
                value={query}
                onChange={(e) => handleQueryChange(e.target.value)}
                placeholder="종목명 또는 종목코드 검색"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-200 transition"
              />
              {searching && (
                <div className="absolute right-3 top-2.5">
                  <div className="w-3.5 h-3.5 border-2 border-gray-200 border-t-gray-500 rounded-full animate-spin" />
                </div>
              )}

              {/* 검색 결과 드롭다운 */}
              {results.length > 0 && (
                <div className="absolute z-20 left-0 right-0 top-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-y-auto">
                  {results.map((stock) => {
                    const alreadyAdded = items.some((w) => w.stock_code === stock.stock_code);
                    return (
                      <button
                        key={stock.stock_code}
                        onClick={() => !alreadyAdded && handleAdd(stock)}
                        disabled={alreadyAdded}
                        className={`w-full text-left px-3 py-2 text-sm flex justify-between items-center ${
                          alreadyAdded
                            ? "bg-gray-50 text-gray-300 cursor-default"
                            : "hover:bg-gray-50 text-gray-700"
                        }`}
                      >
                        <div>
                          <span className="font-medium">{stock.stock_name}</span>
                          <span className="text-gray-300 text-xs ml-2">{stock.stock_code}</span>
                        </div>
                        <span className="text-[10px] text-gray-300">{alreadyAdded ? "등록됨" : stock.market}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            <input
              value={memo}
              onChange={(e) => setMemo(e.target.value)}
              placeholder="메모 (선택)"
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm sm:w-40 focus:outline-none focus:ring-2 focus:ring-gray-200 transition"
            />
          </div>
          {error && <p className="text-rose-500 text-xs mt-2">{error}</p>}
        </div>
      </div>

      {/* 관심종목 목록 */}
      {items.length === 0 ? (
        <div className="text-center py-16 text-gray-400 text-sm">
          종목을 검색하여 관심종목을 추가하세요
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden divide-y divide-gray-50">
          {items.map((item) => (
            <div key={item.id} className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-2 flex-wrap min-w-0">
                <span className="font-medium text-sm text-gray-800">{item.stock_name}</span>
                <span className="text-gray-300 text-xs">{item.stock_code}</span>
                {item.memo && (
                  <span className="text-xs text-gray-400 bg-gray-50 px-2 py-0.5 rounded truncate max-w-[150px]">
                    {item.memo}
                  </span>
                )}
              </div>
              <button
                onClick={() => handleRemove(item.stock_code)}
                className="text-gray-300 hover:text-rose-500 text-xs transition-colors shrink-0 ml-2"
              >
                삭제
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
