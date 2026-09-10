import { test } from "node:test";
import assert from "node:assert/strict";
import {
  hasYear,
  checkImageIntegrity,
  isHealthy,
  formatIntegrityReport,
} from "./image-integrity.ts";

test("hasYear flags 4-digit years but not yearless slugs", () => {
  assert.equal(hasYear("best-vpns-for-2025"), true);
  assert.equal(hasYear("2026-tax-guide"), true);
  assert.equal(hasYear("best-countries-for-remote-workers-in-2025"), true);
  assert.equal(hasYear("best-atms-in-spain"), false);
  assert.equal(hasYear("geoarbitrage"), false);
  // centuries other than 20xx are not "current-year" slugs
  assert.equal(hasYear("guide-to-1999-travel"), false);
});

test("checkImageIntegrity reports missing card and og independently", () => {
  const cards = new Set(["a.png"]);
  const ogs = new Set(["b.png"]);
  const result = checkImageIntegrity(["a", "b"], cards, ogs);
  assert.deepEqual(result.missingCards, ["b"]);
  assert.deepEqual(result.missingOgs, ["a"]);
  assert.deepEqual(result.yearSlugs, []);
});

test("checkImageIntegrity flags year-bearing slugs even when art exists", () => {
  const cards = new Set(["best-vpns-for-2025.png"]);
  const ogs = new Set(["best-vpns-for-2025.png"]);
  const result = checkImageIntegrity(["best-vpns-for-2025"], cards, ogs);
  assert.deepEqual(result.yearSlugs, ["best-vpns-for-2025"]);
  assert.deepEqual(result.missingCards, []);
});

test("healthy result requires full coverage and no years", () => {
  const files = new Set(["a.png", "b.png"]);
  const ok = checkImageIntegrity(["a", "b"], files, files);
  assert.equal(isHealthy(ok), true);

  const missing = checkImageIntegrity(["a", "b", "c"], files, files);
  assert.equal(isHealthy(missing), false);

  const year = checkImageIntegrity(["2026-a"], files, files);
  assert.equal(isHealthy(year), false);
});

test("formatIntegrityReport enumerates every problem and ends with OK", () => {
  const report = formatIntegrityReport(2, {
    missingCards: ["c"],
    missingOgs: ["d"],
    yearSlugs: ["2026-x"],
  });
  assert.match(report, /Checked 2 published slug/);
  assert.match(report, /Missing card images \(1\)/);
  assert.match(report, /\/cards\/c.png/);
  assert.match(report, /\/og\/d.png/);
  assert.match(report, /2026-x/);
  assert.doesNotMatch(report, /OK —/);

  const clean = formatIntegrityReport(1, {
    missingCards: [],
    missingOgs: [],
    yearSlugs: [],
  });
  assert.match(clean, /OK — every published slug has card \+ OG art/);
});