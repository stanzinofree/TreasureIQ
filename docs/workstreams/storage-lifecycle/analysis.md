# Ciclo di vita dello storage della conversazione

Stato: **DRAFT.** Descrive dove vive il testo del cittadino, per quanto, e con
quali uscite. Nessun deploy, nessun logging attivato da questo documento.
Accompagna l'hardening della PR #96 (R1–R5) e la decisione backup R3A.

> **Ambito.** Qui si parla di *dove risiede* e *quanto sopravvive* il transcript,
> non del suo contenuto. Il contenuto dei DB conversazioni non è stato letto né
> riprodotto: le uniche misure citate sono conteggi aggregati.

## 1. Stadi del dato

Il testo del cittadino attraversa stadi distinti, con durata e superficie di
uscita diverse. Tenerli separati è il punto: un rischio su uno stadio non è un
rischio su tutti.

| Stadio | Dove | Durata | Uscita dalla macchina |
|---|---|---|---|
| Elaborazione transitoria | RAM del processo API, per-richiesta | vita della richiesta | nessuna (rail deterministico) |
| Transcript persistito | `data-live/conversations.sqlite3` (volume `/live`) | TTL 90gg, rinnovato all'accesso, poi purge | nessuna |
| Provider intent (rail `model`) | payload verso un provider | vita della richiesta | locale (Ollama) o esterno (Anthropic), vedi §4 |
| Corpus futuro | non ancora esistente | — | fuori sessione, previa base giuridica (protocollo-raccolta) |

Il **rail deterministico** (`rust`/`scorer`, default del codice dopo R4) non
carica alcun provider: l'elaborazione transitoria non lascia il processo.

## 2. Transcript persistito e retention

Il transcript è **stato temporaneo**, non fonte di verità operativa. Serve a
riprendere una conversazione in corso, non a costituire un archivio.

- TTL `CONVERSATION_TTL = 90 giorni`, rinnovato a ogni accesso.
- Purge deterministico all'avvio + task periodico in-process (R1): gli scaduti
  vengono **cancellati**, non solo nascosti.
- `forget()` cancella conversazione, messaggi ed eventi (le tre tabelle).
- Il cookie di sessione (`tiq_conversation`) è il bearer del transcript:
  `HttpOnly`, `SameSite=Lax`, e `Secure` obbligatorio in produzione (R2).

## 3. Backup — decisione R3A

`make backup` **esclude** `data-live/conversations.sqlite3` (e sidecar).

Motivazione: il transcript è progettato come stato temporaneo soggetto alla
retention applicativa (§2). Replicarlo in archivi di lunga durata lo
sottrarrebbe alla retention — copie che sopravvivono al TTL e al `forget()`,
esattamente ciò che la retention vuole evitare. Quindi:

- backup e restore coprono solo dati curati/runtime necessari (`data/storico.db`,
  il resto di `data-live/`);
- il DB conversazioni resta sul volume `/live`, soggetto a TTL + purge;
- `restore` estrae solo i file archiviati: un `conversations.sqlite3` già sul
  volume sopravvive al restore, ma nessun transcript viene reintrodotto da un
  archivio;
- **dopo un disaster restore le conversazioni possono andare perse.** È il
  comportamento voluto, non un difetto.

### 3.1 Quando servirebbe R3B (non attivo)

Solo se emerge il requisito esplicito «resume anche dopo disaster recovery» il
transcript andrebbe conservato oltre il volume live. In quel caso, e solo
allora:

- backup separato dal backup dati curati;
- cifratura forte;
- chiave **fuori dal repository e fuori dall'archivio**;
- retention propria del backup;
- restore esplicito e auditato;
- procedura di cancellazione che raggiunga **anche le copie cifrate** (altrimenti
  `forget()` e il diritto di cancellazione restano aggirabili).

Nessuna cifratura applicativa viene introdotta senza prima confermare questo
requisito: aggiungerla «per sicurezza» creerebbe copie da gestire senza un
bisogno di restore che le giustifichi.

## 4. Superfici di uscita del provider (R5)

Tre superfici distinte; solo la terza lascia la macchina.

- **Ollama** — daemon locale, default per ogni ruolo. Nessuna uscita su internet.
- **llama.cpp narrator** — superficie locale sulla rete compose, off di default;
  rifinisce una risposta già deterministica, non classifica.
- **Anthropic** — unica superficie esterna. Sul rail `model` invia il messaggio
  del cittadino (più gli ultimi 3 turni etichettati e delimitati) a un terzo.
  `external_egress = True`; `load_provider` la rifiuta senza consenso esplicito
  (`TREASUREIQ_ALLOW_EXTERNAL_LLM`) → fail-fast, non egress silenzioso.

## 5. Corpus futuro

La raccolta di un corpus reale **non è attiva** e non è toccata da questo
workstream. Vive fuori sessione, previa base giuridica, secondo
`docs/workstreams/facet-variante-corpus/protocollo-raccolta.md`. Il transcript
persistito (§2) non è un corpus: è stato operativo temporaneo, non un dataset
condiviso.
