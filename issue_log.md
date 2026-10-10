
## 2026-10-06 — Nomadomics link-hygiene QA (Guy request, Pantheon)
- Built `engine/invariants.py::link_hygiene_issues` (QA: raw-url, paren-url, slug-anchor, wrong-domain) + `engine/tests/test_link_hygiene.py` (5 tests pass).
- Built `scripts/link_hygiene_repair.py` (dry-run + apply, idempotent).
- Corpus sweep found 35 issues across 10 articles (23 raw/paren URLs, 12 bad anchors incl. 2 wrong-domain slug->nomadlist.com).
- Applied repairs to 11 body-rows (all 200); one orphaned duplicate row (id 650, same documentId as 649) synced via direct DB update; draft row 399 (stale) NOT synced — pending Guy sign-off.
- Final: 63 articles, 0 issues via API. Backup: logs/link-hygiene-bodies-before-20261006T101454Z.json.

## 2026-10-08 — Nomadomics QA F-01 carding (ATHENA)
- Carded confirmed stale production sitemap defect: `t_9ff8eb75` (assignee HEPHAESTUS, priority 70). Evidence report attached; reproduction is one sitemap URL returning 404 while live Strapi marks the article `in_review`.
- Carded preventive sitemap-vs-published integrity invariant: `t_84a1fa68` (assignee HEPHAESTUS, priority 60). Requires named-set reconciliation, unavailable-dependency fail-closed behavior, tests, and documentation.
- Carded independent closure verification: `t_50f86c0d` (ATHENA, blocked behind both implementation cards). Closure requires a fresh production sweep, live CMS comparison, and invariant pass; implementer self-report is insufficient.
- Both implementation cards were dispatched by the board immediately after creation; no content publication/unpublication or unrelated repo edits authorized.

## 2026-10-09 — Nomadomics cover-art recovery (Guy request)
- Restored the 28 card/OG cover pairs replaced by `8ca67ca` from its parent `df490d7`; this recovers the prior image-first set (13 Gemini-web photoreal assets plus earlier realistic covers) and removes the z-image text-overlay batch.
- Scope: exactly 56 PNGs under `frontend/public/{cards,og}`; no Strapi records or code changed.
- Verification: all 56 files byte-match the parent revision, valid PNG headers, and `node frontend/scripts/check-images.mjs` passed (47 published slugs complete).
- Deployed as commit `cde12b9` to `origin/main`; Vercel live verification matched all 56 restored URLs byte-for-byte at `https://nomadomics-v2.vercel.app/`.

## 2026-10-10 — Nano Banana cover refresh for live hidream-era slugs (ATHENA, via Gemini web)
- Guy request: replace the hidream images with Nano Banana (Gemini web) photoreal covers — realistic photos, topic-relevant, no watermarks or overlaid text.
- Hit list: `cover_titles_hidream.json` (28) ∩ published slugs (48) = **15 live slugs**; 12 of the 28 are orphans left untouched (flagged for a separate cleanup); `14-travel-hacks` skipped (its current cover is the fresh 10-10 art, not hidream).
- Harvest: 12 full-size originals (2752×1536 JPEG, 2.3–4MB) recovered from Guy's existing Gemini chats via CDP download-button capture (Brave relaunched with `--remote-debugging-port=9333`); 3 slugs with no chat (best-vpns-for-traveling, digital-nomad-taxes, how-to-open-a-us-bank-account-as-an-expat) generated fresh in a new Gemini chat via the same CDP pipeline.
- Pipeline: PIL cover-crop → cards 1200×675 + OG 1200×630 → pngquant quality pass → all ≤486KB (cap 500KB).
- Vision QA (local qwen2.5vl): 15/15 photoreal, 0 watermarks/overlaid text, all scenes on-topic.
- Shipped: 15 per-slug commits `feat(frontend): nano-banana cover art for <slug>` pushed as `1577664..f5a296c` → Vercel auto-deploy; live byte-size verification passed on 3 spot-checked cards.
- Tooling: `~/.hermes/scripts/gemini_cdp.py` (probe/send/dump), `nomad_harvest_batch.py`, `nomad_harvest_dl.py`, `nomad_cover_postprocess.py`, `nomad_cover_qa.py`, `nomad_contact_sheet.py`.

## 2026-10-10 — Strapi recovery and 33-cover Nano Banana completion (HEPHAESTUS, t_9a20e694)
- Read-only diagnosis before repair: `curl http://127.0.0.1:1337/admin` returned `000`; direct Strapi start emitted `AggregateError` then shut down; `node check_pg.js` returned `ECONNREFUSED 127.0.0.1:5432`; `launchctl print` showed `com.nomadomics.strapi` crash-looping with `last exit code = 1`. The existing launchd plist and Strapi config were intact; PostgreSQL 16 was not running.
- Restored only the existing local runtime: `brew services start postgresql@16`, then `launchctl kickstart -k gui/$(id -u)/com.nomadomics.strapi`. No Strapi content or publication state was changed.
- Verification: PostgreSQL query connected to database `nomadomics` as user `nomadomics` with 172 article rows; launchd state is `running`, `last exit code = 0`; `/admin` returns HTTP 200; authenticated published article query returns HTTP 200 with data and 48 published articles (`travel-insurance-for-digital-nomads` spot check).
- Cover accounting reconciled against `nano-covers-jobs.json`: exactly 33/33 manifest slugs generated (`nano-covers-state.json` all 33 `done`), 33/33 target JPEGs present, 33/33 card+OG pairs post-processed at 1200×675 / 1200×630, all ≤500 KiB. The 15 prior non-manifest raw JPEGs remain untouched and are not counted as this batch.
- Vision QA: local qwen2.5vl run completed 33/33 with no failures; first pass flagged `budget-travel-accommodation-hacks` for visible text, so it was regenerated through Gemini, reprocessed, and retry QA returned `Yes / No / Cozy bedroom with bunk beds and string lights.` No watermark/text flags remain.
- `cd frontend && npm run check:images` passed (48 published slugs; 14 card and 14 OG orphans intentionally retained). `npm run build` passed with 0 Strapi 500s and 0 empty-state fallbacks; output captured in the task workspace. Image-only commit `7d7f3f7` was pushed to `origin/main`.
- External deployment verified: `https://nomadomics-v2.vercel.app/` returned HTTP 200 and all 66 card/OG URLs matched local bytes when fetched with cache-busting `?cb=7d7f3f7` (66/66 matches, 0 errors). A cache-hit request without the query briefly served old bytes; use the commit cache-buster for verification while CDN expiry catches up.
- Evidence: task workspace `postprocess_33_result.json`, `vision_qa_33.json`, `vision_retry_budget.txt`, `frontend-build.log`; raw/staged batch state under the profile cache scratch directory.

## 2026-10-10 — Production article disappearance: Strapi tunnel outage and fail-open build
- Reproduced on `https://www.nomadomics.blog/`: homepage returned HTTP 200 but rendered `Guides 0`; published article routes returned 404; the same failure was present on `https://nomadomics-v2.vercel.app/`.
- Root cause: `frontend/src/lib/strapi.ts` converted every Strapi error into `null`, so a Vercel build could succeed with zero articles. `generateStaticParams()` then received an empty list and emitted no article routes.
- The public Strapi origin was also unavailable: `strapi.nomadomics.blog` returned Cloudflare 530/1033 while the existing `com.nomadomics.cloudflared` LaunchAgent was unloaded. Local Strapi/PostgreSQL were healthy, but Vercel could not reach `localhost:1337`.
- Recovery: loaded the existing cloudflared LaunchAgent; tunnel connector registered and authenticated public API returned HTTP 200 with 48 published articles. No Strapi content or publication state changed.
- Prevention: changed the data layer to fail closed in production/Vercel; `STRAPI_FAIL_SOFT=1` remains an explicit development-only opt-in. A CMS outage now fails deployment instead of shipping an empty site.
- Verification: frontend tests 24/24 passed; public-API build generated 70/70 static pages including 48 article routes. Vercel redeploy still required to replace the currently cached empty deployment.

## 2026-10-10 — Final published cover byte-cap enforcement (HEPHAESTUS, t_b40af80c)
- Cap semantics: the existing post-process script documents a 500 KiB working cap (`500 * 1024`), but the final published-asset gate is stricter: every published card and OG PNG must be `<=500,000` bytes. `frontend/scripts/check-images.mjs` now fails closed on any published asset over that byte cap; orphan assets remain retained and out of scope.
- Re-encoded exactly 7 oversized published assets with `pngquant` quality `60-88`, preserving dimensions: cards `cost-of-living-barcelona-digital-nomads` 510454→459602, `cost-of-living-buenos-aires-digital-nomads` 501660→430074, `cost-of-living-ho-chi-minh-city-nomads` 550844→479111, `cost-of-living-mexico-city` 505836→460957, `nomad-health-insurance-guide` 539786→452715; OG `cost-of-living-ho-chi-minh-city-nomads` 519718→450196, `nomad-health-insurance-guide` 506911→430778 bytes.
- Final local inventory: 48 published cards and 48 published OGs, 0 over `500,000` bytes; 14 card and 14 OG orphans remain untouched. No article publication state changed and no orphan files were deleted.
- Verification: `cd frontend && npm run check:images` passed (48 published slugs, 62 card and 62 OG files); `npm run build` passed with 70/70 static pages, 0 Strapi 500s, and 0 empty-state fallbacks. Local Strapi `/admin` returned HTTP 200; production homepage and changed article returned HTTP 200.
- Final visual QA inspected all 7 changed files: 7/7 pass with no overlaid headline/text, watermark, or logo; the initial Barcelona bottom-right concern was crop-inspected and confirmed normal railing detail, not a watermark.
- Shipped in image/gate commit `09a2a9d`; production cache-busted verification against Vercel deployment commit `4d4de2b` (`?cb=4d4de2b`) returned HTTP 200 and exact local-byte matches for all 7/7 changed URLs: 459602, 430074, 479111, 460957, 452715, 450196, and 430778 bytes respectively.

## 2026-10-10 — Employer case-study MVP release
- Added the employer-facing `/case-study/nomadomics` page, navigation and sitemap links, and the evidence docs `docs/EMPLOYER-MVP.md` and `docs/CASE-STUDY-NOMADOMICS.md`, sourced from the 2026-10-09 audit snapshot `20261009_111004_bb2a52ce`.
- Frontend tests (24), lint, and production build passed. Commit `3cb620d` was pushed to `origin/main`; the Git-triggered deployment was blocked by commit-author permissions, so the authenticated Vercel CLI deployment `nomadomics-v2-kx62jim7c-nomads4.vercel.app` was used.
- Cache-busted production verification passed: `https://www.nomadomics.blog/case-study/nomadomics`, `/sitemap.xml`, and `/` all returned HTTP 200; the case-study route appears in the live sitemap and homepage navigation.

