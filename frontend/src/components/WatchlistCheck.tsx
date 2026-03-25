"use client";

interface WatchlistItem {
  stock_code: string;
  stock_name: string;
  price: { close: number; change: number; change_pct: number } | null;
  news: string[];
  disclosures: { title: string; importance: string }[];
  summary: string;
}

export default function WatchlistCheck({ items }: { items: WatchlistItem[] }) {
  if (!items || items.length === 0) return null;

  return (
    <section>
      <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        🔍 관심종목 체크
      </h2>
      <div className="space-y-2">
        {items.map((item) => {
          const price = item.price;
          const isUp = price && price.change_pct > 0;
          const isDown = price && price.change_pct < 0;

          return (
            <div
              key={item.stock_code}
              className="bg-white rounded-xl border border-gray-100 shadow-sm p-4"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-sm text-gray-800">{item.stock_name}</span>
                  <span className="text-[11px] text-gray-300">{item.stock_code}</span>
                </div>
                {price && (
                  <div className="text-right">
                    <span className="font-semibold text-sm tabular-nums">
                      {price.close.toLocaleString()}원
                    </span>
                    <span
                      className={`text-xs font-medium ml-1.5 tabular-nums ${
                        isUp ? "text-rose-500" : isDown ? "text-blue-500" : "text-gray-400"
                      }`}
                    >
                      {isUp ? "▲" : isDown ? "▼" : "—"} {Math.abs(price.change_pct).toFixed(2)}%
                    </span>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                {item.news.length > 0 ? (
                  <div>
                    <span className="text-gray-400">뉴스</span>{" "}
                    {item.news.map((title, i) => (
                      <span key={i} className="text-gray-600">
                        {i > 0 && " · "}
                        {title.length > 30 ? title.slice(0, 30) + "..." : title}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-gray-300">뉴스 없음</span>
                )}
              </div>

              {item.disclosures.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {item.disclosures.map((d, i) => (
                    <span
                      key={i}
                      className="text-[11px] bg-gray-50 border border-gray-100 rounded px-1.5 py-0.5"
                    >
                      {d.importance} {d.title.length > 20 ? d.title.slice(0, 20) + "..." : d.title}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
