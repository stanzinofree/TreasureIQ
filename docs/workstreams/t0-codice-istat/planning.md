# T0 — Planning operativo

## Obiettivo globale

Rendere il codice ISTAT una fonte validata, versionata, osservabile e capace di
gestire transizioni amministrative senza orfanare dati storici.

## Step corrente — 3: delega dei lettori al registry (APPROVATO)

> Step 0 chiuso da Claude e confermato da Codex il 2026-08-21 (inventario in
> `done.md`). L'inventario ha aggiunto due vincoli al validatore:
> deve coprire il caso `censimento` (5 letture senza guardia) e il fatto che
> 8/10 lettori oggi non validano la riga.

> Step 1 chiuso contrattualmente da Claude e confermato da Codex il 2026-08-21.
> Il codice resta non wire-ato e il freeze resta attivo.

> Step 2 chiuso lato Claude e confermato da Codex il 2026-08-21. La provenienza
> della baseline resta pianificata nello Step 5; l'assenza del file è
> `FrameIOError` nel registry, mentre il validator diretto conserva `INVALID`.

### Obiettivo Step 3

Far delegare `sonda_live` e i lettori progressivamente a un solo registry
typed, preservando le quattro firme pubbliche e rendendo osservabili gli esiti
di caricamento, senza cambiare il comportamento dei caller.

### Output richiesto

- delega di `_indice` e `_tutti` a un'unica sorgente, senza doppia cache stale;
- migrazione dei lettori censiti nello Step 0 in gruppi verificabili;
- gestione distinta di frame invalido, review richiesta ed errore I/O;
- test di parità e invalidazione delle cache;
- test deterministici, senza rete e senza modifica al frame reale.

### Criteri di accettazione

- [ ] `sonda_live` non mantiene due cache indipendenti del frame;
- [ ] i lettori migrati non leggono più dict grezzi;
- [ ] le quattro firme runtime restano compatibili;
- [ ] errore I/O e `FrameOutcome.INVALID` sono distinguibili;
- [ ] nessuna scrittura su `data/comuni-istat.json`;
- [ ] test deterministici verdi e freeze rispettato.

> Costruito lato Claude il 2026-08-21: `frame_validation.py` +
> `test_frame_validation.py` (19 passed). Contratto concordato in `done.md`.
>
> Step 2 costruito lato Claude il 2026-08-21: `municipality_registry.py` +
> `test_municipality_registry.py` (parità vs `sonda_live`). Suite combinata
> **82 passed**. Contratto in `done.md` § «Step 2». Attende concordanza Codex
> prima dello Step 3 (migrazione lettori).

---

## Step 0 — inventario degli accessi (COMPLETATO)

### Obiettivo

Chiudere l'elenco di ogni lettura diretta di `data/comuni-istat.json`, dei
contratti che restituiscono il codice e degli artefatti persistiti che usano
il codice come segmento di percorso o chiave.

### Output richiesto

- tabella modulo/funzione/frequenza/fail-mode;
- elenco degli artefatti da preservare in caso di transizione;
- decisione su runtime versus batch;
- nessun cambio di comportamento ancora.

### Criteri di accettazione

- nessun accesso diretto non classificato resta fuori dall'inventario;
- ogni lettore ha un proprietario e un contratto di errore previsto;
- sono inclusi almeno i casi `sonda_live`, `registro`, `registro_cli`,
  `censimento` e `dati_cli`;
- Claude e Codex concordano l'output annotandolo in `done.md`.

## Step successivi

1. Fixture e contratto di `FrameValidator`.
2. `MunicipalityRegistry` e `SourceFrame` read-only.
3. Migrazione dei lettori.
4. Generatore atomico.
5. Manifest/hash e verifica runtime.
6. Diff upstream e transizioni amministrative.

## Lock cross-workstream storage-lifecycle

T0 può proseguire con registry, modello typed e test read-only. Non può però
spostare o riscrivere `storico.db`, snapshot catalogo o altri artefatti keyed su
`codice_istat` finché storage-lifecycle non chiude il contratto dei root e il
piano di rollback. La migrazione fisica resta una fase coordinata.
