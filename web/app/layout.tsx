import type { Metadata } from "next";
import { Zen_Maru_Gothic, Zen_Kaku_Gothic_New, DM_Mono } from "next/font/google";
import Link from "next/link";
import { Wordmark } from "@/components/Seal";
import "./globals.css";

// Zen Maru Gothic is a *rounded* Japanese gothic — the warmth of the interface
// lives in the letterforms themselves rather than in illustration, which keeps
// the page friendly without undercutting the seriousness of what it reports.
const display = Zen_Maru_Gothic({
  subsets: ["latin"],
  weight: ["500", "700"],
  variable: "--font-zen-maru",
  display: "swap",
});
const body = Zen_Kaku_Gothic_New({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-zen-kaku",
  display: "swap",
});
const mono = DM_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
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
