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

## Productization roadmap (2026-10-10)

The active hardening roadmap is `~/.hermes/plans/2026-10-10_225256-nomadomics-productization-roadmap.md`.
The reusable blog-production design is `~/nomadomics-v2/docs/REPLICABLE-BLOG-SYSTEM-SPEC.md`.
The P0 contract is `~/nomadomics-v2/docs/PRODUCT-CONTRACT.md`; the dated baseline is
`~/nomadomics-v2/docs/PRODUCT-BASELINE-2026-10-10.md`. Execute phases one at a time and
use fresh command output for live decisions. Do not infer current state from dated counts in
this runbook or the historical launch checklist.

The launch checklist at `~/.hermes/plans/nomadomics/2026-09-19_nomadomics-launch-checklist.md`
remains the historical launch-gate record. It is not a substitute for the productization
roadmap or a fresh probe.

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

**The `status` KEY inside the payload is a different thing (t_8e96e368,
2026-10-07).** It is the article's own app-level enum
(`draft`/`in_review`/`published`/`rejected`), and it is what the frontend filters
on (`filters[status][$eq]=published`). It does **not** control the draft&publish
layer, and setting it to a non-published value does **not** unpublish:

- The engine token cannot retract a published layer at all: `POST
  /api/articles/<docId>/actions/unpublish` → 405, content-manager action routes →
  404, and a null `publishedAt` in the payload is ignored.
- Sending `{"status": "in_review"}` through a **write-through** PUT therefore
  re-publishes the document (fresh `publishedAt`, both rows stamped) while the
  site merely stops listing it. Verified live 2026-10-07T08:11:06Z: the write
  meant to unpublish `cost-of-living-berlin-digital-nomads` did exactly that, and
  the article stayed in the published layer.
- A withdrawal is expressed as an app-status change **on the draft layer**, which
  must be requested explicitly (`status="draft"`).
  `StrapiClient.update_article` now REFUSES a write-through (`status=None`) whose
  payload sets a non-published app status, so the combination cannot be reached
  by accident again.
- `list_in_review()` unions both layers, so the two copies of a document can
  disagree; the union now ranks a QUARANTINE copy first (fail-closed) instead of
  letting `updatedAt` freshness decide, since a write-through PUT re-stamps the
  published mirror's `updatedAt` and can make it the fresher copy.

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

## Gemini content pipeline (canonized 2026-10-11)

Research → draft → edit use the account-backed **Gemini Flash Lite** text lane
(`gemini-flash-lite-latest`) through the OpenAI-compatible endpoint. The engine
reads credentials from the gitignored `.env`; values are never logged. A configured
Gemini stage is isolated to that verified route: it does not burn time on the
unverified OpenRouter `:free` list after a Gemini failure. The OpenRouter chain
remains available only when a stage explicitly selects it or the Gemini key is
absent; non-retryable `400/401/402/403/404/422` failures skip a hop instead of
burning retries.

### Perplexity Sonar research verifier (added 2026-10-12)

Gemini remains the primary research provider and continues to own stage routing.
When `NOMADOMICS_SONAR_VERIFY=1` and `OPENROUTER_MASTER_API_KEY` are available, `engine/research/research.py`
runs exactly one `perplexity/sonar` pass for every topic after Gemini returns.
This is research-only: it cannot select the draft/edit provider or publish.

- The verifier uses the separate paid OpenRouter master account, not the
  free-testing `OPENROUTER_API_KEY`; `~/.hermes/scripts/nomadomics_daily_draft.sh`
  injects only that one key into the child process and never prints it.
- Sonar rejects `response_format=json_object` (HTTP 400), so its request uses
  `response_format={"type":"text"}`; the engine's existing tolerant JSON parser
  still validates/extracts the result.
- OpenRouter `message.annotations` citation URLs are preserved and fill missing
  fact URLs. Gemini facts stay first; unique Sonar facts are appended up to six
  total, with URL/claim de-duplication.
- One key-free receipt per verifier attempt is appended to
  `engine/state/research-verifier.jsonl` (status, fact/citation counts, and
  provider-reported cost only). A transient Sonar failure does not discard a
  valid Gemini result, but the receipt exposes the degraded pass for monitoring.
- The measured compatibility probe returned HTTP 200, five structured facts,
  twenty citation annotations, and a provider-reported cost of about `$0.006`
  for a ~1,000-token research call. There is intentionally no daily cap by
  the current operating decision; the batch still performs one call per topic.

To verify the route without running a batch:
```sh
env -u PYTHONPATH OPENROUTER_MASTER_API_KEY="<from secure env>" \
  .venv/bin/python /Users/guy/.hermes/cache/scratch/probe_nomadomics_sonar_exact.py
```
The scratch probe must never be committed and must not print key material.

- Stage map: `engine/research/` → `engine/writer/` → `engine/editor/` → `engine/seo/analyze.py`.
- The writer sends an explicit `max_tokens=6000` budget so Gemini does not return
  an HTTP 200 with an empty structured draft; an empty/malformed 200 skips that
  hop rather than retrying the same provider blindly.
- The browser account is the **only route for new cover images**. Nano Banana is
  driven through the supervised Brave CDP session on `127.0.0.1:9333`; session-
  scoped image URLs are never logged or persisted.
- The cover worker downloads the full-size browser artifact, writes only
  `1200x675` card and `1200x630` OG PNGs, caps each derivative at `500,000`
  bytes, runs independent local vision QA, and records hashes/dimensions/verdict
  in `~/.hermes/state/nomadomics_gemini_assets.json`. It refuses to overwrite
  an existing public pair and fails closed on uncertainty.
- `engine/publish.py` accepts a cover only when that browser receipt is present
  and re-verifies provider, status, dimensions, byte sizes, and hashes. No
  receipt means no publish. The draft lane applies the same receipt check before
  writing a published-layer status; absent a receipt it leaves the article in
  `in_review` for the next worker/publish window.

Health probe (same config, both research and draft stages):
```
env -u PYTHONPATH .venv/bin/python /Users/guy/.hermes/scripts/nomadomics_lane_smoke.py --json
```
State: `~/.hermes/state/nomadomics_lane_liveness.json` (single writer).

- Structure contract lives in the writer + editor prompts (bullets under every H3,
  comparison tables, Pros/Cons, Bottom Line, FAQ) — output renders via the frontend's
  react-markdown GFM renderer.
<!-- canon:volatile:start -->
- Publish gate (ratified E, 2026-09-23): auto-publish under invariants, veto in the daily digest.
  The engine publishes a non-sensitive article when policy confidence clears and the write-time
  invariants pass: non-empty excerpt and meta, yearless slug, at least two real citations in
  a reader-visible `## Sources` section, no retired generic opener, and clean markdown links.
  Since t_252b48e7 (2026-10-12) the publish lane ALSO passes the fetched published corpus to
  `article_invariant_errors()`, enabling the corpus-repetition gate below; without a corpus
  that gate stays inert (the draft lane's write check has none in reach).
  Guy can retract from the daily digest. Taxes/legal/medical/visas/banking stay quarantined.
  `publish_gate=auto-publish-under-invariants` · `veto=daily-digest` · cron_total is in
  `~/.hermes/docs/generated-canon.txt` (129 on 2026-09-23), not in this paragraph.
<!-- canon:volatile:end -->

### Corpus-repetition gate + LLM style judge (t_252b48e7, 2026-10-12)

Guy MCQ verdict: BOTH mechanisms. Evidence: "Picture this, you" opened 13 published
articles identically; "vibrant" appears in 29 of 50 published articles; the retired
regex banned only two named openers.

- **N-gram corpus-repetition gate** (`engine/invariants.py`,
  `corpus_repetition_issues` + `cliche_issues`, deterministic):
  - Any opener 3-gram (first ~6 words, lowercased) already used by >= 2 published
    articles fails as a repeated opener template. Inert below 3 usable corpus
    bodies; the article's own row is excluded.
  - A seeded cliché census (`vibrant, boasts, nestled, hidden gem, look no
    further, game-changer, when it comes to`) fails a draft carrying >= 2
    DISTINCT seeded phrases (`cliche density over threshold`, with per-phrase
    hit counts in the message). Thresholds are module constants
    (`CLICHE_MAX_PER_ARTICLE`, `OPENER_WORD_WINDOW`, `OPENER_NGRAM_SIZE`,
    `OPENER_MIN_CORPUS`).
  - Wired into `article_invariant_errors(published_corpus=...)`: the 13:00
    publisher fetches the corpus ONCE per run (the same published-layer read the
    internal-link backstop needs) and passes it for candidate selection, the
    blocked-reason diagnostic, and the winner's re-check. No new state file, no
    second writer, no extra request.
- **LLM style judge** (`engine/publish.py`, `style_judge_gate`, per new draft
  before the publish write): one bounded pass comparing the FINAL body against
  `engine/writer/prompts/voice_exemplar.md` with a strict-JSON verdict
  `{cliche_flags, voice_match: pass|fail, reasons}`. Runs on the same edit
  chain the polish pass uses, under its own 120s StageBudget, one attempt per
  hop, no blind retries. FAILS CLOSED on transport error, parse failure, or an
  ambiguous verdict — a judge outage keeps the article in review for the next
  run. Blocks are journaled as `publish_refused_style_judge` in
  `engine/state/publish-pipeline.jsonl` (same event family as
  `publish_refused_link_hygiene`). Dry runs skip the judge (no polish there, so
  the body judged would not be the body published).
- Provider keys never print: the judge posts via the existing
  `endpoint_for`/`headers_for` helpers (headers hold the key in the request
  only; pytest output masks it).

Verification:

```bash
cd ~/nomadomics-v2
env -u PYTHONPATH .venv/bin/python -m pytest engine/tests/test_repetition_gate.py -q
env -u PYTHONPATH .venv/bin/python -m pytest engine/tests/ -q   # full suite
```

### Content-quality gates (canonized 2026-10-11 — slide-6 audit)

These are prevention gates for **new writes and publish candidates**. They do not
bulk-rewrite the historical corpus; remediation of existing pages is a separate,
reviewed migration.

- **Visible provenance:** `ensure_body_citations()` in `engine/invariants.py`
  guarantees two real research links and a reader-visible `## Sources` section.
  Source links must be proper markdown links; placeholder, unreachable, and
  host-mismatched URLs never qualify.
- **Opening diversity:** `opening_pattern_issues()` rejects the retired generic
  `Picture this` / `Imagine this` prefixes. The writer prompt and voice exemplar
  require a topic-specific money frame, counterintuitive claim, reader decision,
  or genuinely specific scene instead.
- **Link hygiene:** `link_hygiene_issues()` is wired into the shared
  `article_invariant_errors()` gate. Bare URLs, plain parenthesized URLs,
  hyphenated-slug anchors, and wrong-domain slug links block the write/publish.
- **Shared enforcement:** `pipeline_cli.py` and `publish.py` call the same
  `article_invariant_errors()` implementation; a passing model score cannot
  bypass these deterministic checks.
- **Prompt prevention:** `engine/writer/writer.py` and
  `engine/writer/prompts/voice_exemplar.md` state the same opening and source
  requirements so generation is steered before deterministic rejection.

Verification:

```bash
cd ~/nomadomics-v2/engine
env -u PYTHONPATH ../.venv/bin/python -m pytest tests/test_content_quality.py tests/test_body_citations.py tests/test_link_hygiene.py -q
```

## Daily content-production cadence (ARMED 2026-10-11)

The engine now runs every day, including Saturday and Sunday. The draft lane
writes reviewable/in-review articles; an AUTO_PUBLISH policy decision is still
held in `in_review` until the supervised browser-cover receipt exists; the retry
lane is guarded and bounded; the publish lane promotes at most one article per
UTC day after the browser-cover receipt gate passes. The cover worker also scans
published articles that are missing a public pair so old artifact gaps can be
repaired without overwriting existing assets.

- `f965b83c176a` `nomadomics-draft-batch`: `0 9 * * *`, enabled, no-agent,
  `~/.hermes/scripts/nomadomics_daily_draft.sh`.
- `ce01c7164641` guarded retry: `30 11 * * *`, enabled, no-agent,
  `~/.hermes/scripts/nomadomics_daily_draft_retry.sh`.
- `1ec0be772c2f` topic feeder: `0 8 * * *`, enabled, no-agent,
  `~/.hermes/scripts/nomadomics_topic_feeder.py`.
- `c3b70b186b0e` lane smoke: `19 */2 * * *`, enabled, no-agent, project
  `.venv/bin/python`, `/Users/guy/.hermes/scripts/nomadomics_lane_smoke.py`.
- `fde4be350c42` browser cover worker: `25 */2 * * *`, enabled, no-agent,
  Hermes image venv, `/Users/guy/.hermes/scripts/nomadomics_gemini_cover_worker.py`.
- `b9e3891806f7` `nomadomics-daily-publish`: `0 13 * * *`, enabled, no-agent,
  `~/.hermes/scripts/nomadomics_daily_publish.sh`.

The cadence is verified from `~/.hermes/cron/jobs.json`; do not edit that file
by hand. Every entrypoint has a bounded batch/timeout contract, and provider
`401/402/403/404` failures are not retried blindly. The browser worker is
supervised automation: if Brave/CDP or vision QA is unavailable, the article
remains reviewable and the publisher skips it rather than publishing without a
receipt.

## Daily publish pipeline (ARMED 2026-09-14 — Guy sign-off)

One polished article/day is eligible for auto-publish, but only after the
browser Gemini cover receipt and all existing policy/invariant gates pass.

- Cron job `b9e3891806f7` "nomadomics-daily-publish" in the **default profile**
  cron store (`~/.hermes/cron/jobs.json`), `no_agent`, deliver to Pantheon
  SIGNALS. The schedule is `0 13 * * *` local (10:00 UTC) every day.
- Entrypoint: `~/.hermes/scripts/nomadomics_daily_publish.sh` (repo-external;
  strips global PYTHONPATH, sets `SITE_URL=https://www.nomadomics.blog` and
  `NOMADOMICS_COVER_MODE=gemini-browser`, and runs `engine.cli publish`).
- Runner: `engine/publish.py` selects the highest-confidence eligible
  `in_review` article ≥ 75, polishes text on the Gemini Flash Lite lane, and
  refuses the release unless the supervised browser Gemini/Nano Banana manifest
  contains a verified receipt for that slug. The worker, not an image API,
  produces `frontend/public/{cards,og}/<slug>.png`.
- Idempotency/state: `engine/state/publish-pipeline.jsonl` and
  `engine/state/publish-ledger.jsonl` remain append-only with one writer per
  file; the lane caps publication at one article per UTC day and never
  republishes a slug. No eligible article or missing browser receipt means a
  reason-coded skip, not a forced publish.
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
  Review checklist for any quarantine-class article: verify a **standard
  disclaimer** is present in the body before release approval — an explicit
  not-advice clause ("not legal/tax/financial advice") AND a consult-a-qualified-
  professional clause — and treat a missing disclaimer as a required edit, not a
  nit. The engine now enforces this as a publish-lane invariant (quarantine-class
  articles fail the 13:00 candidate loop's invariant check with the missing
  clause named, and released articles are still blocked until the disclaimer is
  added) — leaving the checklist advisory-only is no longer an option
  (enforced 2026-10-21, t_d0608cc0).
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

## Cover art — supervised browser Gemini/Nano Banana (canonized 2026-10-11)

New cover art is generated only through Guy's logged-in Gemini browser account;
paid image APIs and API fallback generators are not part of the release path.
The worker is `~/.hermes/scripts/nomadomics_gemini_cover_worker.py` and runs
under cron job `fde4be350c42` every two hours at `:25`.

- CDP availability: `python3 ~/.hermes/scripts/gemini_cdp.py probe` (never log
  session URLs, cookies, or image URLs).
- Worker state: `~/.hermes/state/nomadomics_gemini_assets.json`; raw/stage files
  live only in the librarian scratch area until a verified pair is released.
- Release pair: card `1200x675`, OG `1200x630`, both PNG and ≤ `500,000` bytes.
- QA: full-size browser download → deterministic dimensions/hash/byte checks →
  independent local vision QA → exact-pair commit/push → receipt. The worker
  never overwrites existing public assets or commits unrelated staged files.
- Publisher: `browser_asset_ready(slug)` rechecks status, provider, hashes,
  dimensions, and sizes immediately before any publish write. A missing or
  malformed receipt is a hard skip.

The offline checker remains useful for repository consistency:
`cd frontend && npm run check:images`. Its live mode requires an approved
read-only Strapi token and is not replaced by the local receipt manifest.

## Kill switch (<60s)

- `launchctl unload ~/Library/LaunchAgents/com.nomadomics.strapi.plist` — halts Strapi.
- To quarantine a bad article: set `status` back to `draft` via Strapi admin or API
  (the engine token has `update` but NOT `delete` — by design, quarantine not destroy).
- Text generation uses the account-backed Gemini Flash Lite route; browser Nano
  Banana covers are account-backed. Do not enable a paid image API as an
  emergency shortcut. The hard cover-receipt gate is the rollback-safe behavior.

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

## Vercel build-failure recovery (verified 2026-10-11)

The canonical production project is `nomadomics-v2`, rooted at `frontend/`. A
production deployment is only recovered when `vercel inspect <deployment>` shows
`status Ready` and the canonical aliases are attached. The 2026-10-11 failures
were control-plane/origin failures during Next.js page-data collection, not a
TypeScript or frontend build error:

- the canonical project received a Cloudflare `530` while fetching Strapi;
- a stale duplicate project, `frontend-jh2g`, had only Strapi server secrets and
  no frontend `STRAPI_URL`, so its build fell back to `127.0.0.1:1337` and failed
  with `ECONNREFUSED`;
- recovery order: restore/check `com.nomadomics.cloudflared`, redeploy the
  canonical `nomadomics-v2` project, inspect the resulting production deployment,
  then leave the duplicate project for a separate retire-or-reconfigure decision.

Never treat the duplicate project as production and never delete it during an
incident without an explicit owner decision. Email details remain unreadable when
`email_access_gate.py` denies the librarian profile; use the Vercel deployment
logs and this runbook as the evidence source instead.

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

## 2026-10-08 — Sitemap-vs-published integrity invariant (QA F-01) — HEPHAESTUS

**Defect (reproduced live at implementation time):** the production sitemap
advertised `cost-of-living-cape-town-nomads` while live Strapi returned that
article as `in_review` and the production URL returned 404 — a stale Vercel ISR
render (`age: 41655`, `x-vercel-cache: HIT`). Reproduction: 59 sitemap locs, 1
non-200; live published total 46; feed total 46. The sitemap is generated by
the Next.js frontend from `getPublishedArticles()` (`filters[status][$eq]=published`,
`frontend/src/app/sitemap.ts`, `revalidate = 3600`), so the stale entry was a
cached render from before the withdrawal.

**Fix: a read-only regression invariant** at `engine/sitemap_integrity.py` that
compares the LIVE sitemap's article-URL set against the LIVE published Strapi
slug set, names both sets in its output, and exercises every sitemap-emitted
article URL for HTTP 200. Wired as a CLI command.

Exact invocation (from `~/nomadomics-v2`, engine venv):

```
env -u PYTHONPATH .venv/bin/python -m engine.cli sitemap-check
env -u PYTHONPATH .venv/bin/python -m engine.sitemap_integrity [--url <sitemap-url>]
```

Exit codes:
- `0` — PASS: every sitemap article URL is in the live published set and returns HTTP 200.
- `1` — FAIL (stale sitemap): a sitemap-only slug and/or an emitted article URL is not HTTP 200.
- `2` — dependency UNAVAILABLE: sitemap unreachable/non-200/empty, or the CMS
  errored/401'd/returned ZERO rows. An unauthenticated/empty CMS response is
  NEVER interpreted as "zero published articles" (fail-closed, never fail-open).

Named sets in output: `sitemap_article_slugs`, `published_article_slugs`,
`sitemap_only` (a failure), `published_only` (informational — a just-published
article lags the sitemap until the hourly ISR revalidate), plus a `non200`
line per failed URL. Both absolute and site-relative `<loc>` values are parsed;
`www.` vs apex hosts compare equal. Read-only: never writes Strapi, never
changes publication status.

Tests: `engine/tests/test_sitemap_integrity.py` (20 tests — failing case, clean
matching case, unavailable-dependency behaviour, absolute/relative URL
handling, empty-CMS refusal). Run:
```
cd ~/nomadomics-v2/engine && env -u PYTHONPATH ../.venv/bin/python -m pytest tests/test_sitemap_integrity.py -q
```
Full engine suite at implementation time: 454 passed, 2 skipped.

## 2026-10-07 — auto-publish routing defect: app status ≠ publish layer (t_8e96e368) — HEPHAESTUS

Investigation of "the Berlin article was auto-published despite being `in_review`".
No article was changed or unpublished by this work; all probes are read-only.

**1. The premise is inverted — `in_review` was a LATER state, not the publish gate that failed.**
`cost-of-living-berlin-digital-nomads` (`slvs6a8atlt276fdkpabgt4z`) was created AND
published in one step by the DRAFT lane's Ratified-E AUTO_PUBLISH branch:
`engine/state/pipeline.jsonl:221` (`article_created`, `decision=auto_publish`,
`confidence=84`, `published=true`, `2026-10-06T06:04:54Z`), `publish-ledger.jsonl:18`
(`lane=draft`), and `logs/strapi-service.log:5083`
(`PUT …?status=published`, 2026-10-06 09:04:41 local). It only became `in_review` the
next day, at 11:00:25 local, from the quarantine decision (t_e5384cee). Nothing
reached production *through* an `in_review` gate.

**2. Root cause A — the sensitive-topic gate keys off the TOPIC CATEGORY, not the content.**
`apply_policy(sensitive=is_sensitive(topic["category"]))`; the Berlin topic's category is
`geoarbitrage`, which is not in `SENSITIVE_TOPICS` and does not substring-match
tax/legal/medic/visa/bank. The article's body carried tax advice (home-office flat rate,
freelancer deductions, surcharge/church tax) and banking recommendations — the post-hoc
audit (t_5818bb2a) classified it QUARANTINED. A cost-of-living/geoarbitrage piece with
substantive tax or banking content is a category blind spot that auto-publishes.

**3. Root cause B — app-level `status` and the draft&publish layer are independent, and the withdrawal was performed as a write-through PUT.**
`logs/strapi-service.log:6118`: `[2026-10-07 11:11:06.486] PUT
/api/articles/slvs6a8atlt276fdkpabgt4z` — **no `?status=`** — 200, ~4 minutes after a
sibling worker had verified the published layer's stamps were unchanged. That PUT moved
the published layer's `publishedAt` from `2026-10-06T06:04:41.458Z` to
`2026-10-07T08:11:06.465Z`: the write meant to unpublish the article **re-published** it.
`count_published()` 46→45 only because the frontend filters
`filters[status][$eq]=published`; the published-layer row is still there.
Actor: no worker artefact issued that PUT (the t_ed813311 run ended 11:10:39 and had
already verified the stamps unchanged); the two preceding 400s (11:10:33, 11:10:54) and
an interactive TUI session opened at 11:10:28 read as a hand-run withdrawal attempt, and
card t_0e3aa733 — authored 11:12:10 — carries exactly that observation ("status set to
in_review; publishedAt re-stamped 2026-10-07T08:11Z").

Estate measurement (read-only, live Strapi): the published layer holds **64 documents,
only 45 with app status `published`** — 19 rows (30%) sit in the published layer while
carrying `in_review` (8, four of them quarantine-class), `draft` (5), or `rejected` (5).
Every consumer in the frontend (`strapi.ts:81/89/115`, sitemap, feed) hard-filters on the
app status, so the site is *accidentally* correct: the filter, not the layer state, is
what hides an unpublished article. Any consumer that reads the published layer without
that filter (raw `/api/articles`, admin API, a partner feed, a future route) serves them.

**4. Root cause C (latent) — the 13:00 lane's two-layer union could drop a quarantine flag.**
`list_in_review()` unions the published and draft layers and keeps the winner of
`_candidate_rank`, which was keyed on freshness (`updatedAt`) — and a write-through PUT
re-stamps the *published* mirror, making it the fresher copy. A quarantined draft copy
plus a stale-flagged but fresher published mirror therefore merged into a
non-quarantined candidate. `is_quarantined()` reads the merged row, so the gate could be
bypassed. Not exploited today: a live check found **0 documents currently losing a flag**
(the journal join covered the disagreements), so this is a hardening, not a lived incident.

**Fixes (this card):**
- `engine/publish.py::_candidate_rank` — quarantine ranks FIRST, so if either copy says
  quarantine the document is quarantined (fail-closed). Release is unaffected: the
  `--release` approval ledger is still checked before either field.
- `engine/strapi.py::update_article` — refuses a write-through (`status=None`) whose
  payload sets a non-published app status, with the reason inline.
- Tests: `test_publish_layer_union.py::test_quarantine_flag_survives_a_fresher_published_mirror`,
  `test_article_write_layer.py::test_write_through_cannot_change_the_app_status` +
  `…_draft_layer_app_status_change_is_allowed`.

**Red→green:** with the pre-fix rank the same scenario merges to the published mirror
(`topicDecision=None`) and `is_quarantined` returns **False**; with the fix the quarantined
draft copy wins and it returns **True** (`red_green_rank.py`, in-process, no Strapi
traffic). Full engine suite: **434 passed, 2 skipped**.

**Recommended next (not built here, needs a decision):** a read-only publish-layer drift
invariant in `nomadomics_content_invariants` that fails when published-layer rows carry a
non-published app status, so the 19-row drift cannot grow unnoticed; and either an
admin-side unpublish step in the release runbook or content-level sensitivity detection
(body scan) in place of the category-only `is_sensitive()`.

## 2026-10-08 — F-01 root cause: sitemap metadata route frozen on Vercel ISR — HEPHAESTUS (t_9ff8eb75, commit 19deb3f)

**Mechanism.** The sitemap was `app/sitemap.ts`, a Next **metadata route**. Its XML
artifact was statically rendered at deploy time (prod `last-modified: 07:46:01Z` = the
`454be79` deploy), and its route-level ISR revalidation never fired on Vercel: prod
served the same etag `360081ee…` with `age` climbing 41,655s → 43,445s under repeated
requests. So the sitemap kept advertising `cost-of-living-cape-town-nomads` after the
article moved to `in_review` (URL → 404). The sibling `/feed.xml` **plain route
handler** with the same `getPublishedArticles()` data dep and `revalidate = 3600` kept
revalidating correctly (46 items, age 237s) — the handler shape works on this stack;
the metadata route's outer artifact did not regenerate.

**Fix (commit 19deb3f, deploy 20:05:30Z).** Sitemap is now a plain route handler
`frontend/src/app/sitemap.xml/route.ts` — `export const revalidate = 3600`,
`Cache-Control: s-maxage=3600, stale-while-revalidate`, XML built per-request by the
pure builder `src/lib/sitemapXml.ts` (byte-compatible serialization; covered by
`src/lib/sitemapXml.test.ts` under `npm test`). The metadata route `app/sitemap.ts`
was deleted. Emitted URL set/format unchanged (loc host from the same
`NEXT_PUBLIC_SITE_URL`). Local build: lint 0, tests 24/24, `/sitemap.xml` in the same
ISR class as `/feed.xml` in the build output.

**Production verification (2026-10-08 20:12Z).** Sitemap 200, new etag
`4f369793…`, `last-modified: 20:05:30Z`, age reset from 43,445s → 454s; 58 `<loc>`,
0 cape-town; all 58 URLs fetched with redirects → `non200 0`; the Cape Town URL still
404s (correct — not published); live Strapi still reports it `in_review`
(`publishedAt` 07:25:12Z untouched); sitemap article URLs 46 == live published set 46.

If a stale-sitemap finding ever recurs: check the latest Vercel deployment first, and
confirm `/sitemap.xml` is still served by the route handler (not a metadata route) —
plus ATHENA's sitemap-vs-published invariant (t_84a1fa68).

## 2026-10-11 — Internal-link invariant repair + publish-lane backstop (t_49aba8a9) — HEPHAESTUS

The `nomadomics-content-invariants` cron (79ab8f76111e) failed with corpus link
coverage 48/49: `how-to-live-in-thailand-as-a-digital-nomad` carried 0 countable
internal links, and 3 articles read as zero-inbound orphans.

ROOT CAUSE (three layers, all verified):
1. DATA: the 13:00 polish pass emitted all three of Thailand's links as
   `[slug](slug)` — bare-slug hrefs, no leading slash. Browsers resolve them
   under the article path (broken links); the monitor counts zero.
2. PUBLISH LANE: the draft lane has run `ensure_internal_links` since 2026-10-04,
   but `engine/publish.py` never did — the polish LLM was the only link source,
   and `article_invariant_errors` (incl. link hygiene) ran only on the PRE-polish
   body at candidate selection, never on the final body actually published.
3. PROMPT: `POLISH_SYSTEM` said "use the anchor text shown" over a list rendered
   as `[slug](/slug)` — teaching raw-slug anchors.
(The cron's "Thailand live HTTP 500" was the transient inside that morning's
deploy window — both hosts 200 on every later probe. UNVERIFIED→TRANSIENT/RESOLVED.)

REPAIR (applier: ~/.hermes/state/nomadomics/repair_internal_links_t49aba8a9.py,
dry-run first, per-edit count assertion, backup
bodies-pre-linkfix-20261011T165336Z.json):
- Thailand: 3 bare-slug links repaired in place, two anchors naturalized, +1
  contextual link to cost-of-living-ho-chi-minh-city-nomads. Targets 0 → 4.
- how-to-legally-pay-less-tax-as-a-digital-nomad: existing "Tbilisi, Georgia"
  prose wrapped as a link to the Tbilisi article (kills that orphan). 3 → 4.
- cost-of-living-tbilisi (other orphan) now has inbound=1; HCMC inbound=1.
- Every PUT went through the canonical maintenance path with the publishedAt
  re-stamp read + SQL-restored (tax article) or scoped-transaction-restored to
  the publish-log time 2026-10-11 13:00:29.976 local (Thailand — the repair
  script's own helper crashed on this document's FOUR version rows; the two
  in_review rows were left published_at=NULL per repair_dates doctrine).
- Live read-back: all repaired /slug hrefs serving on www.nomadomics.blog AND
  nomadomics-v2.vercel.app (200). NOTE: first post-PUT probe served the stale
  ISR snapshot (revalidate=300s) — re-probe before believing a failure.

MONITOR AFTER: 51/51 published articles >= 2 internal links (100.0% coverage),
0 under-threshold, 0 zero-inbound orphans (state nomadomics_trial.json,
run 2026-10-11T16:59:06+00:00).

PREVENTION (commit 80e23af, engine tests 476 passed / 2 skipped):
- publish.py runs `ensure_internal_links` on the FINAL body (idempotent) and
  REFUSES the publish when `link_hygiene_issues` flags it (journal event
  `publish_refused_link_hygiene`) — checked before the Strapi write, not after.
- POLISH_SYSTEM now requires natural-prose anchors and the exact leading-slash
  href, and says a bare slug fails the publish gate.
- KNOWN DEBT (needs Guy's review window, NOT done here): the whole-table
  publishedAt backfill — nomadomics_repair_dates.py dry run reports 44 documents
  of September-era re-stamp drift. Bulk mutation of the content DB = Guy sign-off.

## 2026-10-12 — Corpus-repetition gate (n-gram + cliche census) + LLM style judge (t_252b48e7) — HEPHAESTUS

**Symptom:** the 2026-10-12 audit (Guy MCQ: BOTH mechanisms) showed generalized
repetition the regex gates could not see: "Picture this, you" opened 13
published articles identically, "vibrant" appeared in 29 of 50 published
articles, and `opening_pattern_issues` banned only two literal prefixes.

**Fix (both mechanisms):**
1. `engine/invariants.py` — `corpus_repetition_issues()`: any opener 3-gram
   (first ~6 words) shared by >= 2 published articles fails; `cliche_issues()`:
   a seeded 7-phrase census fails a draft with >= 2 DISTINCT seeded phrases.
   Both wired through `article_invariant_errors(published_corpus=...)`; the
   13:00 publisher fetches the corpus ONCE per run and passes it to candidate
   selection, the blocked-reason diagnostic, and the winner re-check (no new
   state file, no extra request). The draft lane's write gate stays corpus-less
   (inert repetition gate) by design — it has no body corpus in reach.
2. `engine/publish.py` — `style_judge_gate()`: one bounded LLM pass (edit
   chain, 120s StageBudget, one attempt per hop) judging the FINAL body against
   `engine/writer/prompts/voice_exemplar.md` for strict-JSON
   `{cliche_flags, voice_match, reasons}`. Fail-closed on transport/parse/
   ambiguity; refuses BEFORE the Strapi write; blocks journal as
   `publish_refused_style_judge`. Dry runs skip it (unpolished body there).

**Verification:** full engine suite 503 passed / 2 skipped (clean checkout run
below, pre-push); `test_repetition_gate.py` 25 cases cover duplicate-opener
fail, unique pass, cliche threshold, own-slug exclusion, judge pass/fail/
malformed-JSON fail-closed, publish_one refusal wiring. Live corpus probe:
49/49 published rows serve bodyMarkdown (gate is live), zero existing opener
3-grams at count >= 3 (healthy opener diversity), 5/49 legacy rows would fail
the NEW cliche threshold (left as-is — no bulk rewrite of history).

**Status:** closed (implementation); watch the next 13:00 run for the first
gated publish. Tests: `engine/tests/test_repetition_gate.py`; RUNBOOK gates
section documents both mechanisms.
