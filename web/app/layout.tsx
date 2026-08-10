import type { Metadata } from "next";
import localFont from "next/font/local";
import Link from "next/link";
import { LogoEsteso } from "@/components/Logo";
import StatusPill from "@/components/StatusPill";
import FeedbackHeader from "@/components/FeedbackHeader";
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
// Poppins for headings, Inter for text — the brand board's pairing. Vendored
// like everything else here rather than pulled by `next/font/google`, which
// downloads at build time and would make `docker compose build` depend on
// reaching fonts.googleapis.com. The project claims it runs with no network
// access; self-hosting is what makes that claim true. Latin subsets only,
// 56 KB for the three files. Both families are SIL OFL 1.1.
const display = localFont({
  src: [{ path: "./fonts/Poppins-SemiBold.woff2", weight: "600", style: "normal" }],
  variable: "--font-zen-maru",
  display: "swap",
});
const body = localFont({
  src: [
    { path: "./fonts/Inter-Regular.woff2", weight: "400", style: "normal" },
    { path: "./fonts/Inter-Medium.woff2", weight: "500", style: "normal" },
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
  title: "TreasureIQ — chatta con i tuoi dati",
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
        <header className="masthead">
          <div className="masthead__inner">
            <Link href="/" className="wordmark">
              <LogoEsteso conPayoff />
            </Link>
            {/* The wordmark sits outside the nav: it is the home link, not a
                nav item, and keeping it separate lets the links become their
                own scrollable row on narrow screens instead of wrapping the
                whole masthead onto three lines. */}
            <nav className="nav" aria-label="Principale">
              <Link href="/dati">Qualità dei dati</Link>
              <Link href="/monitoraggio">Monitoraggio</Link>
              <Link href="/analytics">Analytics</Link>
              <Link href="/connectors">Connettori</Link>
              <Link href="/manifesto">Manifesto</Link>
              <Link href="/info">Come funziona</Link>
            </nav>
            <div className="masthead__right">
              <FeedbackHeader />
              <StatusPill />
            </div>
          </div>
        </header>
        {/* No site footer. It duplicated this masthead's own navigation, and
            on the chat page it would have sat under the composer — two bars
            competing for the bottom edge the conversation needs. Licence,
            provenance and the rest live on /info. */}
        <main id="main">
          <div className="shell">{children}</div>
        </main>
      </body>
    </html>
  );
}
