# TOP-3 PUBLISH RUNBOOK — Nomadomics ship set (2026-08-30)

> One review session. Approve the order → execute gates → published this week.
> All three articles sit in Strapi as **in_review** (never auto-published; `AUTO_PUBLISH_ENABLED=false`).
> Deploy reference: `docs/DEPLOY-HETZNER.md`. Repo: `guy0x/nomadomics-v2` (HTTPS remote, main).

## The 3 articles (readiness verified 2026-08-30)

| # | Strapi doc | Title | SEO score | Words | Meta ready |
|---|---|---|---|---|---|
| 1 | `s3grxo1ly8gwa0kue6rmio99` | Best Countries for Remote Workers in 2025 | 62 | 3008 | ✓ title 41 / desc 151 |
| 2 | `d8kqzcvyanx2ljmuoftqopst` | Top Geoarbitrage Hotspots for 2025 | 62 | 1775 | ✓ title 59 / desc 137 |
| 3 | `h2namtnlw8sf0usuabb82bcr` | 7 Best Flight Booking Apps in 2025 | 55 | 1053 | ✓ title 51 / desc 129 |

Checked 2026-08-30: bodies artifact-free (no CJK/control chars/mojibake/TODO), structure intact
(H2/H3 + tables + pros/cons + FAQ), metaTitle ≤60, metaDescription ≤155, focusKeyword +
targetKeywords set. Engine tests: 48 passed. Strapi: healthy (204), Cloudflare tunnel live.

⚠️ **Title collisions:** the published seed set already contains same-title WP-migrated
articles — id 52 `what-is-geoarbitrage` (vs #2) and id 34 `best-flight-booking-apps` (vs #3).
Decision needed at Gate 2: publish the new engine draft as the canonical version and
retire/supersede the WP seed, or rename one side.

## Guy gates (check as you go)

- [ ] **G1. Approve top-3 publish order:** 1 → Best Countries · 2 → Geoarbitrage · 3 → Flight Apps
- [ ] **G2. Resolve title collisions** for #2 (id 52) and #3 (id 34): recommend publishing the
      engine drafts as canonical and retiring the WP seed articles (or accepting both live).
- [ ] **G3. GitHub PAT push** — repo-scope PAT (`guy0x/nomadomics-v2` ONLY, never Hermes infra),
      entered in a terminal pane (never chat). `git push origin main` after any pending commit.
- [ ] **G4. Hetzner provision** — Phase 1–2 of `docs/DEPLOY-HETZNER.md`: CX22 VPS, Docker,
      Caddy TLS, DNS `api.<domain>`; migrate DB dump (Phase 3); create `frontend-read` token (Phase 4).
- [ ] **G5. Vercel import** — root `frontend/`, env `STRAPI_URL` / `STRAPI_API_TOKEN` /
      `NEXT_PUBLIC_SITE_URL` (Phase 5); verify homepage 200 + sitemap lists published slugs.
- [ ] **G6. Publish from Strapi admin** — flip the 3 articles `in_review → published` in admin.
      Guy only. No CLI publish.

## One ask
**Approve G1 (and G2) so the content mission converts this week.** Everything else in this
runbook is mechanical and staged — ATHENA/engine can escort you through G3–G6 on the day.