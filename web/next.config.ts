import type { NextConfig } from "next";

const API = process.env.INKFALL_API ?? "http://127.0.0.1:5110";

// INKFALL_EXPORT=1 builds static pages into web/out, which the API serves itself on one port (127.0.0.1:5110):
// same origin, so no proxy, and the API sets the page headers (CSP, framing allowed only for the local Constellation).
const EXPORT = process.env.INKFALL_EXPORT === "1";

const devConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Same-origin proxy: the API sets an HttpOnly session cookie, so the browser must talk to it via this origin.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
  experimental: {
    // Local-model answers can take one to two minutes; the default proxy timeout is 30 s.
    proxyTimeout: 240_000,
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

const exportConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default EXPORT ? exportConfig : devConfig;
