/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  env: {
    // Server-side calls go to the api container; the browser talks to localhost.
    TREASUREIQ_API: process.env.TREASUREIQ_API ?? "http://localhost:8010",
  },
};
export default nextConfig;
