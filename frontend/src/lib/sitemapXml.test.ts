import { test } from "node:test";
import assert from "node:assert/strict";
import { buildSitemapXml, type SitemapEntry } from "./sitemapXml.ts";

/** The reproduced F-01 defect: a sitemap-only slug that is not published. */
const CAPE_TOWN = "https://www.nomadomics.blog/cost-of-living-cape-town-nomads";

const PUBLISHED: SitemapEntry[] = [
  { url: "https://www.nomadomics.blog", changeFrequency: "daily", priority: 1 },
  {
    url: "https://www.nomadomics.blog/cost-of-living-berlin-digital-nomads",
    lastModified: "2026-10-07T07:47:58.135Z",
    changeFrequency: "weekly",
    priority: 0.8,
  },
];

test("clean case: emitted set is exactly the published set (no sitemap-only slugs)", () => {
  const xml = buildSitemapXml(PUBLISHED);
  const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
  assert.deepEqual(locs, PUBLISHED.map((e) => e.url));
  assert.ok(!xml.includes(CAPE_TOWN));
});

test("failing case: a stale sitemap-only slug is detectable in the emitted XML", () => {
  const stale: SitemapEntry[] = [
    ...PUBLISHED,
    { url: CAPE_TOWN, changeFrequency: "weekly", priority: 0.8 },
  ];
  const xml = buildSitemapXml(stale);
  const locs = new Set([...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]));
  assert.ok(locs.has(CAPE_TOWN)); // reproduces the defect shape
  // the invariant the QA sweep runs: set difference is non-empty
  const sitemapOnly = [...locs].filter((u) => !PUBLISHED.some((e) => e.url === u));
  assert.deepEqual(sitemapOnly, [CAPE_TOWN]);
});

test("handles relative URLs and URL-escapes XML-special characters", () => {
  const xml = buildSitemapXml([
    { url: "/relative-path" },
    { url: "https://x.example/a?b=1&c=2" },
  ]);
  assert.ok(xml.includes("<loc>/relative-path</loc>"));
  assert.ok(xml.includes("<loc>https://x.example/a?b=1&amp;c=2</loc>"));
});

test("serializes lastmod/changefreq/priority like the previous metadata route", () => {
  const xml = buildSitemapXml([
    {
      url: "https://www.nomadomics.blog/x",
      lastModified: new Date("2026-10-07T07:47:58.135Z"),
      changeFrequency: "weekly",
      priority: 0.8,
    },
  ]);
  assert.ok(
    xml.includes(
      "<url>\n<loc>https://www.nomadomics.blog/x</loc>\n<lastmod>2026-10-07T07:47:58.135Z</lastmod>\n<changefreq>weekly</changefreq>\n<priority>0.8</priority>\n</url>"
    )
  );
});

test("empty input is an explicit empty urlset, never a missing document", () => {
  const xml = buildSitemapXml([]);
  assert.match(xml, /<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/);
  assert.ok(xml.endsWith("</urlset>\n"));
  assert.equal([...xml.matchAll(/<loc>/g)].length, 0);
});
