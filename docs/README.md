# Documentazione di TreasureIQ

| Documento | Cosa risponde |
|---|---|
| [architettura.md](architettura.md) | com'è fatto il sistema oggi, con le dimensioni misurate |
| [evoluzione.md](evoluzione.md) | cosa costruire dopo l'MVP, cosa scartare, e a quali condizioni rivedere ogni scelta |
| [sicurezza.md](sicurezza.md) | abuso dell'API, cortesia verso i portali, dati sensibili del cittadino — con le lacune dichiarate |
| [connettori.md](connettori.md) | quali piattaforme leggiamo e fin dove, quanto costa alzare il livello, e cosa cambia per la chat |
| [roadmap.md](roadmap.md) | in che ordine affrontarle, e perche' quell'ordine |
| [da-fare.md](da-fare.md) | cosa e' rotto, cosa manca, e quanto costa ciascuna cosa |
| [api.md](api.md) | cosa significano le risposte — Swagger su `/docs`, collection Bruno in `bruno/` |
| [motore-dati.html](motore-dati.html) | la stessa architettura in forma visiva, apribile nel browser |

## Come leggere i numeri

Due convenzioni valgono ovunque, nel codice come in questi documenti.

**Un campo non misurato resta vuoto, mai zero.** Su un grafico uno zero e uno
sconosciuto hanno lo stesso aspetto e significato opposto.

**Ogni classificazione porta la prova.** Un enum senza la stringa verbatim che
l'ha deciso è un'opinione con una faccia seria — e questi numeri finiscono
accanto al nome di aziende e di comuni reali.
