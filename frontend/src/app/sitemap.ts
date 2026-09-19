import type { MetadataRoute } from "next";
import { getAuthors, getPublishedArticles } from "@/lib/strapi";
import { CATEGORIES } from "@/lib/categories";

export const revalidate = 3600;

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [articles, authors] = await Promise.all([getPublishedArticles(), getAuthors()]);

  const articleUrls: MetadataRoute.Sitemap = articles.map((a) => ({
    url: `${SITE_URL}/${a.slug}`,
    lastModified: a.updatedAt,
    changeFrequency: "weekly",
    priority: 0.8,
  }));

  const categoryUrls: MetadataRoute.Sitemap = CATEGORIES.map((c) => ({
    url: `${SITE_URL}/category/${c.slug}`,
    changeFrequency: "weekly",
    priority: 0.6,
  }));

  const authorUrls: MetadataRoute.Sitemap = authors.map((a) => ({
    url: `${SITE_URL}/author/${a.slug}`,
    changeFrequency: "monthly",
    priority: 0.5,
  }));

  return [
    { url: SITE_URL, changeFrequency: "daily", priority: 1 },
    { url: `${SITE_URL}/about`, changeFrequency: "monthly", priority: 0.3 },
    ...categoryUrls,
    ...authorUrls,
    ...articleUrls,
  ];
}
