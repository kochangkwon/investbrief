import type { Metadata } from "next";
import ClientShell from "@/components/ClientShell";
import NavBar from "@/components/NavBar";
import "./globals.css";

export const metadata: Metadata = {
  title: "InvestBrief — AI 투자 모닝브리프",
  description: "매일 아침 AI가 정리하는 투자 브리프",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" data-theme="light" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,500;9..144,700;9..144,800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen antialiased" style={{ background: "var(--ib-bg)", color: "var(--ib-ink)" }}>
        <div className="max-w-[1440px] mx-auto px-7 pb-20">
          <NavBar />
          <main className="pt-5">{children}</main>
        </div>
        <ClientShell />
      </body>
    </html>
  );
}
