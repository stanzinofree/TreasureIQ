"""Matrice di prova contro l'API vera: 9 comuni x 5 domande x 2 profili.

Non e' un test automatico e non gira con `make test`: chiama l'API in
esecuzione e stampa una tabella da leggere con gli occhi. Serve a vedere il
comportamento d'insieme, che nessun test unitario mostra.

E' lo strumento che il 6 agosto 2026 ha trovato tre difetti che l'ispezione
del codice non aveva visto: la ricerca web che restituiva zero su ogni query,
il bando della Regione Lazio offerto a un comune siciliano, e il rail
informativo che dava zero risultati anche sui comuni ingeriti.

Uso:  python api/tests/matrice/matrice.py

Rispetta il limite di frequenza dell'API invece di aggirarlo: cosi' la matrice
prova anche quello.
"""

import json, urllib.request, itertools, sys, time

API = "http://localhost:8010/api/chat"
COMUNI = [
    ("INGERITO", "Benevento"), ("INGERITO", "Albano Laziale"), ("INGERITO", "Malvagna"),
    ("CONNETTORE", "Asola"), ("CONNETTORE", "Orta San Giulio"), ("CONNETTORE", "Belluno"),
    ("SOLO WEB", "Roncaro"), ("SOLO WEB", "Lanzada"), ("SOLO WEB", "Rodengo Saiano"),
]
DOMANDE = [
    ("asilo", "ci sono agevolazioni per l'asilo nido"),
    ("trasporto", "ci sono bandi per i mezzi pubblici"),
    ("tributi", "come pago la TARI"),
    ("anagrafe", "dove sta l'ufficio anagrafe e quando e' aperto"),
    ("affitto", "ci sono contributi per l'affitto"),
]
PROFILI = [("38a", "ho 38 anni"), ("70a+nucleo", "ho 70 anni e siamo in 4 in famiglia")]

# Il limite di frequenza e' nostro e serve: lo rispettiamo invece di
# aggirarlo, cosi' la matrice prova anche quello.
PAUSA = 3.2


def chiedi(msg):
    time.sleep(PAUSA)
    req = urllib.request.Request(API, data=json.dumps({"message": msg}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except Exception as e:
        return {"errore": type(e).__name__}

print("%-11s %-17s %-10s %-12s %-14s %-6s %-5s %-5s %s" % (
    "LIVELLO","COMUNE","DOMANDA","PROFILO","TOPIC","KIND","MATCH","LIVE","COMUNE CAPITO"))
for (livello, comune), (dnome, domanda), (pnome, profilo) in itertools.product(COMUNI, DOMANDE, PROFILI):
    msg = f"{profilo} e sono di {comune}, {domanda}?"
    d = chiedi(msg)
    if "errore" in d:
        print("%-11s %-17s %-10s %-12s ERRORE %s" % (livello, comune, dnome, pnome, d["errore"])); continue
    pc = d.get("profilo_capito") or {}
    info = d.get("info") or {}
    print("%-11s %-17s %-10s %-12s %-14s %-6s %-5d %-5s %s" % (
        livello, comune[:17], dnome, pnome, str(d.get("topic"))[:14], str(d.get("kind"))[:6],
        len(d.get("matches") or []), "si" if info.get("letto_dal_vivo") else "-",
        (pc.get("comune_nome") or "NON CAPITO")[:22]))
