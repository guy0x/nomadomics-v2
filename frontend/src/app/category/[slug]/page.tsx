import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getPublishedArticles } from "@/lib/strapi";
import { CATEGORIES, getCategory, categoryForSlug } from "@/lib/categories";
import ArticleCard from "@/components/ArticleCard";
import CategoryIcon from "@/components/CategoryIcon";
import { ChevronRight } from "@/components/Icons";

export const revalidate = 300;

export async function generateStaticParams() {
  return CATEGORIES.map((c) => ({ slug: c.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const category = getCategory(slug);
  if (!category) return {};
  return {
    title: `${category.name} — Guides & Comparisons`,
    description: category.description,
    alternates: { canonical: `/category/${category.slug}` },
  };
}

export default async function CategoryPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const category = getCategory(slug);
  if (!category) notFound();

  const all = await getPublishedArticles();
  const articles = all.filter((a) => categoryForSlug(a.slug).slug === category.slug);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <nav aria-label="Breadcrumb" className="mb-6 flex items-center gap-1.5 text-sm text-ink-500">
        <Link href="/" className="hover:text-brand-700">Home</Link>
        <ChevronRight className="h-3.5 w-3.5" />
        <span className="text-ink-700">{category.name}</span>
      </nav>

      <header className="mb-10 flex items-start gap-4">
        <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-brand-600 text-white">
          <CategoryIcon slug={category.slug} className="h-7 w-7" />
        </span>
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight text-ink-950 sm:text-4xl">
            {category.name}
          </h1>
          <p className="mt-2 max-w-2xl text-lg leading-7 text-ink-600">{category.description}</p>
        </div>
      </header>

      {articles.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-ink-300 bg-ink-50 p-10 text-center text-ink-500">
          No guides in this topic yet — check back soon.
        </p>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {articles.map((a) => (
            <ArticleCard key={a.documentId} article={a} />
          ))}
        </div>
      )}

      {/* Other topics */}
      <section className="mt-16 border-t border-ink-100 pt-10">
        <h2 className="mb-5 font-display text-xl font-bold text-ink-950">Other topics</h2>
        <div className="flex flex-wrap gap-2">
          {CATEGORIES.filter((c) => c.slug !== category.slug).map((c) => (
            <Link
              key={c.slug}
              href={`/category/${c.slug}`}
              className="rounded-full border border-ink-200 bg-white px-4 py-2 text-sm font-medium text-ink-700 transition-colors hover:border-brand-400 hover:text-brand-700"
            >
              {c.name}
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
