import Link from "next/link";
import Image from "next/image";
import { getPublishedArticles } from "@/lib/strapi";
import { CATEGORIES } from "@/lib/categories";
import ArticleCard from "@/components/ArticleCard";
import { cardImageFor } from "@/lib/images";
import { ArrowRight, TrendingUp } from "@/components/Icons";

export const revalidate = 300;

export default async function HomePage() {
  const articles = await getPublishedArticles();
  // "Start here" = the flagship guide (pinned by publish recency of the engine's
  // strongest draft, not an unexplained editorial opinion).
  const startHere =
    articles.find((a) => a.slug === "best-countries-for-remote-workers") ?? articles[0];
  const rest = articles.filter((a) => a.slug !== startHere?.slug);
  const latest = rest.slice(0, 9);

  return (
    <>
      {/* Hero — typography-led money-frame */}
      <section className="border-b border-ink-100 bg-gradient-to-b from-ink-50 to-white">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
          <div className="max-w-3xl">
            <p className="mb-5 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-white px-3 py-1 text-xs font-semibold text-brand-700">
              <TrendingUp className="h-3.5 w-3.5" />
              Money tips for travelers — no fluff, all numbers
            </p>
            <h1 className="font-display text-5xl font-extrabold leading-[1.05] tracking-tight text-ink-950 sm:text-6xl">
              Keep more of what you earn.
              <br />
              Live{" "}
              <span className="text-brand-600">wherever you want.</span>
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-ink-600">
              No-fluff money guides for people who work online and sleep in a
              different timezone — banking that doesn&apos;t bleed you, taxes you
              can actually understand, and the real cost of every border.
            </p>

            <div className="mt-9 flex flex-wrap gap-2">
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

          {/* Honest stat strip */}
          <dl className="mt-14 grid max-w-2xl grid-cols-3 gap-6 border-t border-ink-200 pt-8">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wider text-ink-500">Guides</dt>
              <dd className="mt-1 font-display text-3xl font-extrabold text-ink-950">{articles.length}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wider text-ink-500">Topics</dt>
              <dd className="mt-1 font-display text-3xl font-extrabold text-ink-950">{CATEGORIES.length}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wider text-ink-500">Cost to read</dt>
              <dd className="mt-1 font-display text-3xl font-extrabold text-brand-600">$0</dd>
            </div>
          </dl>
        </div>
      </section>

      {/* Start here — flagship guide with real cover image */}
      {startHere && (
        <section className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
          <div className="mb-6 flex items-baseline justify-between">
            <h2 className="font-display text-2xl font-bold text-ink-950">Start here</h2>
            <span className="text-sm text-ink-500">the guide that saves you the most</span>
          </div>
          <Link
            href={`/${startHere.slug}`}
            className="group grid overflow-hidden rounded-2xl border border-ink-200 bg-white transition-shadow hover:shadow-lg md:grid-cols-2"
          >
            <div className="relative aspect-[16/9] bg-brand-50 md:aspect-auto md:min-h-[21rem]">
              <Image
                src={cardImageFor(startHere.slug)}
                alt=""
                fill
                sizes="(max-width: 768px) 100vw, 50vw"
                className="object-cover"
                priority
              />
            </div>
            <div className="flex flex-col justify-center p-6 sm:p-8">
              <span className="mb-3 inline-flex w-fit rounded-full bg-brand-600 px-3 py-1 text-xs font-bold uppercase tracking-wide text-white">
                Start here
              </span>
              <h3 className="font-display text-2xl font-bold leading-tight text-ink-950 group-hover:text-brand-700 sm:text-3xl">
                {startHere.title}
              </h3>
              {startHere.excerpt && (
                <p className="mt-3 text-base leading-7 text-ink-600">{startHere.excerpt}</p>
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
      <section className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <div className="mb-6 flex items-baseline justify-between">
          <h2 className="font-display text-2xl font-bold text-ink-950">Latest articles</h2>
          <span className="text-sm text-ink-500">one new guide most weekdays</span>
        </div>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {latest.map((a, i) => (
            <ArticleCard key={a.documentId} article={a} priority={i < 3} />
          ))}
        </div>
      </section>

      {/* Newsletter close — honest (no provider wired yet) */}
      <section className="border-t border-ink-100 bg-brand-50">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="font-display text-3xl font-bold text-ink-950">
              One money tip a week.
            </h2>
            <p className="mt-3 text-lg leading-8 text-ink-600">
              The kind you can use at a border crossing. No spam, no course
              upsell — unsubscribe in one click.
            </p>
            <div className="mt-6 flex justify-center gap-2">
              <Link
                href="/about"
                className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-6 py-3 text-sm font-semibold text-white transition-colors hover:bg-brand-700"
              >
                Start with the best guides
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
            <p className="mt-3 text-xs text-ink-500">
              Newsletter coming soon — for now, everything we publish is free on
              the site.
            </p>
          </div>
        </div>
      </section>
    </>
  );
}
