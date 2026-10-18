---
colors:
  canvas: "#FFFEF8"
  surface: "#FFFFFF"
  ink: "#234314"
  muted: "#657460"
  accent: "#26CBB7"
  accent-strong: "#1B7D66"
  evidence: "#A87500"
  border: "#D9DED2"
  focus: "#6539A6"
typography:
  family: "system-ui, sans-serif"
  mono: "ui-monospace, SFMono-Regular, monospace"
  scale: ["12px", "14px", "16px", "20px", "28px"]
radius: ["8px", "14px", "20px"]
spacing: ["4px", "8px", "12px", "16px", "24px", "32px"]
---

# TreasureIQ — chat civica con evidenze esplorabili

## 1. Tema e atmosfera

Un prodotto personale, pop e generoso: la chat resta il luogo in cui si
capisce la risposta; dati, fonte e azioni si aprono solo quando servono.
Crema, inchiostro blu, lime e corallo richiamano l'editoria anni 70/80,
senza usare il colore per falsare lo stato di un dato.

## 2. Palette e ruoli

- `canvas` e `surface` sono crema e avorio, con bordi d'inchiostro e ombre
  nette e corte.
- `ink` è blu notte; `muted` è solo metadato.
- `accent` è lime/corallo per azioni e ritmo, mai affidabilità del dato.
- `evidence` distingue fonte, stato e avvertenze dalla risposta.
- `focus` è sempre visibile da tastiera e non coincide col colore semantico.

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

## 5. Layout

La colonna della chat è la superficie dominante. Il pannello laterale diventa
un riepilogo comprimibile del Comune scelto, non il solo ingresso ai dati.
Su mobile il riepilogo si sposta dietro un'azione nella testata della chat.

## 6. Profondità ed elevazione

Profondità grafica: bordo blu notte e ombra offset breve, mai gradienti o vetro.
Menu contestuale e disclosure usano una superficie avorio distinta, non modali.

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
