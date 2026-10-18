---
colors:
  canvas: "#FFFFFF"
  canvas-dark: "#0C0320"
  surface-dark: "#170834"
  ink: "#12082B"
  ink-dark: "#F7F1FF"
  muted: "#4A3F6B"
  link: "#6A12FF"
  link-dark: "#00E5FF"
  fluo-pink: "#FF2BD6"
  fluo-lime: "#C6FF00"
  fluo-cyan: "#00E5FF"
  fluo-yellow: "#FFF200"
  fluo-orange: "#FF7A00"
  fluo-violet: "#7B2BFF"
  evidence: "#A87500"
typography:
  display: "Poppins SemiBold"
  body: "Inter"
  mono: "DM Mono"
  scale: ["12px", "14px", "16px", "20px", "28px"]
radius: ["8px", "14px", "22px"]
spacing: ["4px", "8px", "12px", "16px", "24px", "32px"]
themes: ["light (default)", "dark (toggle, persisted in localStorage tiq-theme)"]
---

# TreasureIQ — chat pop anni '80, acida e fluo, con evidenze esplorabili

## 1. Tema e atmosfera

Un assistente virtuale pop anni '80: bianco ottico, colori fluo acidi, bordi
neri spessi e ombre a offset stile Memphis. Il tema scuro è la versione
notturna (viola-nero, neon ciano e fucsia), sempre brillante. Lo sfondo è
vivo (blob fluo che derivano e una griglia synthwave sul fondo) per dare
l'effetto "macchina che pensa", ma il testo poggia sempre su una superficie
piena: nessun contenuto sta direttamente sul gradiente.

## 2. Palette e ruoli

- `canvas` bianco ottico / `canvas-dark` viola-nero; `ink` resta il colore di
  lettura (AA su entrambi i temi).
- `fluo-lime` è la CTA e la bolla dell'utente (testo sempre `ink` scuro, anche
  nel dark). `fluo-pink` e `fluo-cyan` sono ombre offset, focus e glow.
- `link` viola elettrico (6,9:1 su bianco) / `link-dark` ciano.
- Giallo, arancio e violetto fluo sono solo decorazione (arcobaleno della
  testata, alone di TIQ, chip): mai testo, mai verdetto.
- I colori semantici di stato (ok/parziale/manca/ignoto, barra sinistra della
  bolla) non cambiano significato con il tema.

## 3. Tipografia

Testo di risposta a 16px; metadati, fonti e timestamp a 12–14px. Il
monospazio è riservato a etichette tecniche brevi, non al contenuto civico.

## 4. Componenti e stati

- Ogni risposta ha al massimo una sintesi, una riga di evidenza e un'azione
  contestuale `⋯` accessibile con etichetta testuale per screen reader.
- `⋯` apre azioni secondarie: fonte, dati del comune, copia link e stato di
  aggiornamento; il menu non contiene la risposta principale.
- I dati pertinenti (bandi, servizi, contatti) si aprono sotto la risposta in
  un disclosure: titolo, numero di elementi, provenienza e ultimo rilevamento.
- Un risultato vuoto è esplicito solo quando è misurato; non può coesistere
  con elementi dello stesso tipo mostrati nella stessa risposta.
- Link esterni dichiarano il portale di destinazione e aprono in nuova scheda.
- Ogni controllo è raggiungibile da tastiera, ha focus visibile e stato
  `aria-expanded`/`aria-controls` quando espande contenuto.
- TIQ è un capibara con cuffie e tuta "TIQ". Sorgente:
  `web/design-src/sprite_tiq.png` (griglia 6×4 di espressioni, celle 256px,
  scacchiera dipinta). Asset servito: `web/public/tiq-sprite.webp` con alpha
  vera, rigenerato da `python3 web/scripts/sprite_cutout.py`.
- `TiqPersona` ha un `mood`: `idle` (saluto/occhiolino), `working` (?,
  mento, lente, laptop: in attesa di risposta), `found`, `empty`, `error`,
  `talk`. Animato = pose che cambiano con pop-in + respiro + alone conico che
  ruota. Le pose sono decorative (`aria-hidden`) e non dichiarano capacità
  che il prodotto non ha: nessun testo dice "AI".

## 5. Layout

La colonna della chat è la superficie dominante. Il pannello laterale diventa
un riepilogo comprimibile del Comune scelto, non il solo ingresso ai dati.
Su mobile il riepilogo si sposta dietro un'azione nella testata della chat.

## 6. Profondità ed elevazione

Profondità pop: bordo 2,5px, ombra piena a offset (fucsia per la testata di
TIQ, ciano per le risposte, inchiostro per CTA e bolla utente). Nel dark il
bordo diventa ciano e si aggiunge un glow neon. Niente vetro, niente ombre
sfumate grigie.

## 7. Do e don't

**Fare:** mostrare prima cosa sappiamo, poi da dove proviene, poi l'azione per
esplorare; mantenere aperto il contesto della domanda; indicare data e limite
di ogni snapshot.

**Non fare:** mescolare risultati web non verificati e dati ingeriti sotto lo
stesso verdetto; nascondere un dato disponibile dietro un gate tecnico;
duplicare la stessa lista in ogni messaggio dello storico; usare il menu `⋯`
per azioni principali.

## 8. Responsive

Sotto 900px la chat occupa l'intera larghezza. I disclosure restano nel flusso
del messaggio; il menu non esce dal viewport. Nessuna informazione richiede
hover e il movimento rispetta `prefers-reduced-motion`.

## 9. Guida per agenti

Ogni modifica UI deve favorire una conversazione leggibile e rendere l'origine
del dato controllabile. Riusa i componenti e i token esistenti quando possibile;
aggiungi un nuovo elemento solo se rende più breve il percorso chat → evidenza
→ fonte.
