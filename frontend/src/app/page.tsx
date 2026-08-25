import Link from "next/link";
import { getPublishedArticles } from "@/lib/strapi";
import { CATEGORIES } from "@/lib/categories";
import ArticleCard from "@/components/ArticleCard";
import CategoryIcon from "@/components/CategoryIcon";
import { ArrowRight, TrendingUp } from "@/components/Icons";

export const revalidate = 300;

export default async function HomePage() {
  const articles = await getPublishedArticles();
  const [featured, ...rest] = articles;
  const latest = rest.slice(0, 9);

  return (
    <>
      {/* Hero */}
      <section className="border-b border-ink-100 bg-gradient-to-b from-brand-50 to-white">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
          <div className="max-w-3xl">
            <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-white px-3 py-1 text-xs font-semibold text-brand-700">
              <TrendingUp className="h-3.5 w-3.5" />
              Geoarbitrage, banking &amp; tax guides
            </p>
            <h1 className="font-display text-4xl font-bold leading-[1.1] tracking-tight text-ink-950 sm:text-5xl">
              Earn in dollars.
              <br />
              Live in <span className="text-brand-600">whatever currency wins.</span>
            </h1>
            <p className="mt-5 max-w-2xl text-lg leading-8 text-ink-600">
              Practical, no-nonsense guides to multi-currency banking, nomad
              taxes, and the logistics of working from anywhere — so you keep
              more of what you earn.
            </p>

            <div className="mt-8 flex flex-wrap gap-2">
              {CATEGORIES.map((c) => (
                <Link
                  key={c.slug}
                  href={`/category/${c.slug}`}
                  className="rounded-full border border-ink-200 bg-white px-4 py-2 text-sm font-medium text-ink-700 transition-colors hover:border-brand-400 hover:text-brand-700"
                >
                  {c.name}
                </Link>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Featured */}
      {featured && (
        <section className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
          <div className="mb-6 flex items-center justify-between">
            <h2 className="font-display text-2xl font-bold text-ink-950">Featured guide</h2>
          </div>
          <Link
            href={`/${featured.slug}`}
            className="group grid overflow-hidden rounded-2xl border border-ink-200 bg-white transition-shadow hover:shadow-lg md:grid-cols-2"
          >
            <div className="flex min-h-56 items-end bg-gradient-to-br from-brand-500 to-brand-800 p-6">
              <span className="rounded-full bg-white/90 px-3 py-1 text-xs font-bold uppercase tracking-wide text-ink-800">
                Editor&apos;s pick
              </span>
            </div>
            <div className="flex flex-col justify-center p-6 sm:p-8">
              <h3 className="font-display text-2xl font-bold leading-tight text-ink-950 group-hover:text-brand-700 sm:text-3xl">
                {featured.title}
              </h3>
              {featured.excerpt && (
                <p className="mt-3 text-base leading-7 text-ink-600">{featured.excerpt}</p>
              )}
              <span className="mt-5 inline-flex items-center gap-2 font-semibold text-brand-700">
                Read the guide
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </span>
            </div>
          </Link>
        </section>
      )}

      {/* Category grid */}
      <section className="border-y border-ink-100 bg-ink-50">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
          <h2 className="mb-6 font-display text-2xl font-bold text-ink-950">Browse by topic</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {CATEGORIES.map((c) => (
              <Link
                key={c.slug}
                href={`/category/${c.slug}`}
                className="group flex items-start gap-4 rounded-2xl border border-ink-200 bg-white p-5 transition-shadow hover:shadow-md"
              >
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                  <CategoryIcon slug={c.slug} className="h-6 w-6" />
                </span>
                <span>
                  <span className="block font-display text-base font-bold text-ink-950 group-hover:text-brand-700">
                    {c.name}
                  </span>
                  <span className="mt-0.5 block text-sm text-ink-600">{c.tagline}</span>
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* Latest feed */}
      <section className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <div className="mb-6 flex items-center justify-between">
          <h2 className="font-display text-2xl font-bold text-ink-950">Latest articles</h2>
          <span className="text-sm text-ink-500">{articles.length} guides</span>
        </div>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {latest.map((a) => (
            <ArticleCard key={a.documentId} article={a} />
          ))}
        </div>
      </section>
    </>
  );
}
