"use client";

import { useEffect, useState } from "react";
import { portaleComune, type PortaleComune } from "@/lib/api";

/** Il ponte da una risposta comunale al censimento nazionale (D-44): una
 * riga sola sotto la risposta, mai una scheda a sé. I numeri vengono dal
 * censimento — mai ricalcolati qui — e se quel comune non è mai stato
 * spazzolato l'endpoint torna `null`: il componente resta muto, perché la
 * tesi del prodotto è non affermare quello che non abbiamo misurato. */
export default function PonteScala({
  istat,
  nome,
}: {
  istat: string;
  nome: string;
}) {
  const [portale, setPortale] = useState<PortaleComune | null>(null);

  useEffect(() => {
    let vivo = true;
    setPortale(null);
    portaleComune(istat)
      .then((esito) => {
        if (vivo) setPortale(esito);
      })
      .catch(() => {
        if (vivo) setPortale(null);
      });
    return () => {
      vivo = false;
    };
  }, [istat]);

  if (!portale) return null;

  const aderenzaPct =
    portale.aderenza != null ? Math.round(portale.aderenza * 100) : null;

  return (
    <p className="chiedi-inline">
      Il Comune di {nome} usa {portale.piattaforma}
      {aderenzaPct != null ? ` (aderenza ${aderenzaPct}%)` : ""} —{" "}
      <a href="/analytics">vedi com&rsquo;è messa l&rsquo;Italia →</a>
    </p>
  );
}
