# RUNBOOK — Strapi service + content engine (Nomadomics v2)

## Strapi runs as a persistent launchd service

Strapi is loaded as a macOS LaunchAgent so it auto-starts on boot and
auto-restarts if it crashes. No need to manually `npm run dev` anymore.

| Command | Action |
|---|---|
| `launchctl list \| grep nomadomics` | Is the service loaded? (PID + exit code) |
| `open http://localhost:1337/admin` | Open the admin panel |
| `launchctl unload ~/Library/LaunchAgents/com.nomadomics.strapi.plist` | Stop the service |
| `launchctl load ~/Library/LaunchAgents/com.nomadomics.strapi.plist` | Start the service |
| `tail -f ~/nomadomics-v2/logs/strapi-service.log` | Watch logs |
| `tail -f ~/nomadomics-v2/logs/strapi-service.err` | Watch errors |
| `curl -s -o /dev/null -w "%{http_code}" http://localhost:1337/admin` | Health check (expect 200) |

Config: `~/Library/LaunchAgents/com.nomadomics.strapi.plist`
Logs: `~/nomadomics-v2/logs/strapi-{service.log,service.err}`

## Content API tokens (rotated 2026-09-10)

Token plaintexts live only in `.env` (engine) and `frontend/.env.local` (frontend) — never in git. The frontend uses a dedicated **read-only** token (`frontend-read`); the engine uses `engine-write`. To rotate a token without the admin UI: generate `secrets.token_hex(64)` in Python, store `HMAC-SHA512(key=API_TOKEN_SALT, msg=<plaintext>)` as hex in `strapi_api_tokens.access_key` (`encrypted_key` may be NULL — it is unused because `ADMIN_ENCRYPTION_KEY` is not set), update the matching `.env` file, restart Strapi if its own env changed. The old `.env.strapi`-era credentials (DB password, salts, JWT secrets, original API tokens) were exposed in git history before commit `5a9eb13` and were fully rotated on 2026-09-10; Vercel's `STRAPI_API_TOKEN` (Production) was swapped and redeployed the same day.

## Mission Control dashboard security

Mission Control binds to `127.0.0.1:8080` by default and does not enable CORS. Read-only GET endpoints remain available locally; mutating POST endpoints require `DASHBOARD_ADMIN_TOKEN` via `Authorization: Bearer <token>` or `X-Dashboard-Token`. Set `DASHBOARD_HOST` only when a deliberately secured reverse proxy/container requires another bind address. Never expose the dashboard directly to the public internet.

## Content engine CLI

Engine venv: `~/nomadomics-v2/.venv` (Python 3.11). All commands from
`~/nomadomics-v2`. Use `env -u PYTHONPATH` first (a global PYTHONPATH leaks the
Hermes venv's site-packages and breaks engine imports).

```
env -u PYTHONPATH .venv/bin/python -m engine.cli info        # config (redacted)
env -u PYTHONPATH .venv/bin/python -m engine.cli next        # next pending topic
env -u PYTHONPATH .venv/bin/python -m engine.cli draft-one <slug>
env -u PYTHONPATH .venv/bin/python -m engine.cli run-batch [N]
env -u PYTHONPATH .venv/bin/python -m engine.cli drafts      # drafts in Strapi
```

Run tests:
```
cd ~/nomadomics-v2/engine && env -u PYTHONPATH ../.venv/bin/python -m pytest tests/ -q
```

## Draft vs published layer — article writes (t_60ad2c8e, 2026-09-22)

`api::article.article` has `draftAndPublish: true`, which means every article has TWO
rows in Postgres (`articles`, keyed by `document_id`; `published_at` NULL = draft).

- A `PUT /api/articles/<documentId>` **with no `?status=`** writes THROUGH to the
  **published layer** and re-stamps `publishedAt`. On 2026-09-22 that shipped an
  edited body to the live site (documentId `su1sx6rek6wnz7yfaayna7qh`) inside the
  frontend's 300s ISR window, with no human gate.
- `?status=draft` → draft layer only; `?status=published` → the publish step
  (it also re-syncs the draft layer).

Therefore `StrapiClient.update_article(...)` takes an explicit `status` and
**defaults to `"draft"`** — never publish by accident. Only two call sites pass
`status="published"`, and they ARE the publish steps: the auto-publish branch in
`pipeline_cli.draft_one` and `publish.publish_one`. Everything else (quarantine /
in_review flips, the `publish --release` topicDecision flip, dev scripts) passes
`"draft"`. `status=None` omits the param and is the historical dangerous
behaviour — don't use it to edit a draft.

**`publishedAt` is not restorable from a payload.** On v5 the document service
owns that column and ignores the value you send, so a timestamp mangled by an
accidental republish cannot be set back by including `publishedAt` in `fields`.
Change publish state only via `status="published"`.

Regression coverage: `engine/tests/test_article_write_layer.py`. The live test
writes to the local Strapi and is opt-in:

```
cd ~/nomadomics-v2/engine && env -u PYTHONPATH NOMADOMICS_STRAPI_LIVE_TEST=1 \
  ../.venv/bin/python -m pytest tests/test_article_write_layer.py -q
```

It creates its own fixture article (custom `status` enum stays `draft`, so the
frontend never serves it), publishes the fixture's own published layer, asserts a
default write leaves that layer byte-identical, then removes the fixture. The
`engine-write` token is least-privilege (find/findOne/create/update, **no
delete**), so cleanup drops the rows at the DB level via `psql` + the repo's
`DATABASE_*` values; without those the test skips instead of leaking rows.

## Gemini content pipeline (2026-08-29)

Research → draft → edit all run on **Gemini 2.5 Flash** (primary) via the
OpenAI-compatible endpoint, with OpenRouter `:free` models as fallback chain.
Key: `GEMINI_API_KEY` in the gitignored `.env` (never logged).

- Stage map: `engine/research/` → `engine/writer/` → `engine/editor/` → `engine/seo/analyze.py`
  (deterministic scorer incl. a **structure score**: tables/bullets/H3/pros-cons feed
  `seo_score`, so walls of prose score lower than structured drafts).
<!-- canon:volatile:start -->
- Publish gate (ratified E, 2026-09-23): auto-publish under invariants, veto in the daily digest.
  The engine publishes a non-sensitive article when policy confidence clears and the write-time
  invariants pass (non-empty excerpt and meta, yearless slug, at least two real citations).
  Guy can retract from the daily digest. Taxes/legal/medical/visas/banking stay quarantined.
  `publish_gate=auto-publish-under-invariants` · `veto=daily-digest` · cron_total is in
  `~/.hermes/docs/generated-canon.txt` (129 on 2026-09-23), not in this paragraph.
<!-- canon:volatile:end -->
- Structure contract lives in the writer + editor prompts (bullets under every H3,
  comparison tables, Pros/Cons, Bottom Line, FAQ) — output renders via the frontend's
  react-markdown GFM renderer.

## Daily batch cron (STAGED — NOT ARMED)

Command (when Guy approves):
```
cd ~/nomadomics-v2 && env -u PYTHONPATH .venv/bin/python -m engine.cli run-batch 2
```
Schedule: `0 9 * * 0-5` (09:00 Sun–Fri, Saturday off) → drafts land `in_review` +
Telegram notify. **Do not create while testing:** the gateway is running, so a created
cron fires immediately.

## Daily publish pipeline (ARMED 2026-09-14 — Guy sign-off)

One polished article/day auto-publishes with cover art.

- Cron job `b9e3891806f7` "nomadomics-daily-publish" in the **default profile**
  cron store (`~/.hermes/cron/jobs.json`), `no_agent`, deliver `telegram`.
- Schedule `0 13 * * *` local = **10:00 UTC daily** (Guy-approved 2026-09-14),
  one hour after the 09:00 draft batch.
- Entrypoint: `~/.hermes/scripts/nomadomics_daily_publish.sh` (repo-external;
  strips global PYTHONPATH, runs `engine.cli publish`, pushes the cover-art
  commit, formats the Telegram notice).
- Runner: `engine/publish.py` via `engine.cli publish` (`--dry-run`,
  `--skip-image`, `--no-commit`). Picks highest-confidence `in_review` article
  ≥ 75 → LLM polish (TL;DR, 2–3 internal links, meta caps; Gemini→:free chain,
  Cake Nano `z-ai/glm-5.3-flash` fallback) → Strapi `publishedAt=now` → Cake
  Nano HiDream 1200×630 cover → `frontend/public/{cards,og}/<slug>.png` →
  git commit + push → live URL verification.
- Idempotency/state: `engine/state/publish-pipeline.jsonl` (gitignored, like
  all of `engine/state/`) — max 1 publish per UTC day, never re-publishes a
  slug. No eligible article ⇒ skip notice, no publish.
- **Quarantine gate (2026-09-20):** the draft lane stamps each article's policy
  decision as `topicDecision` on the Strapi article. The publish lane REFUSES
  any article with `topicDecision=quarantine` — it is skipped (and hard-refused
  if ever selected by another path), so YMYL tax/legal content can no longer
  auto-publish at the 13:00 run. **Release is human-only:** (1) Guy flips
  status to `published` in Strapi admin, or (2) an operator runs
  `env -u PYTHONPATH .venv/bin/python -m engine.cli publish --release <slug>`
  (explicit approval: `topicDecision` quarantine → needs_review, plus a durable
  approval record in `engine/state/release-approvals.jsonl` — the article
  then competes in the normal in_review lane; the release command never
  publishes by itself). Legacy articles created before the field also gate on
  the draft journal (`engine/state/pipeline.jsonl`, joined by documentId) so
  quarantined tax/legal content is protected even without the server-side field.
- Cover integrity: `node frontend/scripts/check-images.mjs` (snapshot:
  `frontend/scripts/published-slugs.json` — the runner does NOT update it;
  refresh it when publishing outside the runner).
- ISR note: the runner's single publish update (body + meta together)
  triggers frontend revalidation. POST-publish meta-only edits via Strapi do
  NOT revalidate the page — flush with an empty-commit redeploy if you ever
  hot-fix meta after publish.
- Kill switch: `hermes --profile default cron pause b9e3891806f7` (resume with
  `cron resume`). Quarantine a bad article: set `status` back via Strapi admin.
- Audit copy (paused, disabled): job `426cd86169bc` in the hephaestus-profile
  cron store — the hephaestus gateway cannot fire (telegram token conflict
  with the default gateway); the default-profile job is the live one.

## Cover art — provider chain (2026-09-19)

`engine/publish.py` walks an ordered image chain and only gives up when every route
is unusable:

| # | Route | Model | Key env |
|---|---|---|---|
| 1 | `cake.nano-gpt.com` | `hidream` (preferred) | `HERMES_CUSTOM_CAKE_NANO_GPT_COM_API_KEY` |
| 2 | `api.cheaperinference.com` | `nano-banana-2` | `HERMES_CUSTOM_API_CHEAPERINFERENCE_COM_API_KEY` |

A non-retryable status (401/402/403/404) skips the hop immediately, so a locked or
capped key no longer ends cover generation. The run prints which route served the
image (`cover generated via <route>`); `publish-pipeline.jsonl` records
`cover: generated|failed|skipped`.

Incident this replaces: Cake hit its **weekly token cap** (`401 invalid session`).
Note `/api/v1/models` still answers 200 without a key — it is public, so it is NOT a
key check. Cover failure is non-fatal by design, so three consecutive posts published
with `cover: failed` and nothing retried them. Backfill a missing cover by calling
`publish.generate_cover(slug, title)` for that slug, then re-run the image gate and
commit the assets.

`frontend/scripts/published-slugs.json` is hand-maintained: refresh it to the live
published set whenever an article is published outside the runner, otherwise
`check-images` validates a stale universe (use `--live` to read Strapi instead).

## Kill switch (<60s)

- `launchctl unload ~/Library/LaunchAgents/com.nomadomics.strapi.plist` — halts Strapi.
- To quarantine a bad article: set `status` back to `draft` via Strapi admin or API
  (the engine token has `update` but NOT `delete` — by design, quarantine not destroy).
- Models are free-only (`:free`) until Guy flips `PREMIUM_MODEL_ENABLED` in `.env`.

## Cloudflare Tunnel — stable public API (strapi.nomadomics.blog)

Named tunnel `nomadomics-strapi` (id a7e47a22-0622-4c9d-9f99-0c1d8fbdab2a) exposes
local Strapi at https://strapi.nomadomics.blog. Runs as LaunchAgent
`com.nomadomics.cloudflared` (RunAtLoad + KeepAlive -> auto-start on boot, self-heals).

| Command | Action |
|---|---|
| `launchctl list \| grep cloudflared` | Tunnel running? (PID) |
| `launchctl unload ~/Library/LaunchAgents/com.nomadomics.cloudflared.plist` | Stop tunnel |
| `launchctl load ~/Library/LaunchAgents/com.nomadomics.cloudflared.plist` | Start tunnel |
| `tail -f logs/cloudflared.err` | Tunnel logs |
| `cloudflared tunnel info nomadomics-strapi` | Connection status |

Config: `~/.cloudflared/config.yml` · Credentials: `~/.cloudflared/*.json` (SECRET)
Migration note: on Hetzner cutover, install cloudflared on the VPS with the same
tunnel ID + ingress (`service: http://strapi:1337`), then remove the local LaunchAgent.
Public URL never changes; Vercel env untouched.

## Vercel frontend env contract

```
STRAPI_URL=https://strapi.nomadomics.blog   # server-side data fetch
STRAPI_API_TOKEN=<read-only token>          # NOT the engine token
NEXT_PUBLIC_SITE_URL=https://nomadomics.blog
NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION=       # GSC HTML tag token (empty locally, set on Vercel production)
```
DNS plan: apex + www -> Vercel · strapi.* -> Cloudflare tunnel (done 2026-08-25)

### Google Search Console verification (Guy-side, 2 min)

1. Open https://search.google.com/search-console and sign in with your Google account.
2. Click **Add property** → choose **URL prefix** → enter `https://nomadomics.blog`.
3. When prompted for verification method, choose **HTML tag**. Copy the `content` value of the meta tag (a long alphanumeric token).
4. In Vercel: Project → Settings → Environment Variables → add `NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION=<your token>`.
5. Redeploy to production (or let the next deploy pick up the new env var).
6. Back in GSC, click **Verify**. Once verified, submit `https://nomadomics.blog/sitemap.xml` under **Sitemaps**.
7. The `verification: { google: ... }` meta tag is already wired in `src/app/layout.tsx` — no code change needed.

## Hard rule: NO years in slugs (Guy, 2026-09-07)

Article slugs must never contain a year (`20\d{2}`). Titles and meta titles SHOULD
carry the current year (SEO best practice) — slugs must not. The engine enforces
this at article-creation time via `_yearless_slug()` (`engine/pipeline_cli.py`),
which strips `-for-YYYY`, `-in-YYYY`, leading `YYYY-`, and bare `-YYYY` tokens.
Tests: `engine/tests/test_yearless_slug.py`. Topic slugs in Strapi may contain
years (the rule applies when the ARTICLE is created).

Kill switch / rollback: none needed — the rule is deterministic and idempotent.

## 2026-10-05 — Nomadomics QA Phase 2 (F-01/F-03/F-06/F-07) — HEPHAESTUS

Gate A passed (NIKE relay, Guy authorized). Implementer lane: HEPHAESTUS.
ATHENA owns closure — she re-runs each VERIFY_COMMAND against the fixed system.

**F-01 (sitemap omitting cost-of-living-barcelona): SELF-HEALED — no fix applied.**
Reproduced the VERIFY_COMMAND fresh (cb=15516): sitemap now 56 <loc> WITH barcelona
(age 61s, new etag 6c22de36…), vs the finding's 54/absent at age 8936s. Stable across
independent fetches; the slug URL resolves HTTP 200; Strapi published total is now 44
(finding said 43 — one publish since). The stale ISR render regenerated on its own
once age passed the revalidate window. Falsification attempt: pushing the pending
deploy (see F-06) re-renders from cold anyway, so F-01 stays fixed mechanically.
NO code or config change made. Lesson recorded: a stale-ISR finding needs an
age-based re-check at implementation time — a CONFIRMED cache finding can expire.

**F-03 (budgeting-apps-for-digital-nomads, 0 internal links): FIXED via the backstop itself.**
Reproduced: 0 absolute / 0 relative links, live body 8,221 B. Proved the 1933489
write-path backstop covers this path by running the REAL ensure_internal_links()
(7/7 backstop tests green) on the REAL live body with the REAL 44-title corpus:
dry run produced exactly 2 links as a pure suffix ("## Related reading"), diff-identity
precondition enforced. Applied through the pipeline's own StrapiClient
update_article(status="published") — the documented explicit-publish API, chosen
over bare PUT because v5 write-through re-stamps publishedAt (t_60ad2c8e incident).
Server-side after: relative-targets=2, articles total unchanged at 62, single row
(no F-02 pair). publishedAt re-stamped 10-04T10:00Z -> 10-05T10:09Z (documented v5
behavior; disclosed, not hidden). Rollback snapshot: scratch/f03_body_rollback.md.
Applier: profiles/hephaestus/cache/scratch/fix_f03_internal_links.py.

**F-06 (barcelona cards/og 404): FIXED.** Generated both PNGs via the sanctioned
nomadomics_backfill_covers.py (cake-nano/z-image-turbo), 1200x630 (IHDR-verified),
headline gate PASSED (vision transcription exact: "Cost of Living in Barcelona for
Digital Nomads"). Committed surgically: 8e3c4b3, explicit paths only, none of the 21
dirty entries touched. Pushed 13eea78..8e3c4b3 -> Vercel deploy (this also ships the
previously unpushed backstop commit 1933489; frontend build content unchanged except
the two PNGs). Post-deploy asset checks: to be re-run by ATHENA at closure.

**F-07 (3 of 4 <img> lack width/height): REFUTED AS A DEFECT — outcome-level evidence.**
Reproduced the STRUCTURAL claim (1 of 4 has dimensions — the hero; 3 related-card
images emit none) but falsified the HARM claim with a real PerformanceObserver
layout-shift measurement on the live page (buffered observer, full load + scroll):
CLS = 0.0000, zero shift events. Mechanism: ArticleCard uses next/image fill inside
an aspect-[16/9] container — Next's own space-reserving pattern; width/height props
are INVALID API on fill images. No change made; recommend ATHENA reclassify F-07
from defect to advisory (structural observation, no measurable CLS harm).

**F-02: NOT TOUCHED (Guy resolved: intentional v4 draft/publish pairs).**
**F-05 (cards/ bimodality): NOT TOUCHED — goal-prompt §8 bars it from this exercise
(separate Tier-2 finding).**

Pre-batch gate: tag qa-pre-batch1 pinned at 1933489 (rollback reference).
Constraints honored: no scripts_dev/ execution, no -a/stash/restore, dirty tree
untouched (still 21 entries), no new credentials, engine venv + env -u PYTHONPATH.

## 2026-10-05 — QA F-06 ROOT CAUSE: slug snapshot ledgered art-less slugs — HEPHAESTUS

**The defect chain (reconstructed from evidence, not inferred):**
1. 10-04 13:16 — `cost-of-living-barcelona-digital-nomads` published by the 13:00 cron
   lane (`publish_one`). `generate_cover()` FAILED non-fatally (both PNGs absent).
2. Same run — `write_slug_snapshot()` ledgered the slug anyway: it was written from
   the LIVE STRAPI SET with no existence check. The commit `13eea78`-lineage
   ("feat(frontend): cover art for …") carries snapshot updates from this lane.
3. Every later backfill sweep (`nomadomics_backfill_covers.py`) read the ledger as
   "already covered" and skipped the slug → 404 art persisted ~3 days.
4. The gates that existed checked OTHER directions: `check-images.mjs` compares
   SNAPSHOT → disk (fails on ghost slugs but nobody invoked it in the cron lane),
   `test_slug_snapshot.py` pinned write-only-when-changed (no file semantics at all).

**The fix (commit ccb7481):** `write_slug_snapshot()` now refuses any slug whose
`frontend/public/cards/<s>.png` AND `frontend/public/og/<s>.png` are not BOTH on
disk. Ghosts print a loud stderr pointer to the backfill tool and are omitted;
an all-ghost set leaves the snapshot untouched. A ledger entry with no file is
no longer representable.

**Red→green:** 2 new tests failed on pre-fix code exactly as the defect predicts
(`test_refuses_slug_with_no_art_on_disk`, `test_refuses_slug_with_only_one_of_two_files`);
3 existing tests updated to the new contract (fixtures now create real art files —
fake slugs are now, correctly, refused). Full suite 423 passed / 2 skipped.
Live proof post-fix: a probe with one real slug + one ghost → ghost REFUSED (stderr),
real slug ledgered, production ledger restored byte-identical after the probe.

**Corrections to the tasking model (evidence-backed):**
- NIKE's message said "the gate validates against the ledger and does NOT verify
  the files exist." Half right: `check-images.mjs` DOES verify files — the real gap
  was (a) nobody invokes it in the publish lane, and (b) the LEDGER WRITER had no
  existence check. Fixed at the writer (the only point that can distinguish
  "covered" from "merely published").
- 8e3c4b3 (barcelona PNGs) was symptom treatment as charged; it remains necessary
  (the art is real and live) but the mechanism fix is ccb7481.

**F-03 documentation debt (NIKE's outstanding item):** the fix lives only in
Strapi (content, not code) — `budgeting-apps-for-digital-nomads` is PRE-BACKSTOP
RESIDUE: published 2026-10-04T13:00, backstop `1933489` landed 16:19 the same day.
Changed 0 → 2 internal link targets via the pipeline's own
`update_article(status="published")`; recorded in the RUNBOOK QA Phase 2 entry
(committed c0357a8) because issue_log.md did not exist as a file in this repo.
git cannot hold this change by design (Strapi is the store); RUNBOOK is the
durable record.

Out of scope, honored: F-05 (CLOSED BY DECISION — hidream-era 675s accepted),
F-07/F-11 (deferred pending true denominator measurement), F-01 (self-healed,
no purge — declined in report), F-03 (passes; untouched this round).
