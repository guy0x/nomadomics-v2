import { NextResponse } from "next/server";
import { getAuthors, getPublishedArticles } from "@/lib/strapi";
import { CATEGORIES } from "@/lib/categories";
import { buildSitemapXml } from "@/lib/sitemapXml";

/**
 * Sitemap as a plain route handler (RUNBOOK 2026-10-08 F-01).
 *
 * The previous `app/sitemap.ts` metadata route was frozen at deploy time on
 * Vercel: its route-level ISR never regenerated, so the sitemap kept
 * advertising an article that had left the published set (HTTP 404). The
 * sibling `/feed.xml` route handler with the exact configuration below has
 * revalidated correctly on this stack since launch, so the sitemap now uses
 * the same shape — handler re-runs on the ISR interval, XML string returned
 * with explicit s-maxage.
 */
export const revalidate = 3600;

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export async function GET() {
  const [articles, authors] = await Promise.all([getPublishedArticles(), getAuthors()]);

  const entries = [
    { url: SITE_URL, changeFrequency: "daily" as const, priority: 1 },
    { url: `${SITE_URL}/about`, changeFrequency: "monthly" as const, priority: 0.3 },
    { url: `${SITE_URL}/privacy`, changeFrequency: "yearly" as const, priority: 0.3 },
    ...CATEGORIES.map((c) => ({
      url: `${SITE_URL}/category/${c.slug}`,
      changeFrequency: "weekly" as const,
      priority: 0.6,
    })),
    ...authors.map((a) => ({
      url: `${SITE_URL}/author/${a.slug}`,
      changeFrequency: "monthly" as const,
      priority: 0.5,
    })),
    ...articles.map((a) => ({
      url: `${SITE_URL}/${a.slug}`,
      lastModified: a.updatedAt,
      changeFrequency: "weekly" as const,
      priority: 0.8,
    })),
  ];

  return new NextResponse(buildSitemapXml(entries), {
    headers: {
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "s-maxage=3600, stale-while-revalidate",
    },
  });
}
