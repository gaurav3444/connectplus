import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// Inter to match the CW2 hi-fi mockup. Vietnamese subset included; 中文 falls
// through to the CJK system faces listed in globals.css.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin", "vietnamese"],
});

export const metadata: Metadata = {
  title: "CONNECT Plus",
  description: "Trusted help with everyday digital tasks, in your language.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
