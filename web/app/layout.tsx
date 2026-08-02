import type { Metadata } from "next";
import localFont from "next/font/local";
import Link from "next/link";
import { Wordmark } from "@/components/Seal";
import "./globals.css";

// Fonts are vendored under app/fonts/ rather than pulled with next/font/google.
// The Google loader downloads at build time, which would make `docker compose
// build` depend on reaching fonts.googleapis.com — and this project claims it
// runs with no network access. Self-hosting makes that claim true, and the
// latin subsets cost 84 KB in total. All three families are SIL OFL 1.1; see
// app/fonts/README.md.

// Zen Maru Gothic is a *rounded* Japanese gothic — the warmth of the interface
// lives in the letterforms themselves rather than in illustration, which keeps
// the page friendly without undercutting the seriousness of what it reports.
const display = localFont({
  src: [
    { path: "./fonts/ZenMaruGothic-Medium.woff2", weight: "500", style: "normal" },
    { path: "./fonts/ZenMaruGothic-Bold.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-zen-maru",
  display: "swap",
});
const body = localFont({
  src: [
    { path: "./fonts/ZenKakuGothicNew-Regular.woff2", weight: "400", style: "normal" },
    { path: "./fonts/ZenKakuGothicNew-Medium.woff2", weight: "500", style: "normal" },
    { path: "./fonts/ZenKakuGothicNew-Bold.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-zen-kaku",
  display: "swap",
});
const mono = localFont({
  src: [
    { path: "./fonts/DMMono-Regular.woff2", weight: "400", style: "normal" },
    { path: "./fonts/DMMono-Medium.woff2", weight: "500", style: "normal" },
  ],
  variable: "--font-dm-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "TreasureIQ — le opportunità del tuo comune",
  description:
    "Incrocia gli open data della PA con il tuo profilo e ti dice a quali agevolazioni hai davvero accesso.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="it" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>
        <a className="skip-link" href="#main">
          Vai al contenuto
        </a>
        <div className="shell">
          <header className="masthead">
            <Link href="/" className="wordmark">
              <Wordmark />
              TreasureIQ
            </Link>
            <nav className="nav" aria-label="Principale">
              <Link href="/opportunita">Opportunità</Link>
              <Link href="/dati">Qualità dei dati</Link>
            </nav>
          </header>
          <main id="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
