import { test } from "node:test";
import assert from "node:assert/strict";
import { titledWithBrand, BRAND_SUFFIX, TITLE_BUDGET } from "./seo.ts";

test("keeps the brand when the pair fits the SERP budget", () => {
  const title = "Complete Guide to Europe 2026 Travel Rules"; // 42c
  assert.equal(titledWithBrand(title), title + BRAND_SUFFIX);
  assert.ok(titledWithBrand(title).length <= TITLE_BUDGET);
});

test("drops the brand rather than truncating the headline", () => {
  const title = "Travel Hacking for Beginners: 10 Simple Ways to Fly Cheap"; // 60c
  assert.equal(titledWithBrand(title), title);
  assert.equal(titledWithBrand(title).includes(BRAND_SUFFIX), false);
});

test("a title exactly at the budget boundary keeps the brand only if it fits", () => {
  const fits = "x".repeat(TITLE_BUDGET - BRAND_SUFFIX.length);
  assert.equal(titledWithBrand(fits), fits + BRAND_SUFFIX);
  assert.equal(titledWithBrand(fits + "y"), fits + "y");
});
