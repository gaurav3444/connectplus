import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { cookies } from "next/headers";
import "./globals.css";
import { HTML_LANG } from "./i18n";
import Offline from "./offline";

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

// Base is 20px (globals.css); these are the two steps up.
const SIZES: Record<string, string> = { lg: "25px", xl: "30px" };

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // The A+ control and Settings write these cookies. Everything is sized in rem
  // off the root, so one font-size here scales the whole app — no
  // per-component variants. Contrast swaps the colour tokens in globals.css.
  const jar = await cookies();
  const size = SIZES[jar.get("text-size")?.value ?? ""];
  const high = jar.get("contrast")?.value === "high";
  const light = jar.get("theme")?.value === "light";
  // the chosen language, so screen readers switch voice and CJK text gets
  // CJK line breaking
  const lang = HTML_LANG[jar.get("lang")?.value ?? ""] ?? "en";

  return (
    <html
      lang={lang}
      className={`${inter.variable} h-full antialiased`}
      style={size ? { fontSize: size } : undefined}
      data-contrast={high ? "high" : undefined}
      data-theme={light ? "light" : undefined}
    >
      <body className="min-h-full">
        {children}
        <Offline />
      </body>
    </html>
  );
}
