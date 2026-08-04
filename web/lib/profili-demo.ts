/**
 * The mock identities the demo offers in place of a real SPID/CIE session.
 *
 * Shared between the chat's inline escalation and the sign-in overlay so
 * there is one list, not two that can drift apart. Every figure here is
 * invented: an ISEE, not an income — the indicator weighs assets and
 * household size, so the two are not interchangeable and a profile that
 * conflated them would state a number the card repeats back as fact.
 */

export const PRESETS = [
  {
    id: "famiglia",
    persona: "Giulia Bianchi",
    situazione: "Lavora, un figlio piccolo, un ISEE che apre parecchie porte.",
    name: "Famiglia con figlio minore",
    detail: "38 anni · ISEE 12.000 € · nucleo di 3",
    profile: {
      eta: 38,
      isee: "12000",
      nucleo_familiare: 3,
      figli_minori: 1,
      employment_status: "occupato",
      interests: ["famiglie", "studenti"],
    },
  },
  {
    id: "pensionato",
    persona: "Mario Rossi",
    situazione: "Vive solo, pensione media: sopra molte soglie, sotto qualche altra.",
    name: "Pensionato che vive solo",
    detail: "71 anni · ISEE 30.000 € · nucleo di 1",
    profile: {
      eta: 71,
      isee: "30000",
      nucleo_familiare: 1,
      figli_minori: 0,
      employment_status: "pensionato",
      interests: ["anziani"],
    },
  },
  {
    id: "studente",
    persona: "Luca Verdi",
    situazione: "Fuori corso e senza lavoro, cerca contributi per studio e affitto.",
    name: "Studente in cerca di lavoro",
    detail: "23 anni · ISEE 8.000 € · nucleo di 2",
    profile: {
      eta: 23,
      isee: "8000",
      nucleo_familiare: 2,
      figli_minori: 0,
      employment_status: "disoccupato",
      interests: ["studenti", "disoccupati"],
    },
  },
  {
    // The comfortable case, and the one worth showing: a household well above
    // every means threshold gets a clean, immediate "no" with the figure that
    // decided it. A service that only ever says yes teaches nobody anything.
    //
    // The figure is an ISEE, not an income. A four-person household earning
    // over 60.000 € has an ISEE far below that — the indicator weighs assets
    // and household size — so writing 60.000 here would put a number on screen
    // that misdescribes the family it claims to represent. 28.000 € is the
    // realistic reading for this profile, and it clears the bonus sociale
    // ceiling of 9.796 € several times over, which is the point of the demo.
    id: "capofamiglia",
    persona: "Anna Neri",
    situazione: "Quattro persone in casa e un reddito che esclude la maggior parte dei bonus.",
    name: "Capofamiglia, reddito alto",
    detail: "45 anni · ISEE 28.000 € · nucleo di 4",
    profile: {
      eta: 45,
      isee: "28000",
      nucleo_familiare: 4,
      figli_minori: 2,
      employment_status: "occupato",
      interests: ["famiglie"],
    },
  },
] as const;

export type Preset = (typeof PRESETS)[number];
