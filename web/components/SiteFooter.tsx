/**
 * Site-wide footer (v3) — brand, link columns, live stats and the license
 * row. Rendered from the layout so every page shares one footer instead of
 * each page hand-rolling a chat-footer. `FooterStats` is a client island;
 * everything else here is static server markup.
 */

import Link from "next/link";
import FooterStats from "./FooterStats";

function Column({ title, links }: { title: string; links: { href: string; label: string }[] }) {
  return (
    <div className="site-footer__col">
      <h3>{title}</h3>
      <ul>
        {links.map((l) => (
          <li key={l.href}>
            <Link href={l.href}>{l.label}</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <div className="site-footer__top">
          <div className="site-footer__brand">
            <span className="wordmark">TreasureIQ</span>
            <p className="site-footer__tagline">
              Le opportunità del tuo comune, lette al posto tuo — solo quello
              che i dati pubblicati confermano.
            </p>
          </div>

          <Column
            title="Esplora"
            links={[
              { href: "/opportunita", label: "Le tue opportunità" },
              { href: "/dati", label: "Qualità dei dati" },
              { href: "/manifesto", label: "Manifesto" },
              { href: "/info", label: "Come funziona" },
            ]}
          />

          <Column
            title="Trasparenza"
            links={[
              { href: "/monitoraggio", label: "Stato sistemi" },
              { href: "/dati", label: "Pagella dei comuni" },
              { href: "/manifesto", label: "I dati dietro il progetto" },
            ]}
          />

          <div className="site-footer__col">
            <h3>Dati del servizio</h3>
            <FooterStats />
          </div>
        </div>

        <div className="site-footer__legal">
          <span>
            TreasureIQ · codice Apache-2.0 ·{" "}
            <a href="https://github.com/stanzinofree/TreasureIQ" target="_blank" rel="noreferrer">
              sorgente su GitHub
            </a>
          </span>
          <span>
            Contesto finanziario dei comuni:{" "}
            <a href="https://openbilanci.it" target="_blank" rel="noreferrer">
              Openbilanci
            </a>{" "}
            (Fondazione Openpolis, CC-BY-NC) da OpenBDAP (MEF). Non è una fonte
            di eleggibilità.
          </span>
        </div>
      </div>
    </footer>
  );
}
