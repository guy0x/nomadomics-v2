import Link from "next/link";
import Image from "next/image";
import { getPublishedArticles } from "@/lib/strapi";
import { CATEGORIES, categoryForSlug } from "@/lib/categories";
import ArticleCard from "@/components/ArticleCard";
import CategoryIcon from "@/components/CategoryIcon";
import { ArrowRight } from "@/components/Icons";
import {
  HOMEPAGE_COPY,
  HOMEPAGE_HERO_IMAGE,
  moneySetupHref,
  selectHomepageArticles,
} from "@/lib/homepage";
import { cardImageFor } from "@/lib/images";

export const revalidate = 300;

export default async function HomePage() {
  const articles = await getPublishedArticles();
  const { lead, featured, latest, moneySetup } = selectHomepageArticles(articles);
  const leadCategory = lead ? categoryForSlug(lead.slug) : null;
  const moneySetupLabel = moneySetup
    ? HOMEPAGE_COPY.moneySetupLabel
    : HOMEPAGE_COPY.moneySetupFallbackLabel;

  return (
    <>
      <section
        aria-labelledby="home-title"
        className="overflow-hidden bg-night-950 text-sand-50"
      >
        <div className="mx-auto grid max-w-7xl lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="flex flex-col justify-center px-4 py-14 sm:px-6 sm:py-16 lg:py-20 xl:px-10">
            <p className="mb-5 text-xs font-semibold uppercase tracking-[0.2em] text-sand-200">
              {HOMEPAGE_COPY.eyebrow}
            </p>
            <h1
              id="home-title"
              className="max-w-xl font-display text-4xl font-bold leading-[1.02] tracking-[-0.04em] text-sand-50 sm:text-6xl lg:text-7xl"
            >
              {HOMEPAGE_COPY.title}
            </h1>
            <p className="mt-6 max-w-lg text-lg leading-8 text-sand-200">
              {HOMEPAGE_COPY.intro}
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link
                href={moneySetupHref(moneySetup)}
                className="inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-sand-50 px-6 text-sm font-bold text-night-950 transition-colors hover:bg-sand-100"
              >
                {moneySetupLabel}
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/category/cities"
                className="inline-flex min-h-12 items-center justify-center rounded-full border border-sand-200/50 px-6 text-sm font-semibold text-sand-50 transition-colors hover:border-sand-50 hover:bg-white/10"
              >
                {HOMEPAGE_COPY.destinationsLabel}
              </Link>
            </div>
          </div>

          <figure className="relative min-h-[20rem] overflow-hidden sm:min-h-[27rem] lg:min-h-[38rem]">
            <Image
              src={HOMEPAGE_HERO_IMAGE}
              alt={HOMEPAGE_COPY.heroAlt}
              fill
              priority
              sizes="(max-width: 1023px) 100vw, 55vw"
              className="object-cover object-center"
            />
            <div
              aria-hidden="true"
              className="absolute inset-0 bg-gradient-to-t from-night-950/65 via-transparent to-transparent"
            />
            <figcaption className="absolute bottom-5 left-5 right-5 text-sm font-medium text-white sm:bottom-7 sm:left-7">
              {HOMEPAGE_COPY.heroCaption}
            </figcaption>
          </figure>
        </div>
      </section>

      <section
        id="topics"
        aria-labelledby="topics-title"
        className="border-b border-sand-200 bg-sand-50"
      >
        <div className="mx-auto max-w-7xl px-4 py-14 sm:px-6 lg:py-16">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-700">
              {HOMEPAGE_COPY.pillarsEyebrow}
            </p>
            <h2
              id="topics-title"
              className="mt-3 font-display text-3xl font-bold tracking-tight text-night-950 sm:text-4xl"
            >
              {HOMEPAGE_COPY.pillarsTitle}
            </h2>
            <p className="mt-3 text-base leading-7 text-ink-600">
              {HOMEPAGE_COPY.pillarsIntro}
            </p>
          </div>

          <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {CATEGORIES.map((category) => (
              <Link
                key={category.slug}
                href={`/category/${category.slug}`}
                className="group flex min-h-36 flex-col justify-between rounded-2xl border border-sand-200 bg-white p-5 transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-1 hover:border-brand-300 hover:shadow-lg"
              >
                <span className="flex items-center justify-between">
                  <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-50 text-brand-700">
                    <CategoryIcon slug={category.slug} className="h-5 w-5" />
                  </span>
                  <ArrowRight className="h-4 w-4 text-ink-400 transition-transform group-hover:translate-x-1 group-hover:text-brand-700" />
                </span>
                <span>
                  <span className="mt-5 block font-display text-base font-bold text-night-950 group-hover:text-brand-700">
                    {category.name}
                  </span>
                  <span className="mt-1 block text-sm leading-5 text-ink-600">
                    {category.tagline}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section
        aria-labelledby="picks-title"
        className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:py-20"
      >
        <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-700">
              {HOMEPAGE_COPY.picksEyebrow}
            </p>
            <h2
              id="picks-title"
              className="mt-3 font-display text-3xl font-bold tracking-tight text-night-950 sm:text-4xl"
            >
              {HOMEPAGE_COPY.picksTitle}
            </h2>
          </div>
          <p className="max-w-sm text-sm leading-6 text-ink-600 sm:text-right">
            {HOMEPAGE_COPY.picksIntro}
          </p>
        </div>

        {lead ? (
          <div
            className={
              featured.length > 0
                ? "grid gap-6 lg:grid-cols-[minmax(0,1.18fr)_minmax(16rem,0.82fr)]"
                : "max-w-3xl"
            }
          >
            <Link
              href={`/${lead.slug}`}
              className="group overflow-hidden rounded-3xl border border-sand-200 bg-white transition-[transform,box-shadow,border-color] duration-200 hover:-translate-y-1 hover:border-brand-300 hover:shadow-xl"
            >
              <div className="relative aspect-[16/10] overflow-hidden bg-sand-100">
                <Image
                  src={cardImageFor(lead.slug)}
                  alt={lead.title}
                  fill
                  priority
                  sizes="(max-width: 1023px) 100vw, 65vw"
                  className="object-cover transition-transform duration-500 group-hover:scale-[1.02]"
                />
                <span className="absolute left-5 top-5 rounded-full bg-white/95 px-3 py-1 text-xs font-bold uppercase tracking-wide text-night-950">
                  {leadCategory?.name ?? "Guide"}
                </span>
              </div>
              <div className="p-6 sm:p-8">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-700">
                  Featured guide
                </p>
                <h3 className="mt-3 max-w-2xl font-display text-2xl font-bold leading-tight text-night-950 group-hover:text-brand-700 sm:text-3xl">
                  {lead.title}
                </h3>
                {lead.excerpt && (
                  <p className="mt-3 max-w-2xl text-base leading-7 text-ink-600">
                    {lead.excerpt}
                  </p>
                )}
                <span className="mt-5 inline-flex items-center gap-2 text-sm font-bold text-brand-700">
                  Read the guide
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                </span>
              </div>
            </Link>

            {featured.length > 0 && (
              <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-1">
                {featured.map((article, index) => (
                  <ArticleCard
                    key={article.documentId}
                    article={article}
                    priority={index === 0}
                  />
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="rounded-2xl border border-dashed border-sand-200 bg-sand-50 p-10 text-center text-ink-600">
            New guides are on the way. Check back soon.
          </p>
        )}
      </section>

      <section
        aria-labelledby="latest-title"
        className="border-y border-sand-200 bg-sand-50"
      >
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:py-20">
          <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-brand-700">
                {HOMEPAGE_COPY.latestEyebrow}
              </p>
              <h2
                id="latest-title"
                className="mt-3 font-display text-3xl font-bold tracking-tight text-night-950 sm:text-4xl"
              >
                {HOMEPAGE_COPY.latestTitle}
              </h2>
            </div>
            <p className="max-w-sm text-sm leading-6 text-ink-600 sm:text-right">
              {HOMEPAGE_COPY.latestIntro}
            </p>
          </div>

          {latest.length > 0 ? (
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {latest.map((article, index) => (
                <ArticleCard
                  key={article.documentId}
                  article={article}
                  priority={index === 0}
                />
              ))}
            </div>
          ) : (
            <p className="rounded-2xl border border-dashed border-sand-200 bg-white p-10 text-center text-ink-600">
              More field notes are being prepared.
            </p>
          )}
        </div>
      </section>

      <section className="bg-night-950 text-sand-50">
        <div className="mx-auto grid max-w-7xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[0.8fr_1.2fr] lg:items-end lg:py-20">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sand-200">
              {HOMEPAGE_COPY.trustEyebrow}
            </p>
            <h2 className="mt-3 max-w-md font-display text-3xl font-bold tracking-tight sm:text-4xl">
              {HOMEPAGE_COPY.trustTitle}
            </h2>
            <p className="mt-4 max-w-md text-base leading-7 text-sand-200">
              {HOMEPAGE_COPY.trustBody}
            </p>
            <Link
              href="/editorial"
              className="mt-6 inline-flex items-center gap-2 text-sm font-bold text-sand-50 underline decoration-sand-200 underline-offset-4 hover:decoration-sand-50"
            >
              {HOMEPAGE_COPY.trustCta}
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>

          <dl className="grid gap-6 border-t border-sand-200/30 pt-8 sm:grid-cols-3 lg:border-t-0 lg:border-l lg:pl-10 lg:pt-0">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.18em] text-sand-200">
                01 / Choose
              </dt>
              <dd className="mt-2 text-sm leading-6 text-sand-50">
                Find places that fit the life you are building.
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.18em] text-sand-200">
                02 / Prepare
              </dt>
              <dd className="mt-2 text-sm leading-6 text-sand-50">
                Know the rules, routes, costs, and practical details.
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.18em] text-sand-200">
                03 / Go
              </dt>
              <dd className="mt-2 text-sm leading-6 text-sand-50">
                Arrive with fewer surprises and more room to explore.
              </dd>
            </div>
          </dl>
        </div>
      </section>
    </>
  );
}
