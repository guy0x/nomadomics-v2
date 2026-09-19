/**
 * Strapi v5 data layer.
 *
 * Server-only. All fetches go through ISR (`next: { revalidate }`) so pages
 * are statically generated and revalidated in the background.
 */

const STRAPI_URL = process.env.STRAPI_URL ?? "http://localhost:1337";
const STRAPI_TOKEN = process.env.STRAPI_API_TOKEN ?? "";

/** Seconds between ISR revalidations. */
export const REVALIDATE = 300;

export interface StrapiAuthor {
  id: number;
  documentId: string;
  name: string;
  slug: string;
  role: string | null;
  bio: string | null;
  credentials: string | null;
}

export interface StrapiArticle {
  id: number;
  documentId: string;
  title: string;
  slug: string;
  excerpt: string | null;
  bodyMarkdown: string;
  metaTitle: string | null;
  metaDescription: string | null;
  focusKeyword: string | null;
  targetKeywords: string | null;
  seoScore: number | null;
  readabilityScore: number | null;
  status: "draft" | "in_review" | "published" | "rejected";
  publishedAt: string | null;
  updatedAt: string;
  createdAt: string;
  /** Byline. Null on articles created before the author content type existed. */
  author?: StrapiAuthor | null;
}

interface StrapiListResponse<T> {
  data: T[];
  meta: {
    pagination: { page: number; pageSize: number; pageCount: number; total: number };
  };
}

/**
 * Fail-soft fetch: returns null when Strapi is unreachable or errors out
 * (e.g. during CI/Vercel builds where no CMS is reachable). Callers treat
 * null as "no content yet" and render empty state — the build must never die
 * because the CMS is offline. ISR will pick content up on the next revalidate.
 */
async function strapiFetch<T>(path: string, revalidate = REVALIDATE): Promise<T | null> {
  try {
    const res = await fetch(`${STRAPI_URL}${path}`, {
      headers: {
        ...(STRAPI_TOKEN ? { Authorization: `Bearer ${STRAPI_TOKEN}` } : {}),
        "Content-Type": "application/json",
      },
      next: { revalidate },
    });
    if (!res.ok) {
      console.warn(`[strapi] ${path} -> ${res.status}; rendering empty state`);
      return null;
    }
    return (await res.json()) as T;
  } catch (err) {
    console.warn(`[strapi] ${path} unreachable (${String(err)}); rendering empty state`);
    return null;
  }
}

/** All published articles, newest first, with their byline. Empty when Strapi is unreachable. */
export async function getPublishedArticles(): Promise<StrapiArticle[]> {
  const json = await strapiFetch<StrapiListResponse<StrapiArticle>>(
    `/api/articles?filters[status][$eq]=published&sort=publishedAt:desc&pagination[pageSize]=100&populate=author`
  );
  return json?.data ?? [];
}

/** A single published article by slug, or null. */
export async function getArticleBySlug(slug: string): Promise<StrapiArticle | null> {
  const json = await strapiFetch<StrapiListResponse<StrapiArticle>>(
    `/api/articles?filters[slug][$eq]=${encodeURIComponent(
      slug
    )}&filters[status][$eq]=published&pagination[pageSize]=1&populate=author`
  );
  return json?.data[0] ?? null;
}

/** Every author, alphabetical — for the About page's team section. */
export async function getAuthors(): Promise<StrapiAuthor[]> {
  const json = await strapiFetch<StrapiListResponse<StrapiAuthor>>(
    `/api/authors?sort=name:asc&pagination[pageSize]=100`
  );
  return json?.data ?? [];
}

/** A single author by slug, or null. */
export async function getAuthorBySlug(slug: string): Promise<StrapiAuthor | null> {
  const json = await strapiFetch<StrapiListResponse<StrapiAuthor>>(
    `/api/authors?filters[slug][$eq]=${encodeURIComponent(slug)}&pagination[pageSize]=1`
  );
  return json?.data[0] ?? null;
}

/** An author's published articles, newest first. */
export async function getArticlesByAuthor(documentId: string): Promise<StrapiArticle[]> {
  const json = await strapiFetch<StrapiListResponse<StrapiArticle>>(
    `/api/articles?filters[author][documentId][$eq]=${encodeURIComponent(
      documentId
    )}&filters[status][$eq]=published&sort=publishedAt:desc&pagination[pageSize]=100&populate=author`
  );
  return json?.data ?? [];
}

/** Slugs of all published articles (for generateStaticParams). */
export async function getPublishedSlugs(): Promise<string[]> {
  const articles = await getPublishedArticles();
  return articles.map((a) => a.slug);
}

/** Estimated reading time in minutes from the markdown body. */
export function readingTimeMinutes(bodyMarkdown: string): number {
  const words = bodyMarkdown.trim().split(/\s+/).length;
  return Math.max(1, Math.round(words / 200));
}
