import type { MetadataRoute } from "next";

/**
 * Web app manifest. The site is not a PWA, but the manifest gives mobile
 * browsers the name and theme colour for add-to-home-screen and makes the
 * brand identity explicit to crawlers.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Nomadomics — money tips for travelers",
    short_name: "Nomadomics",
    description:
      "Practical guides to multi-currency banking, nomad taxes, and geoarbitrage — earn in one currency, live in another.",
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#0f8a5f",
    icons: [
      { src: "/favicon.ico", sizes: "any", type: "image/x-icon" },
      { src: "/apple-icon", sizes: "180x180", type: "image/png" },
    ],
  };
}
