/**
 * Site-wide footer — deliberately short.
 *
 * The chat is the product, and a tall footer competes with it for the bottom
 * of every screen. So this is one row of links and one line of provenance:
 * the service's vital signs moved to /monitoraggio, which is where a reader
 * who actually wants numbers is already heading, and the two link columns
 * collapsed into a single inline list.
 *
 * Fully static server markup — no client island, nothing to hydrate.
 */

import Link from "next/link";

const LINKS = [
  { href: "/opportunita", label: "Le tue opportunità" },
  { href: "/dati", label: "Qualità dei dati" },
  { href: "/monitoraggio", label: "Stato sistemi" },
  { href: "/manifesto", label: "Manifesto" },
  { href: "/info", label: "Come funziona" },
];

export default function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <nav className="site-footer__links" aria-label="Collegamenti del sito">
          <Link href="/" className="wordmark">
            TreasureIQ
          </Link>
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href}>
              {l.label}
            </Link>
          ))}
        </nav>

        <p className="site-footer__legal">
          Codice Apache-2.0 ·{" "}
          <a href="https://github.com/stanzinofree/TreasureIQ" target="_blank" rel="noreferrer">
            sorgente su GitHub
          </a>{" "}
          · I dati provengono da fonti pubbliche e non sono una fonte di
          eleggibilità: l&apos;ultima parola resta al comune.
        </p>
      </div>
    </footer>
  );
}
