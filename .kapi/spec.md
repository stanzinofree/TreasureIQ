# SPEC — grafica-schede (ciclo 13)

```
TASK: grafica-schede
ONE-LINE: Restyle visivo completo delle schede in chat — un sistema card condiviso (token + primitive) che dà gerarchia e appeal senza toccare contenuto/dati né tradire le convenzioni oneste. Video-ready.
```

## PROBLEM (reale, non dichiarato)
Le schede sono il volto di TIQ nel video: è ciò che si vede di più nel demo. Il contenuto è ottimo (gerarchia informativa giusta, niente campi vuoti, provenienza esplicita), ma **visivamente piatte e indifferenziate**: tutto stesso peso (gap `--ma-3` uniforme, font ~0.92rem ovunque), bordi `1px solid` quasi invisibili, il segnale-verdetto è il chip più piccolo, la firma dello stile (accento sinistro, teal) è assente. Non è brutto: è senza punto d'ingresso per l'occhio. A 5 giorni dal video serve dare peso e appeal, restando nello stile «civico giapponese».

## SCOPE (in)
- **Sistema card condiviso**: nuovi token di *struttura* card (accento, elevazione, banda-stato, ritmo tipografico, peso CTA) sopra la palette esistente — 1 modifica token = tutte le card.
- **Restyle di TUTTE le ~12 card** `web/components/*.tsx` + CSS in `globals.css`. Priorità demo-script: `RispostaCivica`, `SchedaDettaglio` (modale), `SchedaLettoOra`, `EcoProfilo`/`ProfiloNoto`, `ChipFiltri`, `Seal`.
- **5 mosse base** (dalla review): (1) accento-sinistro su card+section-header, (2) banda-stato in cima (colore del Seal come segnale-dato), (3) elevazione reale della sotto-card servizio (staccarla dal fondo), (4) ritmo tipografico (sintesi più grande/pesante, micro-label mono davvero piccole → contrasto di scala), (5) CTA con più presenza.
- **Micro-motion CSS** su apertura scheda/hover, dentro `prefers-reduced-motion: reduce`.
- **A11y masthead**: chiudere le 2 violazioni WCAG aperte — contrasto `marchio__iq` (`globals.css:3760`) e mismatch aria-label wordmark (`layout.tsx:65`).

## CONSTRAINTS
- Stack: Next 15.5.4 / React 19.1.1. **Nessuna dipendenza nuova** (no framer-motion, no gsap) → motion solo CSS.
- Stile bespoke «civico giapponese»: **nessun font nuovo, nessun registro nuovo**, nessuna palette nuova. Costruire sui token esistenti (`--paper*`, `--sumi*`, `--ai*`, `--ai-vivid`, `--verde/--ambra`, `--ma-*`, `--radius`).
- **Contrasto WCAG AA tenuto** ovunque. `--ai-vivid` resta fill-only (navy-sopra, 8.89:1); ogni nuovo uso accento verificato.
- Tema unico light (no dark mode): nessun blocco dark da gestire.
- **Solo visivo**: contenuto, dati, testi e logica invariati. Restyle CSS/markup, non ridisegno di *cosa* mostra la card.
- Frontend only. Mai commit su main diretto (branch + PR).

## DECISIONS
- **D-01** Impianto = sistema condiviso (token + primitive card), non ritocco per-card. Coerenza forte, manutenibile; token-first per non far esplodere i tempi.
- **D-02** Evoluzione dello stile esistente, non rifacimento audace. Le 5 mosse sono il linguaggio; niente illustrazione/segni civici nuovi in questo ciclo.
- **D-03** Il **verdetto resta segnale-dato, mai giudizio TIQ**. La banda-stato colora «cosa risulta dalla fonte»; il copy «l'ultima parola è dell'ente» resta e il peso visivo non deve suggerire che TIQ decida. (Vincolo da scelte-fondanti.)
- **D-04** Peso visivo **non smorza i segnali onesti**: «non pubblicato», provenienza, «letto ora», stati vuoti restano leggibili quanto o più di ora.
- **D-05** Motion = CSS micro-transizioni (150–300ms), sempre gated `prefers-reduced-motion`. Nessuna animazione decorativa fine-a-sé.
- **D-06** A11y masthead dentro questo ciclo. Contrasto `marchio__iq`: se serve scelta di brand → segnalare NEEDS HUMAN, non forzare un colore fuori palette.

## DISCRETION (l'esecutore decide)
- Valori esatti di elevazione/ombra, spessore accento, scala tipografica precisa.
- Se estrarre un componente `Card` primitivo React o solo classi CSS condivise.
- Ordine di applicazione tra le card non-demo (best-effort).

## DEFERRED (fuori da questo ciclo)
- Ridisegno di *cosa* mostrano le card (contenuto/struttura informativa).
- Illustrazione, iconografia civica custom, motion coreografato.
- Dark mode.
- I follow-up aperti ciclo 12 (R-05 field-overload, reset override frontend) — non-grafica.

## RISKS
- **R-01** Verdetto colorato letto come «TIQ decide» → viola scelte-fondanti. Mitig: D-03, il colore è stato-dato + copy ente intatto. Reviewer verifica il framing.
- **R-02** Slittamento tempi (12 card + a11y a 5gg dal video). Mitig: demo-script = must-have, resto best-effort; token-first.
- **R-03** Regressione contrasto introdotta dal restyle. Mitig: acceptance include ri-scan a11y su localhost:3000.
- **R-04** Peso visivo seppellisce segnali onesti (provenienza/non-pubblicato/vuoti). Mitig: D-04, reviewer lo asserisce.
- **R-05** Motion jank / no reduced-motion. Mitig: D-05, gate `prefers-reduced-motion`.

## ACCEPTANCE (D-06 ciclo 12 style = barra video)
1. Le card del demo-script leggono con gerarchia chiara a video (punto d'ingresso visivo, verdetto evidente, CTA con peso).
2. Un solo cambio di token di sistema si propaga a tutte le card (D-01 verificato).
3. **Contrasto WCAG AA** su tutte le card + masthead: ri-scan accesslint su `http://localhost:3000/` senza nuove violazioni serious; le 2 aperte chiuse (o `marchio__iq` marcata NEEDS HUMAN con motivazione).
4. `tsc --noEmit` verde. Nessuna regressione sulle convenzioni oneste (stati vuoti, «letto ora», provenienza, «l'ultima parola è dell'ente» presenti e leggibili).
5. Motion rispetta `prefers-reduced-motion`.
```
```
