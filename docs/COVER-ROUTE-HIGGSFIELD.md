# COVER ROUTE — Higgsfield REST (primary since 2026-10-18)

Operations doc for the Nomadomics cover-generation primary route. The worker script
is the single entry point: `/Users/guy/.hermes/scripts/nomadomics_gemini_cover_worker.py`.
All generation, postprocessing, vision QA, and shipping below the submit call are
shared with the legacy Gemini-web/CDP fallback.

## Route summary

- The cover worker's **primary generation route is the Higgsfield developer REST
  API** (`api.higgsfield.ai`), ratified 2026-10-18. Route order: Higgsfield first,
  Gemini-web/CDP only for the slugs Higgsfield could not produce.
- The route **activates when the credential file has a complete key pair**:
  `~/.hermes/secrets/higgsfield_api.env` (mode 0600) must define both `KEY_ID=` and
  `SECRET=` with non-empty values. If either half is empty or the file is missing,
  the worker reports `HF_ROUTE_DEAD missing credentials` and falls back.
- Env overrides exist for tests only: `HF_API_BASE` (base URL) and
  `HIGGSFIELD_ENV_FILE` (credential path). Production uses the defaults.
- The Higgsfield **CLI is a separate surface** (OAuth session, possibly a different
  account). Never read the CLI's plan or credit balance as this API key's state.

## Auth shape

```
Authorization: Key <API_KEY_ID>:<API_KEY_SECRET>
```

- Both halves required. A key ID alone returns `401 Invalid credentials` in every
  header shape (`Bearer`, `X-API-Key`, legacy `hf-api-key`/`hf-secret`).
- Credentials live in `~/.hermes/secrets/higgsfield_api.env` (0600) as `KEY_ID=` /
  `SECRET=`. Never print, log, or commit either value; docs and cards reference the
  path only.

## Request / response lifecycle

1. **Submit** — `POST {base}/z-image/turbo` with `{"prompt": …, "aspect_ratio": "16:9"}`
   (`base = https://api.higgsfield.ai`). Accept `200/201/202`. The response carries a
   request id — parse tolerantly (`request_id` / `requestId` / `id`, shallow-recursive).
2. **Poll** — `GET /requests/<id>/status` every 15 s, capped at 32 polls (~8 min).
   Success = a result URL appears (`url` / `result_url` / `output_url`, must start
   `http(s)`). Terminal failure states include `fail|error|cancel|reject|nsfw|moderat`.
   Exhausting the cap with no URL is classified `timeout`.
3. **Download** — fetch the full-size result URL (120 s timeout); the small inline
   preview is never used. Minimum 10,000 bytes; saved to the raw dir
   (`profiles/librarian/cache/scratch/nomadomics-gemini-raw/`), extension from
   content-type (jpeg/webp/png).
4. **Postprocess (deterministic)** — center-fit crop to the canonical dimensions:
   card `1200x675`, og `1200x630` (LANCZOS), PNG optimized, quantize ladder
   (none → 256 → 128 → 64 colors) until ≤ 500,000 bytes; re-open to verify
   dimensions/format/size or fail closed.
5. **Vision QA (independent evaluator)** — `local_vision.py` (`qwen2.5vl:7b`) on card
   and og. Strict JSON: `topic_relevance`/`photorealism` ≥ 4, no watermark, no
   unwanted text, no logo, no rendering artifacts, `safe_crop=true`, `verdict=pass`
   on **both** derivatives. Any miss → `qa-rejected` (never shipped).
6. **Ship (surgical git)** — stage exactly the card+og pair, refuse when an existing
   public pair differs, refuse when unrelated files are staged, commit
   `feat(frontend): Gemini browser cover art for <slug>`, push `origin main`.

## Failure semantics

| Condition | Classification | What the operator sees |
|---|---|---|
| `401 Invalid credentials` | `HF_ROUTE_DEAD` (invalid credentials) | run falls back to CDP; label `creds-invalid` |
| `402` insufficient credits | `HF_ROUTE_DEAD` (no credits) | run falls back to CDP; label `no-credits` |
| Credential file missing/partial | `HF_ROUTE_DEAD` (missing credentials) | fallback to CDP; label `creds-missing` |
| Submit non-2xx / no request id / no result / download fail | per-slug `HF_ERROR` | that slug is skipped; batch continues |
| Poll cap exhausted (no URL) | per-slug `timeout` | `HF_ERROR <slug> no result (state=timeout)` |
| HF dead **and** CDP unavailable | `CAPABILITY_BLOCKED` | exit 75 when HF was route-dead; exit 2 when HF failed every slug for real reasons |

Route-dead conditions are **never retried within a run** — bounded classification,
no retry storm.

## Fallback route — Gemini web CDP

- For slugs Higgsfield could not produce, the worker calls the legacy CDP path
  (`scripts/gemini_cdp.py` via `/usr/bin/python3`), which drives Gemini Nano Banana
  in the logged-in Gemini web session over Brave CDP.
- **`NO_CDP_BROWSER`** means the CDP endpoint did not answer: Brave is not running
  with remote debugging on `127.0.0.1:9333`. The worker probes `/json/version`
  (2 s, no side effects) **before** invoking the fallback, so a down browser is
  classified as missing capability instead of relaunched.
- Browser availability does **not** prove API entitlement — the two surfaces are
  independent.

## Manifest

`~/.hermes/state/nomadomics_gemini_assets.json` records per-slug: `provider`
(`higgsfield:z-image-turbo` or `gemini-web`), `model`, `status`
(`ready` / `qa-rejected` / `ready-local` / `ship-failed` / `failed`), raw hash,
derivative hashes/dimensions/bytes, QA verdicts, and ship detail. A run lock lives
at `~/.hermes/state/nomadomics_gemini_cover_worker.lock`; a second concurrent run
prints `SKIP existing Gemini cover worker lock` and exits 0.

## References

- Worker: `/Users/guy/.hermes/scripts/nomadomics_gemini_cover_worker.py`
- Route reference + endpoint discovery: `skills/nomadomics-asset-management/references/higgsfield-rest-route.md`
- Asset gate contract: `skills/nomadomics-asset-management/references/image-quality-gate.md`
- Live hygiene snapshot: `state/asset-hygiene-2026-10-18.md`
