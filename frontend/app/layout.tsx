import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VibeChat · 从被理解开始",
  description: "AI 驱动的匿名情绪社交空间",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

