import type { NextConfig } from "next";

const API = process.env.INKFALL_API ?? "http://127.0.0.1:5110";

const nextConfig: NextConfig = {
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

export default nextConfig;
