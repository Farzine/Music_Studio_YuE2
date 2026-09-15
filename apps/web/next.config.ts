import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // The API is a separate FastAPI process. Proxying keeps the browser on one
  // origin in development so audio Range requests and SSE behave normally.
  async rewrites() {
    const target = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";
    return [
      { source: "/api/v1/:path*", destination: `${target}/api/v1/:path*` },
      { source: "/ws/:path*", destination: `${target}/ws/:path*` },
    ];
  },
};

export default config;
