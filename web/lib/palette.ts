/**
 * Chart colours, in one place.
 *
 * The order below is fixed and never cycled: a platform keeps its colour when
 * a filter removes the ones around it. Repainting survivors makes two
 * different charts of the same page tell different stories about the same
 * vendor, and readers trust colour before they read labels.
 *
 * These are not the app's status colours. `--shu`, `--wakatake` and
 * `--yamabuki` already mean blocking / criterion met / not verifiable, and
 * reusing them as "series 3" would quietly break that vocabulary — a green
 * bar would read as approval of a vendor rather than as its identity.
 *
 * Validated against the light surface (#f2f4f7) for lightness band, chroma
 * floor, colour-vision separation, normal-vision separation and contrast.
 * If you change a value, re-run the validator rather than trusting the eye.
 */
export const CATEGORICAL = [
  "#0057b8", // blu — la tinta di marca
  "#0f9d8f", // teal
  "#8257b8", // viola
  "#b5561f", // terra
  "#c0367d", // magenta
] as const;

/**
 * Riservato a ciò che non è stato misurato o riconosciuto.
 *
 * `ignota` e `non_misurata` non sono categorie in gara: sono assenza di dato,
 * e prendersi una tinta piena le farebbe sembrare un fornitore come gli
 * altri — per giunta il più diffuso d'Italia, che è esattamente la lettura
 * sbagliata.
 */
export const NEUTRO = "#98a2b3";

const SENZA_TINTA = new Set(["ignota", "non_misurata"]);

/**
 * Ardesia per la coda lunga dei fornitori riconosciuti.
 *
 * Volutamente diverso da `NEUTRO`: un Drupal con quattro comuni è una
 * piattaforma che sappiamo nominare, e dipingerlo dello stesso grigio dei
 * portali muti direbbe al lettore che non l'abbiamo riconosciuto — che è il
 * contrario di quel che è successo.
 */
export const ALTRE = "#5a6880";

/** Quante piattaforme ricevono una tinta propria prima di essere raggruppate. */
export const TINTE_PROPRIE = CATEGORICAL.length;

/** Il colore di una piattaforma, stabile fra grafici e fra ricariche. */
export function coloreP(piattaforma: string, ordine: readonly string[]): string {
  if (SENZA_TINTA.has(piattaforma)) return NEUTRO;
  if (piattaforma === "altre") return ALTRE;
  const posto = ordine.filter((p) => !SENZA_TINTA.has(p)).indexOf(piattaforma);
  if (posto < 0) return ALTRE;
  // Oltre la quinta non si inventa una tinta: la coda si raggruppa in una
  // voce sola, e la tabella sotto la elenca per intero.
  return CATEGORICAL[posto] ?? ALTRE;
}

/** Etichette leggibili per le piattaforme, senza underscore in faccia. */
export const NOMI: Record<string, string> = {
  wp_design_comuni: "WordPress Design Comuni",
  wordpress_generico: "WordPress generico",
  peopleweb: "PeopleWeb (Siscom)",
  comweb: "ComWeb (ePublic)",
  dotnetnuke: "DotNetNuke",
  flexcmp: "FlexCMP",
  isweb: "IsWeb",
  citypal: "CityPal",
  drupal: "Drupal",
  joomla: "Joomla",
  liferay: "Liferay",
  typo3: "TYPO3",
  plone: "Plone",
  altre: "Altre piattaforme riconosciute",
  regione_fvg: "Regione FVG (piattaforma condivisa)",
  regione_veneto: "Regione Veneto (piattaforma condivisa)",
  rete_civica_lepida: "Rete Civica Lepida (Emilia-Romagna)",
  pageobject: "PageObject (fornitore da identificare)",
  hgate: "HGATE (fornitore da identificare)",
  openpa: "OpenPA",
  municipium: "Municipium (Maggioli)",
  agenda_smart: "AgendaSmart (fornitore da identificare)",
  magnolia: "Magnolia CMS",
  comunibootstrapitalia: "ComuniBootstrapItalia",
  ignota: "Non riconosciuta",
  non_misurata: "Non misurata",
};

export const nome = (p: string) => NOMI[p] ?? p;

/** Sezioni del modello AgID in italiano leggibile. */
export const SEZIONI: Record<string, string> = {
  a_chi_e_rivolto: "A chi è rivolto",
  descrizione: "Descrizione",
  come_fare: "Come fare",
  cosa_serve: "Cosa serve",
  cosa_si_ottiene: "Cosa si ottiene",
  tempi_e_scadenze: "Tempi e scadenze",
  quanto_costa: "Quanto costa",
  accedi_al_servizio: "Accedi al servizio",
  condizioni_di_servizio: "Condizioni di servizio",
  documenti_e_allegati: "Documenti e allegati",
  contatti: "Contatti",
};

export const sezione = (s: string) => SEZIONI[s] ?? s;
