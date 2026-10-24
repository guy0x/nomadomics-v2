import type { StrapiArticle } from "./strapi.ts";

export const HOMEPAGE_HERO_IMAGE = "/homepage/remote-work-mediterranean.png";

export const MONEY_SETUP_SLUG = "multi-currency-accounts";

export const FEATURED_SLUGS = [
  "best-countries-for-remote-workers",
  "europe-travel-rules",
  "cost-of-living-cape-town-nomads",
] as const;

export const HOMEPAGE_COPY = {
  eyebrow: "Nomadomics field notes",
  title: "Make a life abroad that works in real life.",
  intro:
    "Independent guides for choosing a base, planning the move, and setting up money across borders.",
  heroAlt:
    "Laptop, coffee, and notebook on a Mediterranean terrace overlooking a coastal village",
  heroCaption: "Field notes for living well abroad.",
  moneySetupLabel: "Read the money setup guide",
  moneySetupFallbackLabel: "Explore money guides",
  destinationsLabel: "Explore destinations",
  pillarsEyebrow: "Choose your route",
  pillarsTitle: "Start with the question you need answered",
  pillarsIntro:
    "Choose a practical guide for the decision in front of you, then keep moving with clearer next steps.",
  picksEyebrow: "Start here",
  picksTitle: "The guides worth opening first",
  picksIntro: "A considered place to begin before your next move.",
  latestEyebrow: "Fresh from the field",
  latestTitle: "Recent field notes",
  latestIntro: "Three practical reads for better decisions before, during, and after the flight.",
  allGuidesLabel: "All guides",
  trustEyebrow: "The Nomadomics approach",
  trustTitle: "Useful beats aspirational.",
  trustBody:
    "We care about the parts of travel that happen after the postcard: the trade-offs, the costs, and the small systems that make a place livable.",
  trustCta: "Read our editorial approach",
} as const;

export interface HomepageSelection {
  lead: StrapiArticle | null;
  featured: StrapiArticle[];
  latest: StrapiArticle[];
  moneySetup: StrapiArticle | null;
}

/**
 * Select homepage slots deterministically rather than trusting API order.
 * Curated slugs fall back to newest published articles; the money-setup guide
 * is excluded from the feed when it is only linked from the hero.
 */
export function selectHomepageArticles(
  articles: readonly StrapiArticle[],
): HomepageSelection {
  const bySlug = new Map(articles.map((article) => [article.slug, article]));
  const lead = bySlug.get(FEATURED_SLUGS[0]) ?? articles[0] ?? null;
  const used = new Set<string>();

  if (lead) used.add(lead.slug);

  const featured: StrapiArticle[] = [];
  for (const slug of FEATURED_SLUGS.slice(1)) {
    const article = bySlug.get(slug);
    if (!article || used.has(article.slug)) continue;
    featured.push(article);
    used.add(article.slug);
  }

  for (const article of articles) {
    if (featured.length >= 2) break;
    if (used.has(article.slug) || article.slug === MONEY_SETUP_SLUG) continue;
    featured.push(article);
    used.add(article.slug);
  }

  const moneySetup = bySlug.get(MONEY_SETUP_SLUG) ?? null;
  if (moneySetup) used.add(moneySetup.slug);

  return {
    lead,
    featured,
    latest: articles.filter((article) => !used.has(article.slug)).slice(0, 3),
    moneySetup,
  };
}

/** The homepage bridge always stays internal and falls back safely. */
export function moneySetupHref(moneySetup: StrapiArticle | null): string {
  return moneySetup ? `/${moneySetup.slug}` : "/category/banking";
}
