import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { StrapiArticle } from "./strapi.ts";
import {
  FEATURED_SLUGS,
  HOMEPAGE_COPY,
  HOMEPAGE_HERO_IMAGE,
  MONEY_SETUP_SLUG,
  moneySetupHref,
  selectHomepageArticles,
} from "./homepage.ts";

const article = (slug: string, title = slug): StrapiArticle => ({
  id: slug.length,
  documentId: `doc-${slug}`,
  title,
  slug,
  excerpt: `Excerpt for ${slug}`,
  bodyMarkdown: "one two three four five six seven eight nine ten",
  metaTitle: null,
  metaDescription: null,
  focusKeyword: null,
  targetKeywords: null,
  seoScore: null,
  readabilityScore: null,
  status: "published",
  publishedAt: "2026-10-24T00:00:00.000Z",
  updatedAt: "2026-10-24T00:00:00.000Z",
  createdAt: "2026-10-24T00:00:00.000Z",
});

test("pins the curated lead and feature order regardless of API order", () => {
  const input = [
    article("unrelated-first"),
    article(FEATURED_SLUGS[2]),
    article(FEATURED_SLUGS[0]),
    article(FEATURED_SLUGS[1]),
    article(MONEY_SETUP_SLUG),
    article("unrelated-last"),
  ];

  const selected = selectHomepageArticles(input);

  assert.equal(selected.lead?.slug, FEATURED_SLUGS[0]);
  assert.deepEqual(
    selected.featured.map((item) => item.slug),
    [FEATURED_SLUGS[1], FEATURED_SLUGS[2]],
  );
  assert.equal(selected.moneySetup?.slug, MONEY_SETUP_SLUG);
  assert.equal(moneySetupHref(selected.moneySetup), `/${MONEY_SETUP_SLUG}`);
  assert.deepEqual(
    selected.latest.map((item) => item.slug),
    ["unrelated-first", "unrelated-last"],
  );
});

test("falls back safely when curated or money-setup slugs are absent", () => {
  const selected = selectHomepageArticles([
    article("first"),
    article("second"),
    article("third"),
    article("fourth"),
  ]);

  assert.equal(selected.lead?.slug, "first");
  assert.deepEqual(
    selected.featured.map((item) => item.slug), ["second", "third"]);
  assert.deepEqual(selected.latest.map((item) => item.slug), ["fourth"]);
  assert.equal(selected.moneySetup, null);
  assert.equal(moneySetupHref(selected.moneySetup), "/category/banking");
});

test("renders a safe empty selection when Strapi has no published articles", () => {
  const selected = selectHomepageArticles([]);
  assert.deepEqual(selected, {
    lead: null,
    featured: [],
    latest: [],
    moneySetup: null,
  });
});

test("exposes intent-led copy, an editorial bridge, and a local hero path", () => {
  assert.equal(HOMEPAGE_COPY.eyebrow, "Nomadomics field notes");
  assert.equal(HOMEPAGE_COPY.title, "Make a life abroad that works in real life.");
  assert.equal(HOMEPAGE_COPY.moneySetupLabel, "Read the money setup guide");
  assert.equal(HOMEPAGE_HERO_IMAGE, "/homepage/remote-work-mediterranean.png");
});

test("hero artwork is checked into the public directory", () => {
  const heroPath = fileURLToPath(
    new URL(`../../public${HOMEPAGE_HERO_IMAGE}`, import.meta.url),
  );
  assert.equal(existsSync(heroPath), true);
});
