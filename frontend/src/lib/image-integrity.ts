/**
 * Published-article image integrity.
 *
 * Every published article must have a card (`/cards/<slug>.png`) and an OG
 * share image (`/og/<slug>.png`), and no published slug may carry a year
 * (mirrors the engine's `_yearless_slug` hard rule — see
 * `engine/pipeline_cli.py` + `engine/tests/test_yearless_slug.py`).
 *
 * This module is the frontend guard for that contract. It is pure and
 * dependency-free (no fs, no network) so it runs under `node --test` without
 * a bundler, and so CI can call it against a snapshot of published slugs plus
 * directory listings to catch a newly published article that shipped without
 * art, or a stray `-2026` slug reintroduced by hand.
 */

export interface ImageIntegrityResult {
  /** Slugs missing a `/cards/<slug>.png`. */
  missingCards: string[];
  /** Slugs missing an `/og/<slug>.png`. */
  missingOgs: string[];
  /** Slugs that contain a 4-digit year (violates the no-years-in-slugs rule). */
  yearSlugs: string[];
}

/** A 4-digit year anywhere in a slug is a policy violation. */
export function hasYear(slug: string): boolean {
  return /\b20\d{2}\b/.test(slug);
}

/**
 * Check every slug against the available card and OG filenames.
 *
 * `cardFiles`/`ogFiles` are sets of bare filenames (e.g. `"geoarbitrage.png"`),
 * matching what `fs.readdirSync` returns for `public/cards` and `public/og`.
 */
export function checkImageIntegrity(
  slugs: readonly string[],
  cardFiles: ReadonlySet<string>,
  ogFiles: ReadonlySet<string>,
): ImageIntegrityResult {
  const missingCards: string[] = [];
  const missingOgs: string[] = [];
  const yearSlugs: string[] = [];
  for (const slug of slugs) {
    if (hasYear(slug)) yearSlugs.push(slug);
    if (!cardFiles.has(`${slug}.png`)) missingCards.push(slug);
    if (!ogFiles.has(`${slug}.png`)) missingOgs.push(slug);
  }
  return { missingCards, missingOgs, yearSlugs };
}

/** True when every slug has both assets and none carries a year. */
export function isHealthy(result: ImageIntegrityResult): boolean {
  return (
    result.missingCards.length === 0 &&
    result.missingOgs.length === 0 &&
    result.yearSlugs.length === 0
  );
}

/** Human-readable report, one line per problem plus a summary. */
export function formatIntegrityReport(
  slugCount: number,
  result: ImageIntegrityResult,
): string {
  const lines: string[] = [`Checked ${slugCount} published slug(s).`];
  if (result.missingCards.length > 0) {
    lines.push(`Missing card images (${result.missingCards.length}):`);
    for (const s of result.missingCards) lines.push(`  - /cards/${s}.png`);
  }
  if (result.missingOgs.length > 0) {
    lines.push(`Missing OG images (${result.missingOgs.length}):`);
    for (const s of result.missingOgs) lines.push(`  - /og/${s}.png`);
  }
  if (result.yearSlugs.length > 0) {
    lines.push(`Slugs containing a year (${result.yearSlugs.length}):`);
    for (const s of result.yearSlugs) lines.push(`  - ${s}`);
  }
  if (isHealthy(result)) lines.push("OK — every published slug has card + OG art.");
  return lines.join("\n");
}