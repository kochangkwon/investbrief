const API_BASE = "/api";

export interface MarketItem {
  label: string;
  close: number;
  change: number;
  change_pct: number;
}

export interface Disclosure {
  corp_name: string;
  stock_code: string;
  title: string;
  importance: string;
  rcept_no: string;
  rcept_dt: string;
}

export interface SearchResult {
  stock_name: string;
  stock_code: string;
  market: string;
}

export interface DailyBrief {
  id: number;
  date: string;
  global_market: Record<string, MarketItem>;
  domestic_market: Record<string, MarketItem>;
  news_summary: string;
  news_raw: { title: string; link: string; source: string }[];
  disclosures: Disclosure[];
  watchlist_check: unknown[];
  created_at: string;
}

export interface WatchlistItem {
  id: number;
  stock_code: string;
  stock_name: string;
  memo: string | null;
  created_at: string;
}

export async function fetchTodayBrief(): Promise<DailyBrief | null> {
  const res = await fetch(`${API_BASE}/brief/today`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("브리프 조회 실패");
  return res.json();
}

export async function fetchBriefByDate(date: string): Promise<DailyBrief | null> {
  const res = await fetch(`${API_BASE}/brief/${date}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("브리프 조회 실패");
  return res.json();
}

export async function fetchBriefList(days = 7) {
  const res = await fetch(`${API_BASE}/brief/list?days=${days}`, { cache: "no-store" });
  if (!res.ok) throw new Error("브리프 목록 조회 실패");
  return res.json();
}

export async function generateBrief(): Promise<DailyBrief> {
  const res = await fetch(`${API_BASE}/brief/generate`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "브리프 생성 실패");
  }
  return res.json();
}

export async function fetchWatchlist(): Promise<WatchlistItem[]> {
  const res = await fetch(`${API_BASE}/watchlist`, { cache: "no-store" });
  if (!res.ok) throw new Error("관심종목 조회 실패");
  return res.json();
}

export async function addWatchlist(stock_code: string, stock_name: string, memo?: string) {
  const res = await fetch(`${API_BASE}/watchlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stock_code, stock_name, memo }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "관심종목 추가 실패");
  }
  return res.json();
}

export async function removeWatchlist(stock_code: string) {
  const res = await fetch(`${API_BASE}/watchlist/${stock_code}`, { method: "DELETE" });
  if (!res.ok) throw new Error("관심종목 삭제 실패");
  return res.json();
}

export async function searchStocks(query: string): Promise<SearchResult[]> {
  const res = await fetch(`${API_BASE}/watchlist/search?q=${encodeURIComponent(query)}`);
  if (!res.ok) return [];
  return res.json();
}
