# LAUNCH-READY — Homepage redesign + article completeness backfill (recon 2026-09-07)

> Recon for the launch-ready goal prompt. All values live-verified.

## Stream A — homepage as-is (structure + copy)

Sections: Hero → Featured ("Editor's pick") → Category grid → Latest feed (9 cards).

Verbatim copy:
- Hero badge: "Geoarbitrage, banking & tax guides"
- H1: "Earn in dollars. / Live in **whatever currency wins.**"
- Sub: "Practical, no-nonsense guides to multi-currency banking, nomad taxes, and the logistics of working from anywhere — so you keep more of what you earn."
- Featured header: "Featured guide" / badge "Editor's pick" — **honesty defect: `featured` = articles[0], un-curated**
- Grid header: "Browse by topic"; feed: "Latest articles" + "{n} guides"

Theme: `@theme` tokens in `globals.css` — emerald `brand` 50–950, slate `ink` 50–950,
`--font-inter` / `--font-display`. `brand_system.md` (sage/terracotta) is STALE — flag for archive.

Components: `SiteHeader` (sticky, logo + categories + "Best accounts" CTA), `SiteFooter`
(disclosure + copyright), `ArticleCard` (category-gradient header — no image), `CategoryIcon`.
Voice anchor: `engine/writer/prompts/voice_exemplar.md` (2nd person, money-first, snark at institutions).

## Stream B — backfill inventory (live, 13 published)

| slug | excerpt | focusKw | metaTitle | metaDesc |
|---|---|---|---|---|
| 2025-europe-travel-rules | Y | – | – | – |
| best-atms-in-spain | Y | – | – | – |
| best-multi-currency-credit-cards | Y | – | – | – |
| best-tax-free-shopping-destinations | Y | – | – | – |
| best-vpns-for-traveling | **–** | – | – | – |
| digital-nomad-taxes | Y | – | – | – |
| is-crypto-worth-it | Y | – | – | – |
| multi-currency-accounts | Y | – | – | – |
| rural-digital-nomad-destinations | Y | – | – | – |
| travel-hacks-to-save-money | Y | – | – | – |
| best-countries-for-remote-workers-in-2025 | Y | Y | Y | Y |
| top-geoarbitrage-hotspots-for-2025 | Y | Y | Y | Y |
| 7-best-flight-booking-apps-in-2025 | Y | Y | Y | Y |

→ 10 WP articles need focusKw + metaTitle + metaDescription (+1 missing excerpt);
3 engine drafts complete. All 13 publishedAt = today (un-staggered). All lack images.

## Image tooling (Phase 1 probe) — OUTCOME

- `gemini.google.com/images` in the automation browser: **not authenticated** initially.
  Guy signed in via a visible Brave window on the shared debug profile (9222) — session verified live.
- Gemini image API via `GEMINI_API_KEY`: 401 on native v1beta path, 429 quota-0 on the
  OpenAI-compat route (free tier excludes image models). Not usable.
- **FINAL PATH (used):** Guy-authenticated gemini.google.com web app, driven via CDP —
  13 photorealistic travel scenes (no text) generated one per article, extracted as
  canvas→dataURL→PNG, finalized with sips center-crop-to-fill
  (og 1200×630 → `public/og/<slug>.png`, cards 1200×675 → `public/cards/<slug>.png`).
- Strapi media upload NOT used: engine token is update-only (403 on /api/upload, by design).
  Images serve from the repo via slug convention — the frontend already wires
  `/og/<slug>.png` into og:image/twitter:image and `/cards/<slug>.png` into ArticleCard.
  Zero schema change, as the Prepared Default required.
