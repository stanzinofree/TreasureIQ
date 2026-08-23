# Workstream T0 — codice ISTAT

Workstream condiviso tra Codex e Claude per rendere verificabile e migrabile
la chiave comunale prima di collegarla ai nuovi registry e connettori.

## Regola di base

Un agente lavora su un solo step alla volta. Non modifica il runtime finché lo
step non è descritto in `planning.md` e non ha un criterio di accettazione.

## Artefatti

- `planning.md`: obiettivo, step corrente, dipendenze e criteri di accettazione;
- `execution.md`: attività aperte, decisioni in attesa e file toccati;
- `done.md`: attività chiuse, test eseguiti e handoff al passo successivo.

Il documento architetturale globale resta `docs/t0-codice-istat.md`; questi
file isolano il building operativo senza duplicare le decisioni di fondo.

## Protocollo di handoff

Prima di iniziare:

1. leggere `docs/t0-codice-istat.md`, `planning.md` ed `execution.md`;
2. dichiarare in `execution.md` l'agente, lo step e i file previsti;
3. non modificare file fuori perimetro senza annotare il motivo.

Alla conclusione:

1. eseguire i test pertinenti e riportare il comando esatto;
2. aggiornare `done.md` con risultato, test e rischi residui;
3. svuotare o chiudere l'attività in `execution.md`;
4. aggiornare `planning.md` indicando lo step successivo;
5. attendere la valutazione dell'altro agente prima di procedere oltre.

## Stato del repository

Freeze attivo: nessun commit, deploy o modifica distruttiva al frame senza
accordo esplicito. In questa fase si lavora su contratti, fixture, analisi e
test; il worker di sweep resta fermo.
