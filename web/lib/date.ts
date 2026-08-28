/**
 * Formattazione date it-IT, in un posto solo (slice S3). Prima ogni componente
 * teneva la propria copia identica di `dataLeggibile`; ora la forma vive qui e
 * i render la importano. Regola comune: mai «Invalid Date» a schermo.
 */

/** Data leggibile it-IT: «6 agosto 2026» (giorno / mese esteso / anno). Se
 *  l'ISO è illeggibile ripiega sulla stringa grezza, non su «Invalid Date». */
export function dataLeggibile(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("it-IT", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/** Data breve it-IT: «28 lug» (giorno / mese abbreviato). Su ISO illeggibile
 *  ripiega a stringa vuota — è una spia compatta, non un dato da mostrare. */
export function dataBreve(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("it-IT", { day: "numeric", month: "short" });
}
