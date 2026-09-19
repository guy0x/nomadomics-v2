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

## Gemini content pipeline (2026-08-29)

Research → draft → edit all run on **Gemini 2.5 Flash** (primary) via the
OpenAI-compatible endpoint, with OpenRouter `:free` models as fallback chain.
Key: `GEMINI_API_KEY` in the gitignored `.env` (never logged).

- Stage map: `engine/research/` → `engine/writer/` → `engine/editor/` → `engine/seo/analyze.py`
  (deterministic scorer incl. a **structure score**: tables/bullets/H3/pros-cons feed
  `seo_score`, so walls of prose score lower than structured drafts).
- Publish kill-switch: `AUTO_PUBLISH_ENABLED` in `.env` (default **false**). While false,
  every draft lands `in_review` for Guy. When Guy flips it true, non-sensitive topics with
  confidence ≥ 80 auto-publish; taxes/legal/medical/visas/banking always quarantine to review.
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
