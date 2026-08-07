/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  env: {
    // Server-side calls go to the api container; the browser talks to localhost.
    TREASUREIQ_API: process.env.TREASUREIQ_API ?? "http://localhost:8010",
  },

  // Il browser chiama `/api/*` sulla propria origine e Next inoltra qui. Cosi'
  // la pagina funziona identica su http://localhost:3000 e su
  // https://web.treasureiq.orb.local senza che nessuno debba ricordarsi di
  // aggiungere un dominio a due posti diversi (la base URL del client e la
  // lista CORS dell'API). Le rotte `/api` del filesystem, se un giorno ne
  // esisteranno, vincono comunque: `rewrites` sta in coda a quelle.
  async rewrites() {
    const api = process.env.TREASUREIQ_API_INTERNAL ?? "http://api:8000";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
export default nextConfig;
