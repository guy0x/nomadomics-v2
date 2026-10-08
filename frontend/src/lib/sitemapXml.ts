/**
 * Sitemap XML builder — pure and dependency-free (no `@/` imports) so the
 * `node --test` suite can exercise it without path aliases.
 *
 * Byte-compatible with what the Next metadata sitemap route emitted before
 * this module existed (RUNBOOK 2026-10-08 F-01): same <urlset> shape, field
 * order, and serialization for plain url/lastmod/changefreq/priority entries.
 */

export interface SitemapEntry {
  url: string;
  lastModified?: string | Date;
  changeFrequency?: "always" | "hourly" | "daily" | "weekly" | "monthly" | "yearly" | "never";
  priority?: number;
}

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/**
 * Serialize sitemap entries to the urlset XML document.
 *
 * The emitted set is exactly the passed set, in order — callers are the sole
 * authority on what goes in (the route handler derives it from the live
 * published set on every revalidation).
 */
export function buildSitemapXml(entries: SitemapEntry[]): string {
  const body = entries
    .map((e) => {
      const lastmod =
        e.lastModified instanceof Date ? e.lastModified.toISOString() : e.lastModified;
      const lines = ["<url>", `<loc>${escapeXml(e.url)}</loc>`];
      if (lastmod) lines.push(`<lastmod>${lastmod}</lastmod>`);
      if (e.changeFrequency) lines.push(`<changefreq>${e.changeFrequency}</changefreq>`);
      if (typeof e.priority === "number") lines.push(`<priority>${e.priority}</priority>`);
      lines.push("</url>");
      return lines.join("\n");
    })
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`;
}
