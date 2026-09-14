import { NextResponse } from "next/server";
import { getPublishedArticles } from "@/lib/strapi";

export const revalidate = 3600;

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export async function GET() {
  const articles = await getPublishedArticles();

  const items = articles
    .map((a) => {
      const link = `${SITE_URL}/${a.slug}`;
      const pubDate = a.publishedAt
        ? new Date(a.publishedAt).toUTCString()
        : new Date(a.createdAt).toUTCString();
      const excerpt = escapeXml(a.excerpt ?? "");
      return `    <item>
      <title>${escapeXml(a.title)}</title>
      <link>${link}</link>
      <guid isPermaLink="true">${link}</guid>
      <pubDate>${pubDate}</pubDate>
      <description>${excerpt}</description>
    </item>`;
    })
    .join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Nomadomics</title>
    <link>${SITE_URL}</link>
    <description>Practical guides to multi-currency banking, nomad taxes, and geoarbitrage — earn in one currency, live in another.</description>
    <language>en</language>
    <lastBuildDate>${new Date().toUTCString()}</lastBuildDate>
    <atom:link href="${SITE_URL}/feed.xml" rel="self" type="application/rss+xml" />
${items}
  </channel>
</rss>`;

  return new NextResponse(xml, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Cache-Control": "s-maxage=3600, stale-while-revalidate",
    },
  });
}
