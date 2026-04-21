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
  const [sel, setSel] = useState(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  async function load() {
    const data = await fetchWatchlist();
    setItems(data); setLoading(false);
  }
  useEffect(() => { load(); }, []);

  function handleQueryChange(v: string) {
    setQuery(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!v.trim()) { setResults([]); return; }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      setResults(await searchStocks(v.trim()));
      setSearching(false);
    }, 300);
  }

  async function handleAdd(stock: SearchResult) {
    setError("");
    try {
      await addWatchlist(stock.stock_code, stock.stock_name, memo.trim() || undefined);
      setQuery(""); setResults([]); setMemo(""); load();
    } catch (e) { setError(e instanceof Error ? e.message : "추가 실패"); }
  }
  async function handleRemove(code: string) {
    await removeWatchlist(code); load();
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.key === "j" || e.key === "ArrowDown") setSel((s) => Math.min(items.length - 1, s + 1));
      else if (e.key === "k" || e.key === "ArrowUp") setSel((s) => Math.max(0, s - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items.length]);

  if (loading) return <div className="py-32 text-center ib-faint ib-mono text-sm">LOADING...</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-4">
        <h1 className="ib-serif" style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-0.015em", margin: 0 }}>
          관심종목
        </h1>
        <div className="ib-label">{items.length} 종목</div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3">
        <StatTile k="총 종목" v={String(items.length)} d="MAX 50" />
        <StatTile k="메모 있음" v={String(items.filter(i => i.memo).length)} d="MEMO" />
        <StatTile k="오늘 추가" v={String(items.filter(i => {
          const d = new Date(i.created_at);
          const today = new Date();
          return d.toDateString() === today.toDateString();
        }).length)} d="TODAY" tone="info" />
        <StatTile k="상태" v="LIVE" d="SYNCED" tone="up" />
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap" style={{
        padding: "12px 14px", background: "var(--ib-bg-sunk)", border: "1px solid var(--ib-line)", borderBottom: 0,
      }}>
        <div className="relative flex-1 min-w-[320px]">
          <div className="ib-input flex items-center gap-2">
            <span className="ib-faint">⌕</span>
            <input
              value={query}
              onChange={(e) => handleQueryChange(e.target.value)}
              placeholder="종목명 · 종목코드 검색 (예: 삼성전자 · 005930)"
              className="flex-1 outline-none bg-transparent ib-mono"
              style={{ fontSize: 12, color: "var(--ib-ink)" }}
            />
            {searching && <span className="ib-faint ib-mono" style={{ fontSize: 10 }}>...</span>}
          </div>
          {results.length > 0 && (
            <div className="absolute z-20 left-0 right-0 top-full mt-1 ib-card max-h-60 overflow-y-auto">
              {results.map((s) => {
                const added = items.some((w) => w.stock_code === s.stock_code);
                return (
                  <button
                    key={s.stock_code}
                    onClick={() => !added && handleAdd(s)}
                    disabled={added}
                    className="w-full text-left flex justify-between items-center px-3 py-2"
                    style={{
                      borderBottom: "1px solid var(--ib-line-soft)",
                      color: added ? "var(--ib-ink-faint)" : "var(--ib-ink)",
                      cursor: added ? "default" : "pointer",
                      fontSize: 12,
                    }}
                  >
                    <span>
                      <span style={{ fontWeight: 600 }}>{s.stock_name}</span>
                      <span className="ib-mono ib-faint ml-2" style={{ fontSize: 10 }}>{s.stock_code}</span>
                    </span>
                    <span className="ib-mono ib-faint" style={{ fontSize: 10 }}>{added ? "등록됨" : s.market}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <input
          value={memo} onChange={(e) => setMemo(e.target.value)}
          placeholder="메모 (선택)" className="ib-input w-40"
        />
        <button className="ib-btn ib-btn--primary">+ 추가</button>
        {error && <p className="ib-dn ib-mono w-full" style={{ fontSize: 11 }}>{error}</p>}
      </div>

      {/* Table */}
      {items.length === 0 ? (
        <div className="py-16 text-center ib-faint text-sm" style={{ border: "1px solid var(--ib-line)", background: "var(--ib-bg-elev)" }}>
          종목을 검색하여 관심종목을 추가하세요
        </div>
      ) : (
        <div style={{ border: "1px solid var(--ib-line)", background: "var(--ib-bg-elev)", overflow: "auto" }}>
          <table className="w-full" style={{ fontFamily: "var(--ib-mono)", fontSize: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--ib-bg-sunk)", color: "var(--ib-ink-faint)", borderBottom: "1px solid var(--ib-line)" }}>
                {["#","종목","코드","메모","등록일",""].map((h, i) => (
                  <th key={i} className="text-left px-3 py-2.5" style={{
                    fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", fontWeight: 500, whiteSpace: "nowrap",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => {
                const isSel = i === sel;
                const d = new Date(it.created_at);
                return (
                  <tr key={it.id}
                    onClick={() => setSel(i)}
                    style={{
                      borderBottom: "1px solid var(--ib-line-soft)",
                      background: isSel ? "color-mix(in oklch, var(--ib-warn) 14%, var(--ib-bg-elev))" : undefined,
                      cursor: "pointer",
                    }}>
                    <td className="ib-faint px-3 py-2.5" style={{ width: 32 }}>{String(i+1).padStart(2,"0")}</td>
                    <td className="px-3 py-2.5" style={{ fontFamily: "var(--ib-sans)", fontSize: 13, color: "var(--ib-ink)" }}>
                      {it.stock_name}
                    </td>
                    <td className="ib-faint px-3 py-2.5">{it.stock_code}</td>
                    <td className="ib-dim px-3 py-2.5 ib-serif" style={{ fontStyle: "italic", fontFamily: "var(--ib-serif)" }}>
                      {it.memo || "—"}
                    </td>
                    <td className="ib-faint px-3 py-2.5">
                      {String(d.getMonth()+1).padStart(2,"0")}/{String(d.getDate()).padStart(2,"0")}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleRemove(it.stock_code); }}
                        className="ib-mono"
                        style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--ib-ink-faint)" }}
                      >
                        DEL
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Keyboard footer */}
      <div className="flex gap-5" style={{
        padding: "10px 14px", border: "1px solid var(--ib-line)", background: "var(--ib-bg-sunk)",
        fontFamily: "var(--ib-mono)", fontSize: 10, color: "var(--ib-ink-faint)", letterSpacing: "0.1em",
      }}>
        <span><Kbd>J</Kbd>/<Kbd>K</Kbd> 아래/위</span>
        <span><Kbd>/</Kbd> 검색</span>
        <span><Kbd>1</Kbd>/<Kbd>2</Kbd>/<Kbd>3</Kbd> 페이지</span>
        <span><Kbd>T</Kbd> 테마</span>
      </div>
    </div>
  );
}

function StatTile({ k, v, d, tone }: { k: string; v: string; d: string; tone?: "up"|"info"|"warn" }) {
  const c = tone === "up" ? "var(--ib-up)" : tone === "info" ? "var(--ib-info)" : tone === "warn" ? "var(--ib-warn)" : "var(--ib-ink)";
  return (
    <div style={{ padding: 14, border: "1px solid var(--ib-line)", background: "var(--ib-bg-elev)" }}>
      <div className="ib-label" style={{ color: "var(--ib-ink-dim)" }}>{k}</div>
      <div className="ib-num" style={{ fontSize: 28, fontWeight: 600, marginTop: 6, letterSpacing: "-0.02em", color: c }}>{v}</div>
      <div className="ib-mono" style={{ fontSize: 10, letterSpacing: "0.08em", marginTop: 2, color: "var(--ib-ink-dim)", opacity: 0.75 }}>{d}</div>
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd style={{
      display: "inline-block", padding: "1px 6px", border: "1px solid var(--ib-line)",
      background: "var(--ib-bg-elev)", color: "var(--ib-ink)", fontFamily: "var(--ib-mono)", fontSize: 10, marginRight: 6,
    }}>{children}</kbd>
  );
}
