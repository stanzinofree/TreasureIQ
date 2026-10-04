# Dettagli ufficio mancanti: Poggio Mirteto

## Caso osservato (4 ottobre 2026)

Domanda: «Quali sono gli orari dell'ufficio anagrafe di Poggio Mirteto?».
La risposta mostra gli orari, ma indica che un recapito diretto non è nei dati
aperti letti dal connettore. La scheda ufficiale dell'ufficio pubblica altri
dati utili:

`https://comune.poggiomirteto.ri.it/amministrazione/unita_organizzativa/anagrafe/`

- Sezione `#persone`: Emiliano Armini e Simonetta Caramignoli, entrambi
  qualificati come «Referente», con link alle rispettive schede persona.
- Sezione `#sede-principale`: «Municipio», Piazza Martiri della Libertà n. 40,
  con link alla scheda della sede.
- Sezione `#contatti`: «Ufficio Anagrafe e Stato Civile», telefoni
  `+390765545209` e `+390765545230`, email
  `anagrafe.statocivile@comune.poggiomirteto.ri.it` e link alla scheda del
  punto di contatto.

La route REST `/wp-json/wp/v2/unita_organizzative?slug=anagrafe` restituisce
`title` e `link`, ma non espone `acf`, `content`, `sede`, `persone` o `contatti`.
`wordpress_agid._leggi_unita_wordpress_agid` legge l'indice REST e produce
quindi solo nome e URL. Gli orari arrivano da un successivo percorso di lettura
della pagina, che oggi non proietta questi dettagli nella scheda risposta.

## Intervento successivo

1. Leggere la scheda HTML dell'ufficio indicato dalla risposta, con guardia
   host e limiti di timeout/dimensione, usando le sezioni identificate da `id`.
   Non scaricare tutte le schede ufficio durante il bootstrap.
2. Restituire entrambi i referenti come elenco con ruolo e URL della fonte;
   non scegliere arbitrariamente uno dei due come `responsabile` singolare.
3. Restituire tutti i telefoni diretti, l'email e la sede, mantenendo distinta
   la scheda ufficio dal recapito generale del Comune. Valori assenti restano
   assenti; non inferirli dal JSON-LD globale dell'ente.
4. Proiettare questi campi in `OfficeAnswer`, `ChatOut` e nella card civica.
   La riga «Un recapito diretto non è tra i dati aperti letti dal connettore»
   deve sparire quando il recapito è stato effettivamente letto dalla scheda.
5. Verificare con una fixture della pagina Anagrafe e un test del percorso
   domanda → scheda risposta, includendo i due referenti e i due telefoni.

I modelli esistenti hanno già `indirizzo` e un `responsabile` opzionali, ma
`OfficeAnswer` ha un solo telefono e un solo responsabile. La forma dei dati
va estesa per rappresentare fedelmente questo caso prima di popolare la UI.
