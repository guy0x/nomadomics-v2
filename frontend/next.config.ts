import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the bundle lean — the site is content-first with minimal client JS.
  poweredByHeader: false,
  compress: true,
  // Pin the Turbopack root to this app (the monorepo has a parent lockfile).
  turbopack: { root: __dirname },
};

export default nextConfig;
