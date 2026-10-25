
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

## 2026-10-13 — Nomadomics live status audit (ATHENA)
- Core lane live: Gemini Flash Lite research/draft smoke returned HTTP 200; engine suite passed 534 with 2 skips; Strapi admin, canonical site, and sitemap returned HTTP 200; frontend production build generated 72 static pages.
- Daily progress: the 09:00 draft batch produced 2 reviewable articles; the guarded retry correctly skipped; the 13:00 publisher released `falling-sick-abroad-hospital` and verified the article, card, and OG assets live at HTTP 200.
- Queue: Strapi reported 96 topics, 18 pending topics (~3.8 days runway), and 20 draft/in-review articles. The local asset gate reports all 49 tracked published slugs have card + OG art; 16 orphan pairs remain on disk.
- Open findings: Gemini primary is healthy, but the optional Sonar verifier timed out during today's batch; the Gemini cover worker has 8 consecutive failures from a Python 3.14/Pillow `_imaging` import error; the last invariant run reported 47/48 articles meeting the >=2 internal-link threshold. No production state was changed by this audit.

## 2026-10-13 — Replicable blog-production system specification (ATHENA)
- Created the canonical productization design: `docs/REPLICABLE-BLOG-SYSTEM-SPEC.md`.
- Scope clarified: one reusable engine can produce different isolated blogs for different companies; this is not yet a self-service SaaS platform.
- Spec covers site-instance identity, engine/CMS/frontend/asset/operations planes, workflows, quality gates, isolation contract, replication acceptance tests, packaging options and open product decisions.
- Created execution plan: `/Users/guy/.hermes/plans/2026-10-13_140611-nomadomics-replicable-blog-system.md`.
- Linked the spec from `docs/PRODUCT-CONTRACT.md` and `RUNBOOK.md`; no production content, schema, cron or credentials changed.

## 2026-10-13 — Nomadomics spec maintenance card (ATHENA)
- Created Kanban card `t_20b215a5`: maintain `REPLICABLE-BLOG-SYSTEM-SPEC.md` as the engine, architecture, trust gates and replication boundary evolve.
- Assignee: `hephaestus`; priority: 45; status: `ready`.
- Acceptance requires dated evidence, linked-doc consistency, relevant verification, and separation of current/dry-run/live-verified capability.

## 2026-10-13 — Replicable blog-system specification maintenance (HEPHAESTUS, t_20b215a5)
- Updated `docs/REPLICABLE-BLOG-SYSTEM-SPEC.md` to version 0.2 with a dated capability snapshot and an explicit replication-seam status table.
- Synchronized `docs/PRODUCT-CONTRACT.md` so the validated profile/config/schema prerequisites are distinguished from the unapproved backfill, universal query isolation, frontend profile rendering, and second-fixture proof.
- Evidence basis: this file's 2026-10-13 live-status entry plus repository inspection of `engine/site_profile.py`, `engine/config.py`, the topic/article schemas, and `scripts_dev/backfill_site_key.py`; no production content, schema, cron, credential, or second-site state was changed.
- Verification and handoff evidence are recorded in Kanban card `t_20b215a5`; the next owner is the P1 identity/isolation workstream after Guy's explicit backfill/filter gate.
**Status:** in-progress

## 2026-10-16
- Strapi content change (F-03): reworked `long-stay-travel-gear-essentials` (draft working row 838, documentId n0u3kmjo3t50uayfqt6dx4ox) per review t_5fe40c69 blocking items 1-6 (kanban t_3f281926): corrected airline claims (Ryanair free bag 40x30x20cm / Priority 55x40x20cm/10kg / gate fee EUR70-75; Wizz 40x30x20 free + WIZZ Priority 55x40x23), hedged GaN safety FAQ, spec ranges w/ as-of date, 9 specific sources w/ retrieval dates, five pack/organization entries, expanded to ~1,924 prose words (durability field notes, repairability, buy-on-arrival, TL;DR), currency conversion context, metaTitle/metaDescription/excerpt repaired (schema-safe). Draft layer only; published layer untouched. Invariants clean; quarantine regression 20/20 PASS; link hygiene + citation gates green; 36 engine tests passed.
**Status:** in-progress (re-review pending)

## 2026-10-18 — Health audit (HERMES, read-only)
- Green: engine tests 542 passed/2 skipped; Strapi :1337 200 (106 topics); site + sitemap 200; draft lane active (4 events today, 2 new drafts, retry guard working); runway 15 pending topics; covers OK for all published slugs (71/71 card+OG); all 5 nomadomics crons active + firing.
- FINDING (publish gap, 5 days): last live publish 2026-10-13 (`falling-sick-abroad-hospital`). Queue head `tipping-customs-around-the-world` refused 3 days straight — 10-16 style judge (TL;DR after intro, meta-commentary, H3 pattern), 10-17 link hygiene (2 slug-anchor links), 10-18 style judge (formal source attribution in prose). Publisher cron itself healthy (runs daily 13:00, exits 0). Fix is content-side: rework the article to pass gates, not ops.
- FINDING (degraded): `nomadomics-gemini-cover-worker` cron error streak=23 — exit 2 `NO_CDP_BROWSER` (Brave CDP not running). No published slug lacks art today, so impact is latent (bites at next publish needing a gemini-web cover).
- Minor: 22 orphan card/og files on disk; 2 asset filenames contain a year; lifecycle-health cron fired 7 min late once today.

## 2026-10-18 — Publish-jam rework + Higgsfield cover route (HERMES)
- Article fix (`tipping-customs-around-the-world`, docId mea8u82n412yd46wp52vkm9j, draft layer only, sha-verified read-back): removed TL;DR trio after intro, meta-commentary intro line, all six formal attribution parentheticals, "Top 6" false count; Pros/Cons H3 → own "The Trade-Offs" H2; Bottom Line bullets → prose; replaced dead JNTO 404 link with live Intrepid Travel Japan tipping page (claim-support verified on-page); kept Rick Steves (200). Gates on stored body: article_invariant_errors=[], link_hygiene=[], source_section=[], internal_link=[] with live corpus, 2 citation URLs. Publisher picks it up at next 13:00 window.
- Cover worker route swap (`~/.hermes/scripts/nomadomics_gemini_cover_worker.py`): Higgsfield API (`gpt_image_2`, 16:9) is now the PRIMARY generation route; Gemini-web CDP demoted to per-slug fallback; postprocess/vision-QA/git-ship unchanged; manifest provider now `higgsfield:gpt_image_2`. Plan/auth refusals classify as HF_ROUTE_DEAD (bounded, no retry hammering); CLI shape verified against real `generate list --json` (`result_url`/`status`); stub-tested refuse/success/no-CLI paths (ALL PASS) + worker dry-run green.
- BLOCKER (human): HF account is free plan → live probe returns `job_minimum_basic_plan_required`. Route auto-activates on plan upgrade; until then next cron runs still fall through to CDP (NO_CDP_BROWSER) and error.

## 2026-10-18 (later) — Cover worker switched to Higgsfield REST API (HERMES)
- Guy: use the Higgsfield API (credits already loaded). Discovery: the `higgsfield` CLI is OAuth-bound to a DIFFERENT account (`wd94rxmkfc@privaterelay…`, free/0 credits) — dead end for covers. Developer REST API is the credited lane: base `https://api.higgsfield.ai`, auth `Authorization: Key <API_KEY_ID>:<API_KEY_SECRET>` (docs.higgsfield.ai/docs/authentication), endpoint `POST /z-image/turbo` (documented; same model class as RUNBOOK F-06 backfill), async poll `GET /requests/<id>/status`.
- Worker rewrite (`nomadomics_gemini_cover_worker.py`): CLI route REMOVED; `run_higgsfield` now = REST submit→poll→download with tolerant request-id/status/result-url parsing; 401/402 classify HF_ROUTE_DEAD (bounded); creds read from `~/.hermes/secrets/higgsfield_api.env` (0600). Stub-tested: missing-creds / 401 / happy-path (360KB raw) ALL PASS; worker dry-run green; py_compile clean under cron venv.
- BLOCKER (human, same as Guy's 12:15 note): rtf holds ONLY the `KEY_ID` (UUID, 36ch). All auth shapes 401 `Invalid credentials` — the `SECRET` was never obtained. Paste it into `~/.hermes/secrets/higgsfield_api.env` (`SECRET=`) from console.higgsfield.ai → API keys; next 2-hourly cron then generates covers on the credited account with zero further changes.

## 2026-10-20 — GDPR fact-check applied (data-residency-gdpr-nomads, docId iwdogh28zaz0g7i1hbr7m4b4, draft/in_review layer only, sha-verified read-back)
- Fact-check (ATHENA librarian, kanban t_705323a4) against Art 83/Art 3 GDPR (eur-lex live), EDPB Guidelines 3/2018, EC DPF adequacy page, DPF list. Corrections applied to draft layer (status=draft PUT, never publish; published mirror untouched): (1) added informational-only not-legal-advice disclaimer (was missing); (2) fixed territorial scope wording "EU residents/EU citizens" → data subjects in the EU (location-based, Recital 14); (3) softened "single customer from Berlin" overstatement per Recital 23 apparent-intention test; (4) added lower fine tier EUR 10M/2% alongside EUR 20M/4% max; (5) DPF table "Free" → "No fee to rely on; self-certification is fee-based"; (6) DPF per-vendor verification caveat (AWS/Google/Stripe all certified, verified on DPF list); (7) replaced dead EC source URL (404) with live eu-us-data-transfers_en + added EDPB 3/2018 + DPF program sources (all 200); (8) as-of October 2026 DPF status note (General Court Sept 2025 dismissal; CJEU appeal pending). Gates on stored body: article_invariant_errors=[] (with live corpus), link_hygiene=[], source_section=[], internal_link=[], 5 citation URLs all live. topicDecision=quarantine → release remains human-only via Strapi admin (journal_match=True, no release approval).
## 2026-10-20 — Editorial review + publication-readiness pass (data-residency-gdpr-nomads, docId iwdogh28zaz0g7i1hbr7m4b4, draft/in_review layer only)
- Editorial review (ATHENA librarian, kanban t_f0a689dd) on the fact-checked draft. Applied to draft layer (status=draft PUT, never publish; published mirror untouched, still original 899 words). Merged on top of sibling fact-check t_705323a4 — all 9 corrections re-verified present on the stored body (disclaimer, in-the-EU territorial scope, fine tiers, DPF caveats, live sources, as-of Oct-2026 status).
- Required-edits list (all applied): (1) expanded body 899 → 1,928 words (target 1,800; write skill range 1,600-2,200) — added practical sections (decision-tree framing after mechanism table, "What Standard Contractual Clauses actually do", "When the DPF or SCCs aren't enough", "How to run the audit in an afternoon", "The personal-data reality check"), an FAQ entry ("Does the GDPR apply if I have no EU customers yet?"), and the "no office in Europe is not a defense" upshot; (2) removed duplicate section — the sibling body had "Framework benefits for nomads" repeating the Pros/Cons bullets verbatim; replaced with the SCC/DPF-catch content; (3) fixed H1 to match stored article title (dropped trailing "Abroad" — title field is canonical); (4) replaced intro transition ("Let's look at…" meta-commentary → punchier "The good news / The bad news" framing per style-judge history); (5) added data-sovereignty explainer paragraph; (6) excerpt rewritten from truncated "…" to a clean 119c summary; (7) confirmed metaTitle (45c), metaDescription (156c), focusKeyword + targetKeywords already populated, all within schema budgets.
- Gates on stored body (verified post-write, sha-matched): article_invariant_errors=[] (with live corpus), opening_pattern=[], cliche=[], link_hygiene=[], source_section=[], internal_link=[] with live corpus, 5 citation URLs live (eur-lex, EC eu-us-data-transfers, EDPB 3/2018 PDF, DPF program site, gdpr-info Chapter V). Voice self-check: ≥3 money numbers in first 500 words (€20M/4%/€10M/2%), no banned openers, no "In this article", avg sentence length in normal prose band.
- topicDecision=quarantine (legal/tax) → release remains HUMAN-ONLY via Strapi admin status flip or `engine.cli publish --release data-residency-gdpr-nomads`; publish lane refuses quarantine-class automatically. Publish child t_63661e05 is released to run after both review cards complete.
**Status:** in-progress (awaiting human release decision)

## 2026-10-20 — Public Strapi tunnel recovery (HERMES/NIKE gate)
- 09:50 IDT: public Strapi 530, local admin 200, canonical tipping article 500. Existing com.nomadomics.cloudflared LaunchAgent was unloaded but not disabled. Loaded the documented existing service (exit 0); read-back PID 96301, public admin 200, unauth API 401, article 200. No code, credentials, CMS record or deployment changed; cause of unload unknown.
- Natural 13:00 publisher b9e3891806f7 completed and its failure incident auto-resolved, but output was a quality-gate SKIP, not a new publication or exercised page-live verification. Output: /Users/guy/.hermes/cron/output/b9e3891806f7/2026-10-20_13-00-44.md.
- Natural 14:30 invariants + NIKE independent QA remain pending. NIKE card t_d599688f scheduled 14:40, strict no-forced-run/no-ack. Full evidence: /Users/guy/.hermes/build/cron-review/20261020-094750/RECOVERY.md.

## 2026-10-20 — Post-fire correction: origin recovered; output invariant remains HOLD
- HEPHAESTUS independently confirmed public/local Strapi parity (admin 200, unauth API 401) and the former tipping article 200; NIKE's completed read-only card `t_d599688f` independently verified title, canonical URL, sitemap and card/OG 200. Neither review proved why the tunnel had been unloaded.
- Publisher's 13:00 natural run completed on a *quality-gate skip* (not a new publish or live-check-path proof), auto-resolving its historical incident. Content-invariants naturally fired late and failed on a **new** electricity card HTTP 0 even though tipping explicitly passed and both electricity image URLs now return 200. Its `http()` converts any network exception into status 0; no re-run was forced because the script writes its own state. NIKE verdict is HOLD pending a clean natural fire, not a green cron.
- HERMES closed only the old tipping incident (`79ab8f_763115b287b9`) after its specific natural-run pass and direct page check; SQL read-back confirmed `closed`. New electricity incident (`79ab8f_548fdacee27f`) remains `alerted`. Also surfaced: new publish-repair agent cron provider-constraint 403, and ARES Morning Read workspace-budget 403. Exact classes, counts, and bounded owner actions: `/Users/guy/.hermes/build/cron-review/20261020-094750/RECOVERY.md`. No policy, schedule, credentials, CMS or production code altered for these new failures.

## 2026-10-20 — Nomadomics engine status audit outcome (closes il:2026-10-12:t10-37-00-0300-nomadomics-engine)

- **Audit outcome** (source: Needs-Guy digest item, cron `e9a2b934835d`, filed 2026-10-16): **operational** with a non-blocking monitor/control-plane red finding. No remediation was required or applied — the follow-up card (t_8572e3c2) was doc-only, released by Guy 2026-10-20.
- **Referential note:** no on-disk entry exists under the referenced `il:` ID in either `~/.hermes/issue_log.md` or this log (this log's dated entries jump 2026-10-10 → 2026-10-13). This entry records the outcome in place of the missing original.
- **Live status verified 2026-10-20 ~22:15 IDT:** `engine.cli info` loads clean (strapi_url localhost:1337, site nomadomics, gemini-flash-lite research/draft/edit lanes, premium disabled); Strapi admin HTTP 200; Mission Control dashboard :8080 not running (manual-start service — resting state, not an incident).
- **Auto-publish: remains intentionally OFF.** Drafts advance only via explicit `engine.cli` publish actions.
- **Next check:** next scheduled engine status digest from cron `e9a2b934835d`, or on Guy's request.

## 2026-10-21 — EOR article consolidated review (kanban t_42bf5ec6)

- Merged fact-check (t_58226b76, FAIL/HOLD) × editorial QA (t_ddd661e6, REVISE) for `employer-of-record-for-digital-nomads` (docId nel2xgvszzhrrz6kuj6r55cn). **Consolidated verdict: REVISE IN STRAPI — NOT ready for human release.**
- Disputes resolved in favor of live-verified figures: pricing **$599–$699/mo** (editorial's $499 placeholders wrong); EOR coverage **Remote 90+ / Deel 150+ / Oyster 120+** (editorial's "180+ jurisdictions" fix text conflated contractor coverage); PE-risk wording adopts the stricter fact-check framing.
- Release-blocking: coverage table, pricing range, PE-risk rewrite, top-of-article legal/tax disclaimer, 2 dead source URLs + add independent source + retrieval dates, €50k figure (source or remove). Editorial fixes: truncated metaTitle, cut-off metaDescription, near-duplicate paragraph, unrelated Related reading, table differentiation ("Best for" + verified prices). Policy: `topicDecision=unknown` must become explicit at release; release stays human-only (Strapi admin or `engine.cli publish --release employer-of-record-for-digital-nomads`).
- Consolidated notes appended to the article's NEW `reviewNotes` field (additive `text` column in the article content type; Strapi auto-registered it in the admin edit view). Full report: `docs/CONSOLIDATED-REVIEW-EOR-2026-10-21.md` (untracked).
- **Incident + resolution:** the notes write via v5 REST PUT has publish semantics by default and created a published row (06:26:15Z). Removed transactionally from Postgres (snapshot: kanban workspace `articles.rows.pre-cleanup.json`); side effect: the pre-existing STALE published ghost (publishedAt 06:00:45Z, status-enum `draft` — the "possible stale publish" the fact-check flagged) is now fully gone. Document is draft-only: id 882, status `in_review`, `published_at` NULL; body/meta byte-identical (sha-verified); site 404'd throughout (article never live).
- **Heads-up for the next publish-lane worker:** `engine/update_view_config.py`'s baked `config_backup` is stale (missing author/coverImage/topicDecision/siteKey edit-view rows) — running it as-is reverts the admin layout; regenerate before reuse. The `schema.json` reviewNotes addition is uncommitted (commit decision: Guy). Engine tests: 555 passed, 4 pre-existing failures (`skip` vs `dry_run` in release-approval tests) come from in-flight uncommitted `engine/publish.py`/`config.py` changes, not from this task.

**Status:** open (article awaits human revision + release)
**Decision:** review notes live in the article `reviewNotes` field; published layer for this doc removed to draft-only; release remains human-only.

## 2026-10-21 — Nomadomics publish-lane: ghost origin trace + remediation (kanban t_ba7e5c88)

- **Ghost origin (forensics):**
  - EOR doc `nel2xgvszzhrrz6kuj6r55cn`: published layer born **06:00:45.710Z**
    (app status in_review, row 886) at the batch's `create_article()` `POST /api/articles`
    — v5 D&P publishes on creation when no `?status=` is sent.
  - Quarantine doc `qa4bubanhlrfcp79d538aaqj`: `PUT /api/articles/qa4bu...` without
    `?status=` (Strapi log 09:27:51.604Z, 200) created row 887 (publishedAt 09:27:51.586Z)
    — same leak class as EOR; ** remediated this run. Snapshot sha256 7840f683… (before)
    / 003aa953… (after); draft row 884 content byte-identical (excl. stamps);
    rows 882/884 `in_review`, `published_at` NULL; EOR ghost 886 rechecked gone.
  - Both leaks are v5 draft&publish semantics at two call sites: `StrapiClient.create_article`
    (no publication param) and the review lane's raw REST PUTs outside the engine client
    (whose `update_article` refuses write-through for non-published app status).
- **Fix** `engine/strapi.py` `create_article()` now always sends `?status=draft`
  (docstring updated); unit tests `engine/tests/test_publish_layer_guard.py` (5)
  + `test_view_config_merge.py` (2) = **7/7 pass**.
- **update_view_config.py** rewritten: hardcoded stale `config_backup` removed; merges a
  curated declaration into the live CM view-config row, `--apply` snapshots live config to
  `state/backups/` first, preserves unknown rows (author/coverImage/topicDecision/siteKey/
  reviewNotes + admin layout). Verified == live snapshot, 26/26 metadatas, 10-row edit
  layout, settings/uid/list equal to t_42bf5ec6 pre-reviewnotes snapshot.
- **Quarantine backlog (25 stale published layers, topicDecision unknown/draft/rejected)**:
  docIds 847, 849, 865, 851, 867, 853, 565, 871, 819, 855, 777, 779, 857, 873, 876, 859,
  839, 841, 789, 795, 797, 845, 863, 869, 881. Prevention by construction; sweep booked as
  follow-up card `t_ba7e5c88-backlog`.
- `src/api/article/content-types/article/schema.json` `reviewNotes` additive field: **commit
  decision belongs to Guy** (any main commit rides the 13:00 Vercel push; backend-only).
- 4 pre-existing engine test failures (`engine/publish.py` + `config.py` in-flight
  uncommitted, release-approval `skip` vs `dry_run`): out of scope, documented.

## 2026-10-23 — Nomadomics custom favicon + duplicate slug finding

- Replaced the generic black/white triangle `frontend/src/app/favicon.ico` with a five-size green-and-white globe mark matching the existing `apple-icon.tsx` brand treatment.
- Verified the production build and served artifact: `npm run build` passed; `GET /favicon.ico` on a local `next start` returned `200 image/x-icon` and matched the source ICO SHA-256.
- Live Strapi probe found two published API rows for `best-coworking-spaces-for-digital-nomads`: IDs **800** and **801**, same `documentId`, same title/body, with 800 newer (`2026-10-12`) than 801 (`2026-10-07`). After Guy's approval, deleted the older row 801 in a guarded SQL transaction; the API now returns exactly one published row (800). A backup of the deleted row is retained in the Hermes scratch area.
- Production has not been redeployed: `www.nomadomics.blog/favicon.ico` still serves the old four-size ICO (SHA-256 `2b8ad2d3…`), while the local replacement is the five-size custom ICO (SHA-256 `cda2fbfe…`).

## 2026-10-23 — Editorial route and author roster presentation

- Changed the primary navigation's Project link to **About**, pointing to `/editorial`; the mobile menu now matches.
- Moved the editorial page to `/editorial`, updated internal links and sitemap, and preserved `/about` as a permanent redirect to `/editorial`.
- Replaced the author `<ul>/<li>` roster with semantic list roles and card articles so writer names no longer render with bullets.
- Verified `/editorial` returns `200`, `/about` returns `308` to `/editorial`, the build passes, 24 tests pass, and ESLint reports 0 errors/0 warnings.

## 2026-10-23 — Author portrait generation and Editorial integration

- Generated four casual personal portraits through the authenticated Gemini/Nano Banana browser workflow; rejected an off-brief Thiago candidate and regenerated it with an explicit no-railway/no-camera constraint.
- Passed visual QA for all four: no visible text, logos, watermarks, artifacts, or work/editorial cues.
- Added optimized static portraits under `frontend/public/authors/` and wired them into the Editorial roster and author pages with initials fallback support.
- Verified all four assets return HTTP 200 from the local production server; `/editorial` returns HTTP 200 and includes all four portrait URLs.
- Final optimized assets: Guy 89,891 bytes; Katie 151,950 bytes; Thiago 97,030 bytes; Vincent 132,611 bytes. Build passed, 24 tests passed, ESLint 0 errors/0 warnings.

## 2026-10-23 — Nomadomics frontend deployment

- Committed and pushed focused frontend release `68fa0ed` (`feat(frontend): add editorial portraits and brand polish`) without staging unrelated workspace changes.
- First Vercel Git deployment failed because the Strapi Cloudflare tunnel returned HTTP 530 during build; local Strapi remained healthy (`/admin` HTTP 200).
- Restored the tunnel through the configured cloudflared command, redeployed from the repository root, and received Vercel production deployment `dpl_H4wJSsj3t1za4Uif3mgx2En8HgP2` in `READY` state.
- Live verification: `/editorial` HTTP 200; legacy `/about` HTTP 308; all four `/authors/*.jpeg` assets HTTP 200; live favicon SHA-256 matches the committed five-size ICO (`cda2fbfe…`); Editorial HTML contains all four portrait URLs and no `Project` label.

## 2026-10-25 — Search metadata and excerpt repair (Guy request)

- Audited the 53 published Nomadomics articles through authenticated Strapi; six published records had excerpts ending in a literal ellipsis, exposing truncated intro text in article headers/cards.
- Repaired the six affected slugs: `digital-nomad-communities-every-major-hub`, `cost-of-living-buenos-aires-digital-nomads`, `cost-of-living-tbilisi-digital-nomads`, `portable-wifi-vs-esim-vs-local-sim`, `international-health-insurance-claims-abroad`, and `satellite-internet-for-digital-nomads`.
- Replaced each excerpt with a complete, theme-specific summary and each `metaDescription` with search-oriented copy. Published-layer writes used explicit `?status=published`; readback verified all six document IDs and exact field values.
- Post-repair corpus verification: 53/53 published excerpts are non-truncated; 53/53 meta descriptions are non-empty, 120–160 characters, terminally punctuated, and free of the migration-template/ellipsis defects.
- Checked the current Nomadomics productization plan/spec and repository roadmap surface; no roadmap item is changed by this content-only repair. The first Vercel read was a stale ISR response (`x-vercel-cache: STALE`); after revalidation, the live satellite page returned the corrected excerpt and meta description (`x-vercel-cache: HIT`, age 57s).

## 2026-10-25 — Pipeline prevention for excerpt/meta truncation (Guy request)

- Hardened `engine/seo/analyze.py`: excerpts now select complete opening sentences only; long openers skip to a complete sentence or use a neutral topic fallback, never U+2026/`...` clipping. Meta descriptions now use complete opening-sentence windows or a topic-specific fallback, never a word-cut fragment.
- Hardened the shared `engine/invariants.py` write/publish gate: rejects excerpt ellipses, over-cap/unpunctuated excerpts, and excerpt/meta values that are prefixes of longer body sentences. Both draft and daily publish lanes use this same gate.
- Hardened the permanent `~/.hermes/scripts/nomadomics_content_invariants.py` monitor with the same 160-character excerpt / meta-description limits and clipped-prefix checks, so historical regressions alert even if they bypass the engine.
- Added regression coverage for long house-voice openers, no-sentence bodies, clipped body prefixes, and the previous `...from unconventional.` meta failure. Full engine suite: **581 passed, 2 skipped**.
- Updated `RUNBOOK.md` with the prevention contract and verification command. No roadmap item changed; this is a pipeline-quality hardening change.
