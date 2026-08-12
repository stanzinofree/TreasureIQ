/**
 * What we hold ourselves to.
 *
 * Structured after Fondazione Openpolis' manifesto, which the project takes as
 * a model: a short diagnostic opening, then sections headed by a single noun
 * and written in the first person plural as commitments rather than
 * descriptions. Nothing of theirs is reproduced — what is borrowed is the
 * shape and the plainness.
 *
 * The division with /info is deliberate and was not always respected: both
 * pages once opened with the same headline. This one is why we do it and what
 * we refuse to do; /info is how the machinery works. Where a claim here has a
 * number behind it, the number is a measured one and links to where it can be
 * checked.
 *
 * A server page: public information about the project, no client JS.
 */

import Link from "next/link";

export const metadata = {
  title: "Manifesto — TreasureIQ",
  description:
    "A cosa ci teniamo, cosa non facciamo, e quali registri pubblici leggiamo per farlo.",
};

type Principio = { titolo: string; corpo: React.ReactNode };

const PRINCIPI: Principio[] = [
  {
    titolo: "Assenza",
    corpo: (
      <>
        Quando un&apos;amministrazione non ha pubblicato una cosa, lo diciamo.
        Non riempiamo il vuoto con una stima, non lo mascheriamo dietro una
        risposta generica e non lo lasciamo in silenzio — perché
        un&apos;assenza taciuta è indistinguibile da una ricerca che nessuno ha
        fatto. «Il comune non lo ha scritto da nessuna parte» è una risposta, e
        spesso è la più utile che possiamo dare.
      </>
    ),
  },
  {
    titolo: "Prova",
    corpo: (
      <>
        Un requisito compare solo se esiste, nel documento pubblicato, la frase
        che lo dice. Quelle frasi vengono ricontrollate contro la fonte: se non
        si ritrovano, il requisito cade. Preferiamo dire di non sapere piuttosto
        che riportare un criterio che nessuno ha scritto.
      </>
    ),
  },
  {
    titolo: "Verdetto",
    corpo: (
      <>
        A decidere se una misura ti spetta è una regola leggibile, non un
        modello linguistico. Il modello capisce la tua domanda e nulla più: non
        stabilisce esiti, non calcola soglie, non riscrive cifre. È un limite
        che ci siamo dati, non una mancanza — un verdetto che nessuno può
        ricostruire non è verificabile da nessuno.
      </>
    ),
  },
  {
    titolo: "Costo",
    corpo: (
      <>
        Misuriamo quanto lavoro serve per leggere ciò che è stato pubblicato, e
        quel costo è nostro: nessun cittadino lo paga, né in denaro né in tempo.
        Lo rendiamo pubblico perché è l&apos;argomento più concreto che
        conosciamo a favore dei dati aperti — leggere Ariccia costa quasi il
        doppio per servizio rispetto ad Albano, e la differenza non sta nei
        cittadini né negli uffici: sta in un&apos;interfaccia spenta.{" "}
        <Link href="/dati">I conti sono qui</Link>.
      </>
    ),
  },
  {
    titolo: "Provenienza",
    corpo: (
      <>
        Ogni affermazione porta con sé da dove viene e di quando è. Un recapito
        senza fonte e senza data è un recapito di cui nessuno risponde, e chi se
        ne fida rischia di trovare uno sportello chiuso. Dove la fonte è un
        registro ufficiale lo diciamo; dove è una pagina trovata cercando, lo
        diciamo con la stessa chiarezza.
      </>
    ),
  },
  {
    titolo: "Identità",
    corpo: (
      <>
        Chiediamo chi sei solo quando saperlo cambia la risposta. Se i criteri
        non sono stati pubblicati, identificarsi non serve a niente, e
        proporlo sarebbe una promessa falsa. Chiediamo il minimo che serve a
        rispondere, e niente che renderebbe interessante rubarci il database.
      </>
    ),
  },
  {
    titolo: "Standard",
    corpo: (
      <>
        Non proponiamo un nuovo standard. Ne esistono già — il modello Design
        Comuni Italia prevede il campo dei vincoli, che quasi nessuno compila —
        e aggiungerne un altro sposterebbe il problema invece di risolverlo.
        Leggiamo quelli che ci sono, e mostriamo quanto costa quando non
        vengono usati.
      </>
    ),
  },
  {
    titolo: "Amministrazioni",
    corpo: (
      <>
        Quello che pubblichiamo sono fatti sui portali, mai giudizi sulle
        persone che li governano. Un dato mancante quasi mai è pigrizia: è un
        gestionale che non lo esporta, un modulo nato in PDF, un ufficio con due
        persone. Vogliamo dare a chi amministra un argomento da portare a chi
        decide i bilanci, non una pagella da subire.
      </>
    ),
  },
  {
    titolo: "Registri",
    corpo: (
      <>
        Cataloghiamo solo fonti pubbliche, e diciamo quali. Le API dei servizi
        comunali dove esistono; l&apos;Indice della Pubblica Amministrazione per
        gli enti e i loro canali certificati; i cataloghi nazionali per le
        misure che valgono ovunque; le pagine dei portali istituzionali come
        ultima risorsa, marcate come non verificate. Nient&apos;altro entra: se
        una pagina non appartiene a un ente pubblico non la mostriamo, e se
        appartiene a un altro comune non è la tua.
      </>
    ),
  },
  {
    titolo: "Apertura",
    corpo: (
      <>
        Il codice è leggibile e riusabile da chiunque, con licenza Apache 2.0, e
        le misure che pubblichiamo sono ricalcolabili da chi voglia contestarle.
        Quando troviamo un buco, quello che chiediamo non è di fidarsi di noi: è
        che quel dato venga aperto, così che leggerlo smetta di costare — anche
        a chi verrà dopo e non saprà che siamo esistiti.
      </>
    ),
  },
];

export default function Manifesto() {
  return (
    <div className="stack">
      <section className="manifesto-hero">
        <div className="manifesto-hero__inner">
          <p className="eyebrow">Manifesto</p>
          <h1>Quello che è pubblico dovrebbe essere leggibile</h1>
          <p className="lede">
            I dati che dicono a una persona se ha diritto a un aiuto quasi
            sempre esistono, e sono pubblicati: dentro una notizia, in fondo a
            un PDF allegato, in una frase scritta una volta e mai tipizzata.
            Sono pubblici e illeggibili insieme, e la distanza fra le due cose
            la paga chi ha meno tempo e più bisogno.
          </p>
          <p className="lede">
            TreasureIQ prova a colmare quella distanza leggendo al posto di chi
            chiede, e misurando quanto costa farlo. Queste sono le cose a cui
            non rinunciamo mentre lo facciamo.
          </p>
        </div>
      </section>

      <section className="panel">
        <ul className="principi">
          {PRINCIPI.map((p) => (
            <li key={p.titolo} className="principio">
              <h2>{p.titolo}</h2>
              <p>{p.corpo}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="manifesto-fondatore">
        <div className="manifesto-fondatore__inner">
          <p className="eyebrow">Voce del fondatore</p>
          <h2>Perché ho iniziato</h2>
          <div className="manifesto-fondatore__corpo">
            <p>
              Ogni tanto capita di dover cercare gli orari di un ufficio del
              comune, di capire a chi rivolgersi per un certificato, o di sapere
              se c&apos;è un bando a cui si ha diritto. Oggi è più facile di
              qualche anno fa, ma ancora insoddisfacente per l&apos;era in cui
              siamo. Si viene rediretti da un portale all&apos;altro, quando va
              bene; altrimenti si finisce su un 404 o su un sito che non risponde
              più. È lì che ho iniziato: fare in modo che quello che sul comune A
              sta sotto «Servizi» e sul comune B sotto «Uffici», sotto TIQ sia in
              una chat.
            </p>
            <p>
              TIQ non è la soluzione: è un apriscatole. Il problema non sono i
              fornitori che costruiscono le loro piattaforme — è che non c&apos;è
              una spinta comune a farli lavorare su uno schema condiviso di
              esposizione dei dati. Ogni connettore che scrivo è, allo stesso
              tempo, la misura di quanto manca a quello standard.
            </p>
            <p>
              L&apos;obiettivo vero è che quello che oggi provo a fare io, da
              privato e da solo, venga perseguito dallo Stato: che diventi una
              piattaforma centralizzata, o quantomeno la strada di riferimento
              per la trasparenza dei comuni. TIQ serve finché la scatola è
              chiusa.
            </p>
          </div>
          <p className="manifesto-fondatore__firma">
            — Alessandro Middei, fondatore di TreasureIQ
          </p>
        </div>
      </section>

      <section className="manifesto-cta">
        <h2>Come funziona, nel dettaglio</h2>
        <p className="lede">
          Questa pagina dice a cosa ci teniamo. Se ti interessa il meccanismo —
          come si decide un esito, cosa succede a una frase che non si ritrova
          nella fonte, quali gradini scendiamo per arrivare a un dato — è
          scritto altrove.
        </p>
        <p className="manifesto-cta__azioni">
          <Link className="button" href="/info">
            Come funziona
          </Link>
          <Link className="button button--ghost" href="/dati">
            Le misure
          </Link>
        </p>
      </section>
    </div>
  );
}
