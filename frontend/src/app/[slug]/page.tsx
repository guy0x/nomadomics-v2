import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getArticleBySlug,
  getPublishedSlugs,
  getPublishedArticles,
  readingTimeMinutes,
} from "@/lib/strapi";
import { categoryForSlug } from "@/lib/categories";
import { commercialForSlug, defaultOfferForCategory } from "@/lib/offers";
import { renderBody } from "@/components/renderBody";
import QuickVerdict from "@/components/QuickVerdict";
import ComparisonTable from "@/components/ComparisonTable";
import StickyOfferBar from "@/components/StickyOfferBar";
import ProsCons from "@/components/ProsCons";
import TableOfContents from "@/components/TableOfContents";
import ReadingProgress from "@/components/ReadingProgress";
import AdvertiserDisclosure from "@/components/AdvertiserDisclosure";
import ArticleCard from "@/components/ArticleCard";
import { Clock, ChevronRight } from "@/components/Icons";

export const revalidate = 300;
export const dynamicParams = true;

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export async function generateStaticParams() {
  const slugs = await getPublishedSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const article = await getArticleBySlug(slug);
  if (!article) return {};

  const title = article.metaTitle ?? article.title;
  const description = article.metaDescription ?? article.excerpt ?? undefined;
  const url = `${SITE_URL}/${article.slug}`;

  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: {
      title,
      description,
      url,
      type: "article",
      publishedTime: article.publishedAt ?? undefined,
      modifiedTime: article.updatedAt,
    },
    twitter: { card: "summary_large_image", title, description },
  };
}

function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default async function ArticlePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const article = await getArticleBySlug(slug);
  if (!article) notFound();

  const category = categoryForSlug(article.slug);
  const commercial = commercialForSlug(article.slug);
  const stickyOffer = commercial?.stickyOffer ?? defaultOfferForCategory(category.slug);
  const { html, toc } = renderBody(article.bodyMarkdown);
  const mins = readingTimeMinutes(article.bodyMarkdown);
  const published = formatDate(article.publishedAt);

  // Related articles: same category first, then newest
  const all = await getPublishedArticles();
  const related = all
    .filter((a) => a.slug !== article.slug)
    .sort((a, b) => {
      const ac = categoryForSlug(a.slug).slug === category.slug ? 0 : 1;
      const bc = categoryForSlug(b.slug).slug === category.slug ? 0 : 1;
      return ac - bc;
    })
    .slice(0, 3);

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: article.title,
    description: article.metaDescription ?? article.excerpt ?? undefined,
    datePublished: article.publishedAt ?? undefined,
    dateModified: article.updatedAt,
    mainEntityOfPage: `${SITE_URL}/${article.slug}`,
    author: { "@type": "Organization", name: "Nomadomics" },
    publisher: { "@type": "Organization", name: "Nomadomics" },
    ...(commercial?.quickVerdict
      ? {
          review: {
            "@type": "Review",
            reviewRating: {
              "@type": "Rating",
              ratingValue: commercial.quickVerdict.score,
              bestRating: 10,
            },
            itemReviewed: {
              "@type": "Product",
              name: commercial.quickVerdict.offer.name,
            },
          },
        }
      : {}),
  };

  return (
    <>
      <ReadingProgress />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />

      <article className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        {/* Breadcrumb */}
        <nav aria-label="Breadcrumb" className="mb-6 flex items-center gap-1.5 text-sm text-ink-500">
          <Link href="/" className="hover:text-brand-700">Home</Link>
          <ChevronRight className="h-3.5 w-3.5" />
          <Link href={`/category/${category.slug}`} className="hover:text-brand-700">
            {category.name}
          </Link>
          <ChevronRight className="h-3.5 w-3.5" />
          <span className="truncate text-ink-700">{article.title}</span>
        </nav>

        <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_16rem] lg:gap-12">
          {/* Main column */}
          <div className="max-w-3xl">
            <header>
              <span className="rounded-full bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-wide text-brand-700">
                {category.name}
              </span>
              <h1 className="mt-4 font-display text-3xl font-bold leading-tight tracking-tight text-ink-950 sm:text-4xl">
                {article.title}
              </h1>
              {article.excerpt && (
                <p className="mt-4 text-lg leading-8 text-ink-600">{article.excerpt}</p>
              )}
              <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-ink-500">
                <span className="flex items-center gap-1.5">
                  <Clock className="h-4 w-4" />
                  {mins} min read
                </span>
                {published && <span>Updated {published}</span>}
                <AdvertiserDisclosure />
              </div>
            </header>

            {commercial?.quickVerdict && <QuickVerdict verdict={commercial.quickVerdict} />}

            {/* Body */}
            <div className="article-body mt-8" dangerouslySetInnerHTML={{ __html: html }} />

            {commercial?.comparison && <ComparisonTable table={commercial.comparison} />}
            {(commercial?.pros || commercial?.cons) && (
              <ProsCons pros={commercial.pros ?? []} cons={commercial.cons ?? []} />
            )}

            {/* Related */}
            {related.length > 0 && (
              <section className="mt-16 border-t border-ink-100 pt-10">
                <h2 className="mb-6 font-display text-2xl font-bold text-ink-950">
                  Keep reading
                </h2>
                <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                  {related.map((a) => (
                    <ArticleCard key={a.documentId} article={a} />
                  ))}
                </div>
              </section>
            )}
          </div>

          {/* Sidebar TOC (desktop) */}
          <aside className="mt-10 hidden lg:mt-0 lg:block">
            <div className="sticky top-24">
              <TableOfContents items={toc} />
            </div>
          </aside>
        </div>
      </article>

      {stickyOffer && <StickyOfferBar offer={stickyOffer} />}
    </>
  );
}
