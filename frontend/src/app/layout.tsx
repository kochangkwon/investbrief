import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "InvestBrief — AI 투자 모닝브리프",
  description: "매일 아침 AI가 정리하는 투자 브리프",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="bg-[#f8f9fb] text-gray-900 min-h-screen antialiased">
        <header className="bg-white border-b border-gray-100 sticky top-0 z-10 shadow-sm">
          <nav className="max-w-3xl mx-auto px-4 h-12 flex items-center justify-between">
            <a href="/" className="font-bold text-base tracking-tight text-gray-800">
              ☀️ InvestBrief
            </a>
            <div className="flex gap-4">
              <a href="/" className="text-sm text-gray-500 hover:text-gray-900 transition-colors">
                오늘
              </a>
              <a href="/archive" className="text-sm text-gray-500 hover:text-gray-900 transition-colors">
                아카이브
              </a>
              <a href="/watchlist" className="text-sm text-gray-500 hover:text-gray-900 transition-colors">
                관심종목
              </a>
            </div>
          </nav>
        </header>
        <main className="max-w-3xl mx-auto px-4 py-5">{children}</main>
      </body>
    </html>
  );
}
