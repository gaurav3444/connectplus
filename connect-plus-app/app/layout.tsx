import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { cookies } from "next/headers";
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

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // The A+ control writes this cookie. Everything is sized in rem off the root,
  // so one font-size here scales the whole app — no per-component variants.
  const big = (await cookies()).get("text-size")?.value === "lg";

  return (
    <html
      lang="en"
      className={`${inter.variable} h-full antialiased`}
      style={big ? { fontSize: "25px" } : undefined}
    >
      <body className="min-h-full">{children}</body>
    </html>
  );
}
