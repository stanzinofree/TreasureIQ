# TIQ e ItaliaAperta: confronto per il lancio

Rilevazione del 3 ottobre 2026. ItaliaAperta osservata sul sito pubblico;
TIQ osservato sul runtime locale `http://localhost:3000` e nel repository.
Il confronto non certifica la copertura o l'affidabilità complessiva dei due servizi.

## Differenza che un cittadino può vedere

| Aspetto | ItaliaAperta | TIQ |
| --- | --- | --- |
| Promessa | Orientamento ai servizi pubblici, spiegazione dei passaggi e pagine ufficiali | Ricerca di servizi, uffici e bandi con riferimenti comunali e provenienza dei dati |
| Ampiezza | Dichiara 1.115 pagine di 208 enti: 518 nazionali, 312 regionali, 233 comunali, 52 europee | Riconoscimento dei comuni, con copertura effettiva variabile per fonte e funzione; riconoscimento non equivale a dati completi |
| Presentazione | Ingresso semplice, esempi concreti, chat separata, limiti espliciti | Chat direttamente nella home, scheda del comune e dati strutturati; testata iniziale troppo tecnica |
| Conversazioni | Dichiara nessun archivio delle chat; domanda e allegati inviati a Regolo | Il banner locale dichiara cookie tecnico e conversazioni sul server per 90 giorni, cancellabili |
| Operazioni | Dichiara di non prenotare e non inviare pratiche | Rimanda ai canali ufficiali; una fonte trovata non equivale a pratica completata |

## Prova comparabile effettuata

Domanda identica: «Come rinnovo la carta d'identità ad Albano Laziale?».

- **ItaliaAperta:** risposta discorsiva sui passaggi nazionali, costo di base,
  documenti e tempi; link ad Agenda CIE; invita a verificare sul sito del Comune
  il canale locale e i diritti di segreteria. Non ha mostrato nella risposta
  osservata la pagina del servizio di Albano. Non significa che non possa
  trovarla con altre domande.
- **TIQ:** scheda «Carta d'identità (CIE)», link diretto a
  `https://comune.albanolaziale.rm.it/servizio/carta-identita/`, data di lettura
  25 agosto 2026 e riferimenti del Comune nel pannello. Il link è stato
  osservato nella risposta; validità attuale e correttezza delle istruzioni
  amministrative non sono state verificate con l'ente.

È un esempio utile del valore locale di TIQ, non un benchmark di superiorità.
Il vantaggio da dimostrare nel lancio è trovare il riferimento locale giusto,
con fonte e data leggibili. Le fonti ufficiali sono una caratteristica condivisa.

## Difetti visivi iniziali e contratto del restyling

1. La hero occupa quasi tutto il primo viewport desktop; esempi e avvio della
   conversazione devono essere immediatamente raggiungibili.
2. Analytics, connettori e monitoraggio hanno lo stesso peso dell'accesso al
   servizio. Renderli secondari, mantenendo percorsi e accessibilità.
3. A 500 px il pannello resta accanto alla risposta e spezza i recapiti in
   singoli caratteri. Verificare stato iniziale e conversazione a 390, 500,
   768 e 1440 px.
4. A viewport mobile emulato di 390 px, il documento iniziale si estende a
   418 px: testata/status e banner conversazione contribuiscono all'overflow.
5. Non promettere accesso certo alle agevolazioni o copertura completa.
   Rendere riconoscibili fonte, data, dati mancanti e collegamento ufficiale.
6. Riutilizzare motore, componenti e font locali; controllare tastiera,
   focus, contrasto, navigazione e invio domanda dopo il restyling.

## Fonti del confronto

- https://www.italiaaperta.it/ — promessa, conteggi e funzioni dichiarate.
- https://www.italiaaperta.it/chat — prova della domanda sopra indicata.
- https://www.italiaaperta.it/privacy — informativa aggiornata al 30/09/2026.
- https://www.italiaaperta.it/termini — limiti e licenza dichiarati.
- TIQ: `web/app/page.tsx`, `web/app/layout.tsx`, `web/components/Chat.tsx`,
  `README.md`, runtime locale e banner conversazione.

Il lavoro grafico è locale. La disponibilità al pubblico richiede anche la
verifica del runtime da pubblicare e dell'effettiva copertura promessa.

Osservazione operativa: `/api/status` locale riporta API e motore di regole
disponibili, ingestion degradata perché datata al 05/08/2026, 733 record su
8 comuni misurati. Non è una misura della produzione né della copertura live.
Il README descrive uno snapshot più piccolo: evitare di usarlo come contatore
aggiornato per la homepage. Il restyling non risolve l'aggiornamento dei dati.

## Verifica indipendente del restyling

**CLEAR per il perimetro grafico**, candidato `9ad99cc` (include `c7f04de`),
branch locale `feat/restyling-lancio`, preview `http://localhost:3100`.
Autore: dev.owner; verificatore: dev.check. Nessun push o deploy.

- Provata una nuova domanda CIE Albano: presente la fonte comunale con data;
  la hero scompare e la conversazione diventa il contenuto principale.
- A 390, 500, 768 e 1440 px: larghezza documento uguale al viewport.
  Una colonna sugli schermi stretti, due su desktop; recapito telefonico
  leggibile su una riga a 390 px, pannello sotto la conversazione.
- Menu tecnico mobile: trovato e corretto il ritaglio dovuto a overflow della
  navigazione. Verificati apertura, hit-test del menu, Invio e Tab con focus
  visibile di 3 px.
- Nuova riga dei limiti: trovato contrasto insufficiente 4,02:1; follow-up
  `9ad99cc` verificato nel browser a **7,11:1**, testo 14,08 px.
- Diff esaminato nei quattro file frontend; `git diff --check` pulito.
  Typecheck e build Next riusciti secondo la consegna del builder; non
  rieseguiti dal verificatore dopo la sola correzione del colore.
- Banner conversazioni di 90 giorni preservato. Nessuna nuova promessa di
  copertura totale o di diritto certo alle agevolazioni.

Limiti: questa è QA di home, navigazione e ingresso/conversazione chat su
Chromium; non una revisione completa di tutte le pagine, di Safari o della
produzione. Il sito vetrina separato non è stato ristilato.

**Problema preesistente da risolvere per la ripresa della chat:** dopo una
risposta con scheda CIE, ricaricare la pagina ripristina il testo «qui accanto
trovi…», ma non scheda, link e pannello. Riprodotto sul runtime precedente
`:3000` e sulla preview `:3100`. Una nuova domanda restituisce nuovamente
la scheda. Non è una regressione del diff grafico, né è risolto dal restyling.
