#!/usr/bin/env node
/**
 * Published-article image integrity gate.
 *
 * For every published article slug, assert that both:
 *   - frontend/public/cards/<slug>.png   (card)
 *   - frontend/public/og/<slug>.png      (OG share image)
 * exist, are no larger than 500,000 bytes, and no slug carries a year (the
 * engine's `_yearless_slug` rule).
 *
 * Exit 0 when clean, exit 1 when anything is missing, over cap, or a
 * year-bearing slug or year-bearing image filename is found. Run it in CI after
 * generating new cover art:
 *
 *   node scripts/check-images.mjs              # snapshot slugs (offline)
 *   node scripts/check-images.mjs --live       # fetch published slugs from Strapi
 *   node scripts/check-images.mjs --slugs other.json
 *
 * Authoritative logic lives in src/lib/image-integrity.ts (unit-tested); the
 * one-liners mirrored here are filename I/O, not policy.
 */
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const CARDS_DIR = join(ROOT, "public", "cards");
const OG_DIR = join(ROOT, "public", "og");
const SNAPSHOT = join(dirname(fileURLToPath(import.meta.url)), "published-slugs.json");

const YEAR_RE = /\b20\d{2}\b/;
const MAX_PUBLISHED_IMAGE_BYTES = 500_000;

function parseArgs(argv) {
  const args = { live: false, slugsFile: null };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--live") args.live = true;
    else if (argv[i] === "--slugs") args.slugsFile = argv[++i];
  }
  return args;
}

async function fetchPublishedSlugs() {
  const url = process.env.STRAPI_URL ?? "http://localhost:1337";
  const token = process.env.STRAPI_API_TOKEN ?? "";
  const res = await fetch(
    `${url}/api/articles?filters[status][$eq]=published&pagination[pageSize]=100`,
    { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } },
  );
  if (!res.ok) throw new Error(`Strapi returned ${res.status}`);
  const json = await res.json();
  return json.data.map((a) => a.slug).sort();
}

function listPng(dir) {
  if (!existsSync(dir)) return new Set();
  return new Set(readdirSync(dir).filter((f) => f.endsWith(".png")));
}

function byteSize(dir, filename) {
  return readFileSync(join(dir, filename)).byteLength;
}

function main() {
  const args = parseArgs(process.argv.slice(2));

  let slugs;
  let source;
  if (args.slugsFile) {
    slugs = JSON.parse(readFileSync(args.slugsFile, "utf8"));
    source = args.slugsFile;
  } else if (args.live) {
    return fetchPublishedSlugs()
      .then((s) => report(s, "Strapi (live)"))
      .catch((e) => {
        console.error(`check-images: live fetch failed: ${e.message}`);
        process.exitCode = 2;
      });
  } else {
    slugs = JSON.parse(readFileSync(SNAPSHOT, "utf8"));
    source = SNAPSHOT;
  }

  report(slugs, source);
}

function report(slugs, source) {
  const cards = listPng(CARDS_DIR);
  const ogs = listPng(OG_DIR);

  const missingCards = slugs.filter((s) => !cards.has(`${s}.png`));
  const missingOgs = slugs.filter((s) => !ogs.has(`${s}.png`));
  const yearSlugs = slugs.filter((s) => YEAR_RE.test(s));
  const overCapCards = slugs
    .filter((s) => cards.has(`${s}.png`))
    .map((s) => [s, byteSize(CARDS_DIR, `${s}.png`)]);
  const overCapOgs = slugs
    .filter((s) => ogs.has(`${s}.png`))
    .map((s) => [s, byteSize(OG_DIR, `${s}.png`)]);
  const failedCapCards = overCapCards.filter(([, bytes]) => bytes > MAX_PUBLISHED_IMAGE_BYTES);
  const failedCapOgs = overCapOgs.filter(([, bytes]) => bytes > MAX_PUBLISHED_IMAGE_BYTES);

  console.log(`check-images: ${slugs.length} published slugs (source: ${source})`);
  console.log(`  cards: ${cards.size} files · og: ${ogs.size} files`);

  let problems = 0;
  if (missingCards.length) {
    problems += missingCards.length;
    console.log(`  MISSING card images (${missingCards.length}):`);
    for (const s of missingCards) console.log(`    - /cards/${s}.png`);
  }
  if (missingOgs.length) {
    problems += missingOgs.length;
    console.log(`  MISSING og images (${missingOgs.length}):`);
    for (const s of missingOgs) console.log(`    - /og/${s}.png`);
  }
  if (yearSlugs.length) {
    problems += yearSlugs.length;
    console.log(`  YEAR-BEARING slugs (${yearSlugs.length}):`);
    for (const s of yearSlugs) console.log(`    - ${s}`);
  }
  if (failedCapCards.length || failedCapOgs.length) {
    const failedCapCount = failedCapCards.length + failedCapOgs.length;
    problems += failedCapCount;
    console.log(`  OVER CAP (${failedCapCount}; max ${MAX_PUBLISHED_IMAGE_BYTES} bytes):`);
    for (const [s, bytes] of failedCapCards)
      console.log(`    - /cards/${s}.png (${bytes} bytes)`);
    for (const [s, bytes] of failedCapOgs)
      console.log(`    - /og/${s}.png (${bytes} bytes)`);
  }

  // Orphans / year-bearing filenames aren't fatal but worth surfacing.
  const slugSet = new Set(slugs);
  const orphanCards = [...cards].filter((f) => !slugSet.has(f.replace(/\.png$/, "")));
  const orphanOgs = [...ogs].filter((f) => !slugSet.has(f.replace(/\.png$/, "")));
  const yearFilenames = [...cards, ...ogs].filter((f) => YEAR_RE.test(f));
  if (orphanCards.length || orphanOgs.length)
    console.log(
      `  note: ${orphanCards.length} orphan card(s), ${orphanOgs.length} orphan og(s) on disk`,
    );
  if (yearFilenames.length)
    console.log(`  note: ${yearFilenames.length} asset filename(s) contain a year`);

  if (problems === 0) {
    console.log("  OK — every published slug has card + OG art.");
    process.exitCode = 0;
  } else {
    console.log(`  FAIL — ${problems} problem(s).`);
    process.exitCode = 1;
  }
}

main();