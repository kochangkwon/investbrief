"use client";

import { useEffect } from "react";

/**
 * 클라이언트 전용 초기화:
 *  - 저장된 테마 복원
 *  - 테마 토글 버튼 바인딩
 *  - 숫자 단축키 (1,2,3)로 페이지 전환
 *  - 현재 경로 기반 nav 활성화
 *
 * layout.tsx에서 <ClientShell /> 로 한 번만 마운트.
 */
export default function ClientShell() {
  useEffect(() => {
    const KEY = "ib_theme";
    const root = document.documentElement;
    const saved = localStorage.getItem(KEY);
    if (saved === "dark" || saved === "light") root.setAttribute("data-theme", saved);

    const toggle = () => {
      const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      localStorage.setItem(KEY, next);
    };
    const btn = document.getElementById("ib-theme-btn");
    btn?.addEventListener("click", toggle);

    // 활성 탭 — NavBar.tsx가 usePathname으로 직접 처리하므로 여기서는 안 함

    // 단축키
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.key === "1") window.location.href = "/";
      else if (e.key === "2") window.location.href = "/archive";
      else if (e.key === "3") window.location.href = "/watchlist";
      else if (e.key.toLowerCase() === "t") toggle();
    };
    window.addEventListener("keydown", onKey);

    return () => {
      btn?.removeEventListener("click", toggle);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  return null;
}
