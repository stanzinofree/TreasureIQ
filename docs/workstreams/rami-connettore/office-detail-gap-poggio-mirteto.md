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

## Intervento realizzato nel ramo `feat/municipal-connector-coverage`

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

La lettura su richiesta della scheda ora estrae le persone, i recapiti diretti
e la sede dallo stesso HTML usato per gli orari. La risposta API espone
`persone` come elenco di nome, ruolo verbatim e URL. La card mostra «Persone
indicate dal Comune» e non converte «Referente» in «Responsabile».
Il telefono resta un campo testuale nella risposta chat, con i due numeri
separati da virgola; la card li presenta come due link distinti.

Verifica successiva: la scheda Anagrafe di Albano Laziale pubblica Simona
Polizzano nella sezione «Persone», con il testo dell'incarico. Il suo markup
WordPress differisce da Poggio Mirteto; l'estrattore ora legge entrambe le
forme. Se una scheda WordPress è stata letta e non contiene persone, la card
lo dice in modo circoscritto alla scheda. Se una sezione contiene link persona
che l'estrattore non sa interpretare, non dichiara l'assenza.

## Estensione delle persone nelle altre famiglie

La lettura della singola scheda ufficio supporta ora anche:

| Famiglia | Scheda verificata | Forma del dato |
|---|---|---|
| OpenWeb | Collegno | nome, ruolo e link nella sezione `#persone` |
| PeopleWeb, vendor OpenWeb.NET | Airasca | responsabile e personale in sezioni distinte, con le etichette pubblicate |
| OpenPA | Storo | tutte le card della sezione persone, con ruolo e link |
| Municipium | Pomezia | nome e link; ruolo assente nella scheda |
| Drupal | Fiesole | nome, descrizione dell'incarico e link |
| Magnolia | Farini | nome e link; ruolo dalla sezione «Responsabile» solo se il link coincide |

Il dialetto Siscom della famiglia PeopleWeb resta senza elenco: la scheda
campione non espone una lista equivalente. Queste letture avvengono alla domanda
sull'ufficio, usando l'HTML già scaricato per gli orari; il bootstrap conserva
solo nome e URL degli uffici.
