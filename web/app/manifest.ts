/**
 * The web app manifest — what an installed TreasureIQ looks like.
 *
 * `theme_color` is the brand blue rather than the page background: it tints
 * the system bars around the installed app, and the light grey would leave a
 * device unable to tell where the app's chrome ends. `background_color`
 * matches the page, so the splash does not flash a different colour before
 * the first paint.
 *
 * Both icons are the compass, and `maskable` is deliberately not claimed: the
 * mark has a star sitting proud of the ring at the top right, and Android's
 * maskable crop is aggressive enough to cut it off. Declaring a shape we do
 * not have would trade a small letterbox for a clipped logo.
 */

import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "TreasureIQ — opportunità che ti riguardano",
    short_name: "TreasureIQ",
    description:
      "Legge ciò che Stato, Regioni e Comuni hanno pubblicato e ti mostra a cosa hai davvero accesso — o cosa manca perché si possa dire.",
    start_url: "/",
    display: "standalone",
    lang: "it",
    background_color: "#F2F4F7",
    theme_color: "#0057B8",
    icons: [
      { src: "/icon.svg", type: "image/svg+xml", sizes: "any" },
      { src: "/apple-icon", type: "image/png", sizes: "180x180" },
    ],
  };
}
