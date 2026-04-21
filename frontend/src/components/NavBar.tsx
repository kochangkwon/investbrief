"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

function useKstClock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000 * 30);
    return () => clearInterval(id);
  }, []);
  return now;
}

function formatKst(d: Date) {
  // KST 고정 표시 — 서버/클라 타임존 차이 무시하고 Asia/Seoul로 포맷
  const fmt = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    weekday: "short",
  });
  const parts = Object.fromEntries(fmt.formatToParts(d).map((p) => [p.type, p.value]));
  return {
    date: `${parts.year}.${parts.month}.${parts.day}`,
    weekday: parts.weekday,
    time: `${parts.hour}:${parts.minute}`,
  };
}

export default function NavBar() {
  const pathname = usePathname() || "/";
  const now = useKstClock();
  const tabs = [
    { href: "/", label: "오늘의 브리프", kbd: "1" },
    { href: "/archive", label: "아카이브", kbd: "2" },
    { href: "/watchlist", label: "관심종목", kbd: "3" },
  ];
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <header className="ib-nav">
      <div className="logo">
        INVESTBRIEF<span className="dot">.</span>
      </div>
      <nav className="flex gap-0.5 flex-1">
        {tabs.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className={`ib-nav-tab${isActive(t.href) ? " on" : ""}`}
          >
            {t.label}
            <span
              className="ml-1"
              style={{ color: "var(--ib-ink-faint)", fontSize: 9, letterSpacing: "0.1em" }}
            >
              {t.kbd}
            </span>
          </Link>
        ))}
      </nav>

      {/* 실시간 KST 시계 */}
      <div
        className="ib-mono"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 11,
          letterSpacing: "0.08em",
          color: "var(--ib-ink-dim)",
          whiteSpace: "nowrap",
        }}
        suppressHydrationWarning
      >
        {now ? (
          <>
            <span style={{ color: "var(--ib-ink)" }}>
              {formatKst(now).date}
              <span className="ib-faint" style={{ marginLeft: 6 }}>{formatKst(now).weekday}</span>
            </span>
            <span
              aria-hidden
              style={{
                display: "inline-block",
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: "var(--ib-up)",
                boxShadow: "0 0 0 3px color-mix(in oklch, var(--ib-up) 25%, transparent)",
              }}
            />
            <span>
              {formatKst(now).time}
              <span className="ib-faint" style={{ marginLeft: 4 }}>KST</span>
            </span>
          </>
        ) : (
          <span style={{ opacity: 0.5 }}>— —</span>
        )}
      </div>

      <button
        id="ib-theme-btn"
        aria-label="테마 전환"
        className="w-[30px] h-[30px] inline-flex items-center justify-center"
        style={{ border: "1px solid var(--ib-line)", color: "var(--ib-ink-dim)", marginLeft: 14 }}
        suppressHydrationWarning
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
        </svg>
      </button>
    </header>
  );
}
