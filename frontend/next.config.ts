import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the bundle lean — the site is content-first with minimal client JS.
  poweredByHeader: false,
  compress: true,
  // Pin the Turbopack root to this app (the monorepo has a parent lockfile).
  turbopack: { root: __dirname },
  // Retired duplicate: the Aug-23 travel-hacks article was superseded by the
  // Oct-10 rewrite (same title, two documents — kanban t_7bdd6aea). The old
  // URL is preserved via a permanent 301 to the kept article.
  async redirects() {
    return [
      {
        source: "/travel-hacks-to-save-money",
        destination: "/14-travel-hacks-that-ll-save-you-money",
        statusCode: 301,
      },
    ];
  },
};

export default nextConfig;
