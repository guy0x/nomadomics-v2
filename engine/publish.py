"""Daily publish pipeline runner.

Picks the highest-confidence in_review article (EXCLUDING quarantine-class
articles — see the QUARANTINED_DECISIONS gate below), runs a focused final
polish (TL;DR + internal links + meta tightening), generates card/OG cover art
via Cake Nano, publishes to Strapi (status=published, publishedAt=now), commits
AND pushes the cover assets to origin/main, and verifies the article page and
both art URLs are live (a publish is not "done" while its card/og 404).

CLI entrypoint: `publish` command (registered in engine/pipeline_cli.py).
State: append-only engine/state/publish-pipeline.jsonl (single writer: this module).
Secrets: Cake API key read from HERMES_CUSTOM_CAKE_NANO_GPT_COM_API_KEY — never logged.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

from config import Config, load_config
from llm import (
    LLM_TIMEOUT,
    StageBudget,
    endpoint_for,
    headers_for,
    is_retryable_status,
    resolve,
    stage_chain,
)
from strapi import StrapiClient, StrapiError

PUBLISH_STATE_FILE = Path(__file__).resolve().parent / "state" / "publish-pipeline.jsonl"
DRAFT_JOURNAL = Path(__file__).resolve().parent / "state" / "pipeline.jsonl"
RELEASE_APPROVALS = Path(__file__).resolve().parent / "state" / "release-approvals.jsonl"
REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_CARDS = REPO_ROOT / "frontend" / "public" / "cards"
PUBLIC_OG = REPO_ROOT / "frontend" / "public" / "og"
SNAPSHOT = REPO_ROOT / "frontend" / "scripts" / "published-slugs.json"
CARD_W, CARD_H = 1200, 630
MIN_CONFIDENCE = 75

# --- asset shipping + verification (2026-09-20, kanban t_69dcb49a) -----------
# Cover art only becomes public when its commit reaches origin/main: Vercel
# deploys this repo from git pushes (docs/HANDOFF-2026-09-07.md:59), so a commit
# that stays local serves 404 forever. commit_assets() used to stop at
# `git commit` and the ONLY push in the lane lived in the cron wrapper's
# `published` branch — so an out-of-band publish (interactive `engine.cli
# publish`, `--release <slug>`) stranded its art, and a skip-day wrapper run
# could not sweep it live. Live proof 2026-09-20: the article page for
# cost-of-living-chiang-mai was 200 while its cards/ and og/ .png were 404
# (committed 4524ded, never pushed). The push now lives next to the commit so
# EVERY publish path ships; the wrapper keeps its own (now unconditional) push
# as the self-heal for anything a previous run stranded.
# The post-publish live check asserts the art URLs too, with a bounded retry
# because push -> Vercel deploy is asynchronous: retries absorb propagation lag,
# but they never mask a genuine miss (a slug with no deployed art still ends
# `assetsLive: false` and the runner exits non-zero).
PUSH_TIMEOUT_SECONDS = 180
ASSET_VERIFY_ATTEMPTS = 10
ASSET_VERIFY_DELAY_SECONDS = 30.0

# Quarantine gate (2026-09-20, from finding t_cae3c2d2). The draft lane records
# a policy decision per article; for sensitive topics (taxes/legal/medical/
# visas/banking) that decision is QUARANTINE — "always human review, never
# auto-published". The publish lane used to gate ONLY on status=in_review +
# confidence, so a quarantined article was published on the next 13:00 run with
# no human sign-off (proven live: crypto-taxes-for-digital-nomads published
# 2026-09-19T10:06Z with decision=quarantine in engine/state/pipeline.jsonl).
# The gate field is `topicDecision` on the Strapi article (engine/policy/
# publish.py Decision value; "unknown" when the article predates the field or
# was created before the draft lane started stamping it).
#
# A quarantined article is NOT an eligible auto-publish candidate, and if it is
# somehow selected by an external path the runner REFUSES to publish it. The
# ONLY release path is an explicit human action: Guy flips status to published
# in Strapi admin (the engine token has update but no delete — quarantine not
# destroy), or Guy moves the article out of the quarantine class entirely.
QUARANTINED_DECISIONS = {"quarantine"}
CAKE_BASE = "https://cake.nano-gpt.com/api/v1"
CAKE_MODEL = "hidream"
CAKE_SIZE = "1536x1024"
CAKE_KEY_ENV = "HERMES_CUSTOM_CAKE_NANO_GPT_COM_API_KEY"

# Fallback image route (2026-09-19). Cake is the preferred model (Guy), but a
# weekly-cap lockout or a rotated key returns 401 and cover generation failed
# NON-FATALLY — the article published anyway, so three consecutive posts went live
# with no card/OG art and nothing retried them (publish state: cover "failed"
# 09-16, 09-17, 09-18). The fleet's live provider exposes image models on the same
# OpenAI-compatible route, so cover art now walks an ordered chain and only gives
# up when every route is unusable. Verified 2026-09-19: nano-banana-2 returns
# b64_json PNG in ~19s, gpt-image-2 in ~15s, nano-banana returns a data: URL.
FALLBACK_IMAGE_BASE = "https://api.cheaperinference.com/v1"
FALLBACK_IMAGE_MODEL = "nano-banana-2"
FALLBACK_IMAGE_SIZE = "1536x1024"
FALLBACK_IMAGE_KEY_ENV = "HERMES_CUSTOM_API_CHEAPERINFERENCE_COM_API_KEY"
COVER_TIMEOUT_SECONDS = 180.0
# Last-resort polish model (paid but pennies) — used when the free chain fails.
CAKE_CHAT_MODEL = "z-ai/glm-5.3-flash"

POLISH_SYSTEM = """You are the Nomadomics final-publish editor. The article passed
research + draft + edit stages and is structurally sound, well-voiced, and
fact-grounded. Your job is a NARROW pre-publish tightening — do NOT rewrite or
restructure.

1. After the opening paragraph (before the first H2), insert a "## TL;DR"
   section: 3-4 punchy bullets of the most actionable takeaways. Lead each
   bullet with a bold label (e.g. **Book refundables first:** …).
2. Add 2-3 contextual internal links to the related articles provided. Embed
   them naturally in the body prose — never as a list. Use the anchor text shown.
   Prefer linking from the most relevant section.
3. Refine metaTitle (≤60 chars) and metaDescription (≤160 chars) — make them
   punchy, include the primary keyword, end metaDescription with a hook.
4. Do NOT alter facts, stats, prices, structure, voice, headings, or add any
   new claims. Only add the TL;DR section, the links, and refine the two meta
   fields.

Return STRICT JSON only, no markdown fences:
{"markdown": "<full article>", "metaTitle": "...", "metaDescription": "..."}
"""

def _current_year() -> str:
    return _today_utc()[:4]


def _fit(text: str, limit: int) -> str:
    """Trim text to `limit` characters at a word boundary, without an ellipsis.

    Meta fields are capped by the Strapi schema; the polish model overshoots. A
    hard cut with "..." both spends three characters on punctuation and leaves a
    snippet that reads as broken, so shorten until the text fits instead.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-–—").rstrip()


# ----------------------------------------------------------------------------
# State
# ----------------------------------------------------------------------------

def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _today_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def _append_state(entry: dict) -> None:
    PUBLISH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PUBLISH_STATE_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _published_slugs(*, today_only: bool = False) -> set[str]:
    """Return slugs already published. If today_only, only the current UTC day."""
    out: set[str] = set()
    if not PUBLISH_STATE_FILE.exists():
        return out
    today = _today_utc()
    for line in PUBLISH_STATE_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("event") != "published":
            continue
        slug = e.get("slug")
        if not slug:
            continue
        if today_only and not (e.get("ts") or "").startswith(today):
            continue
        out.add(slug)
    return out


# ----------------------------------------------------------------------------
# Strapi queries
# ----------------------------------------------------------------------------

def list_in_review(client: StrapiClient, limit: int = 50) -> list[dict]:
    data = client._request(
        "GET",
        "/api/articles",
        params={
            "filters[status][$eq]": "in_review",
            "sort": "confidence:desc",
            "pagination[pageSize]": limit,
        },
    )
    return data.get("data", [])


def article_decision(article: dict) -> str:
    """The article's recorded policy decision ('needs_review'/'quarantine'/...).

    Read from the `topicDecision` field when present; falls back to `unknown`
    (a missing field must never be treated as quarantine — it is the *absence*
    of the recorded gate, which pre-dates the field, not a verdict).
    """
    d = article.get("topicDecision") or "unknown"
    return str(d).strip().lower() or "unknown"


def journal_quarantined_docids() -> set[str]:
    """documentIds the DRAFT journal recorded as QUARANTINE.

    Defense-in-depth layer (t_cae3c2d2): the draft lane appends one
    `article_created` record per article to engine/state/pipeline.jsonl, carrying
    the policy `decision`. Articles created before the `topicDecision` Strapi
    field existed have no server-side gate marker, but their quarantine decision
    IS in this journal — joining on documentId (not slug, which can differ via
    _yearless_slug) closes that hole for legacy rows. Missing file -> empty set
    (fail-open on the journal, but the Strapi topicDecision field still gates
    new articles).
    """
    if not DRAFT_JOURNAL.exists():
        return set()
    out: set[str] = set()
    for line in DRAFT_JOURNAL.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("event") != "article_created":
            continue
        if e.get("decision") == "quarantine" and e.get("articleDocumentId"):
            out.add(str(e["articleDocumentId"]))
    return out


def release_approved_docids() -> set[str]:
    """documentIds an operator EXPLICITLY approved for release (--release).

    The explicit-human-release override ledger (t_cae3c2d2): `engine.cli
    publish --release <slug>` appends one record per released documentId. A
    documentId present here is exempt from the quarantine class, regardless of
    what the Strapi field or the draft journal says — the human override is the
    highest-authority signal. Single file, appended (never rewritten), ignored
    if absent.
    """
    if not RELEASE_APPROVALS.exists():
        return set()
    out: set[str] = set()
    for line in RELEASE_APPROVALS.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("articleDocumentId"):
            out.add(str(e["articleDocumentId"]))
    return out


def record_release_approval(article: dict, *, source: str = "operator") -> bool:
    """Persist an explicit human release of a quarantined article.

    Called by the `--release` CLI path. Appends {ts, slug, articleDocumentId,
    source} to RELEASE_APPROVALS. This is the durable record that a human
    deliberately overrode the quarantine; it never publishes the article.
    """
    try:
        RELEASE_APPROVALS.parent.mkdir(parents=True, exist_ok=True)
        with RELEASE_APPROVALS.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": _now_iso(),
                        "slug": article.get("slug") or "",
                        "articleDocumentId": article.get("documentId") or "",
                        "source": source,
                    }
                )
                + "\n"
            )
        return True
    except OSError:
        return False


def is_quarantined(article: dict, journal: set[str] | None = None, approvals: set[str] | None = None) -> bool:
    """True when the article is in the quarantine class.

    Two independent signals, either of which marks quarantine:
      1. the Strapi `topicDecision` field == quarantine (new articles), or
      2. the draft journal's `article_created` record for this documentId
         recorded decision==quarantine (legacy articles, joined by documentId).
    An EXPLICIT human approval (article's documentId in `approvals`, recorded by
    `engine.cli publish --release <slug>`) overrides both — release is the
    highest-authority signal.

    A missing topicDecision and a missing journal record ('unknown') is NOT
    quarantined: pre-gate articles keep the old in_review+confidence behavior so
    the daily lane is not starved by a schema change.
    """
    if approvals and article.get("documentId") in approvals:
        return False
    if article_decision(article) in QUARANTINED_DECISIONS:
        return True
    if journal and article.get("documentId") in journal:
        return True
    return False


def _skip_reason(event: str, reason: str) -> dict:
    return {"event": event, "reason": reason}


def _hard_refuse_if_quarantined(
    article: dict, journal: set[str] | None = None, approvals: set[str] | None = None
) -> dict | None:
    """Return a skip result (never publish) when `article` is quarantine-class.

    Defense in depth: the candidate loop in publish_one already skips
    quarantine-class articles, but a race/concurrent actor could flip a
    legacy record's topicDecision to quarantine AFTER it was selected, or a
    future code path could bypass the loop. If a quarantine article ever
    reaches the publish step, this refuses it before any write, polish, or
    cover generation — release is a human-only call (Strapi admin, or
    `engine.cli publish --release <slug>`).
    """
    if is_quarantined(article, journal, approvals):
        return {
            "event": "skip",
            "reason": (
                f"refused to publish quarantined article {article.get('slug') or '?'} "
                "(topicDecision=quarantine; release only via Strapi admin)"
            ),
        }
    return None


def list_published(client: StrapiClient, limit: int = 50) -> list[dict]:
    data = client._request(
        "GET",
        "/api/articles",
        params={
            "filters[status][$eq]": "published",
            "sort": "publishedAt:desc",
            "pagination[pageSize]": limit,
        },
    )
    return data.get("data", [])


def pick_link_targets(published: list[dict], *, n: int = 8) -> list[dict]:
    """Pick up to n related articles as internal-link targets (recency order)."""
    targets: list[dict] = []
    seen: set[str] = set()
    for a in published:
        slug = a.get("slug")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        targets.append({"slug": slug, "title": a.get("title", "")})
        if len(targets) >= n:
            break
    return targets


# ----------------------------------------------------------------------------
# LLM polish pass
# ----------------------------------------------------------------------------

def _build_polish_prompt(article: dict, primary_kw: str, related: list[dict]) -> str:
    rel_lines = "\n".join(f"- [{r['slug']}](/{r['slug']}): {r['title']}" for r in related)
    year = _current_year()
    return (
        f"TITLE: {article.get('title')}\n"
        f"PRIMARY KEYWORD: {primary_kw}\n"
        f"CURRENT YEAR: {year} — if a year appears in metaTitle or "
        f"metaDescription it MUST be {year}, never a previous year.\n"
        f"EXCERPT: {article.get('excerpt') or ''}\n\n"
        "=== RELATED ARTICLES (link to 2-3 of these) ===\n"
        f"{rel_lines}\n\n"
        "=== ARTICLE BODY (markdown) ===\n"
        f"{article.get('bodyMarkdown')}\n\n"
        f"Polish now per the rules and return strict JSON. "
        f"Remember: the only acceptable year is {year}."
    )


def _parse_polish(content: str, original: dict) -> dict | None:
    text = (content or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fence:
        text = fence.group(1).strip()
    parsed: dict | None = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict):
        return None
    md = str(parsed.get("markdown", "")).strip()
    if len(md) < 500:
        return None
    return {
        "markdown": md,
        "metaTitle": str(parsed.get("metaTitle", original.get("metaTitle") or "")).strip(),
        "metaDescription": str(parsed.get("metaDescription", original.get("metaDescription") or "")).strip(),
    }


def polish_article(
    article: dict,
    primary_kw: str,
    related: list[dict],
    cfg: Config,
) -> dict | None:
    """Run the final polish LLM pass. Returns {markdown, metaTitle,
    metaDescription} or None on failure (caller keeps original)."""
    chain = stage_chain(cfg, "edit")
    payload: dict = {
        "model": None,
        "messages": [
            {"role": "system", "content": POLISH_SYSTEM},
            {"role": "user", "content": _build_polish_prompt(article, primary_kw, related)},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    client = httpx.Client(timeout=LLM_TIMEOUT)
    budget = StageBudget("edit")
    try:
        for entry in chain:
            if budget.expired():
                print(f"  ! polish chain budget exhausted ({budget.exhaustion_reason()})", file=sys.stderr)
                break
            provider, model_id = resolve(cfg, entry)
            base_url, _ = endpoint_for(cfg, provider)
            headers = headers_for(cfg, provider)
            payload["model"] = model_id
            if not budget.take():
                break
            started = time.monotonic()
            try:
                resp = client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
                if resp.status_code == 429:
                    budget.note(provider, model_id, "429 rate-limited — skipping hop", started)
                    time.sleep(2)
                    continue
                if not is_retryable_status(resp.status_code):
                    budget.note(provider, model_id, f"{resp.status_code} non-retryable — skipping hop", started)
                    continue
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                result = _parse_polish(content, article)
                if result is not None:
                    budget.note(provider, model_id, "200 ok", started)
                    return result
                budget.note(provider, model_id, "200 but unparseable polish", started)
            except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                budget.note(provider, model_id, f"error {type(e).__name__}", started, extra=f" — {e}")
                continue

        # Free chain exhausted — Cake Nano chat fallback (same key as cover art).
        key = os.environ.get(CAKE_KEY_ENV, "")
        if key:
            try:
                resp = client.post(
                    f"{CAKE_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": CAKE_CHAT_MODEL,
                        "messages": payload["messages"],
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                result = _parse_polish(content, article)
                if result is not None:
                    print(f"  polish ok via cake-nano fallback ({CAKE_CHAT_MODEL})")
                    return result
            except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                print(f"  ! cake-nano polish fallback failed: {e}", file=sys.stderr)
        else:
            print("  ! cake-nano polish fallback unavailable (no key)", file=sys.stderr)
    finally:
        client.close()
    return None


# ----------------------------------------------------------------------------
# Cover art
# ----------------------------------------------------------------------------

def _cover_prompt(title: str) -> str:
    """Cover-art prompt.

    Hard-won (2026-09-19): without an explicit "this is the only text" clause the
    image models invent extra copy — a comparison table whose data units came back
    as "10GR/Month" instead of GB — and they mis-spell the headline itself
    ("BUDJGET TRAVEL HACKS", "NOMLADS", "NIOMOAADS" all shipped on published covers).
    Naming the headline as the sole text and demanding exact spelling is the cheap
    mitigation; every new cover still gets read back with a vision check before it
    is called shipped.
    """
    return (
        f"Professional blog article cover image, 1200x630. The ONLY text anywhere in the "
        f"image is this headline, spelled exactly as written, in bold readable type: "
        f"\"{title}\". Do not add any other words, labels, tables, numbers, units, icons "
        "with text, or logos. Clean modern layout, subtle geometric or travel-themed "
        "background with green (#27976d) and dark ink tones, minimalist flat vector "
        "style, generous margins, important content centered. No people, no watermarks."
    )


def image_routes() -> list[dict]:
    """Ordered image providers for cover art — only those with a key set.

    Cake Nano HiDream first (Guy's preferred model), then the fallback route.
    "Key present" is not "key valid": a locked or rotated key is discovered on the
    call itself and the next route takes over.
    """
    routes: list[dict] = []
    for label, base, model, size, key_env in (
        (f"cake-nano/{CAKE_MODEL}", CAKE_BASE, CAKE_MODEL, CAKE_SIZE, CAKE_KEY_ENV),
        (FALLBACK_IMAGE_MODEL, FALLBACK_IMAGE_BASE, FALLBACK_IMAGE_MODEL,
         FALLBACK_IMAGE_SIZE, FALLBACK_IMAGE_KEY_ENV),
    ):
        key = os.environ.get(key_env, "")
        if key:
            routes.append({"label": label, "base": base, "model": model, "size": size, "key": key})
    return routes


def _extract_image_bytes(payload: dict, *, http_client: httpx.Client) -> bytes | None:
    """Image bytes out of an /images/generations response, across provider shapes.

    Seen live: `b64_json` (cake, nano-banana-2, gpt-image-2), a `data:` URL
    (nano-banana), or a plain http URL to fetch.
    """
    items = payload.get("data") or []
    if not items or not isinstance(items[0], dict):
        return None
    item = items[0]
    b64 = (item.get("b64_json") or "").strip()
    if not b64:
        url = (item.get("url") or "").strip()
        if url.startswith("data:"):
            b64 = url.partition(",")[2].strip()
        elif url.startswith("http"):
            fetched = http_client.get(url, timeout=COVER_TIMEOUT_SECONDS)
            fetched.raise_for_status()
            return fetched.content or None
    if not b64:
        return None
    try:
        return base64.b64decode(b64)
    except (ValueError, TypeError):
        return None


def fetch_cover_bytes(
    title: str, *, http_client: httpx.Client | None = None
) -> tuple[bytes | None, str]:
    """First usable cover image across the provider chain -> (bytes, route label)."""
    routes = image_routes()
    if not routes:
        print(
            "  !! no image provider key available "
            f"({CAKE_KEY_ENV} / {FALLBACK_IMAGE_KEY_ENV}) — skipping image gen",
            file=sys.stderr,
        )
        return None, ""
    client = http_client or httpx.Client(timeout=COVER_TIMEOUT_SECONDS)
    own = http_client is None
    prompt = _cover_prompt(title)
    try:
        for route in routes:
            try:
                resp = client.post(
                    f"{route['base']}/images/generations",
                    headers={
                        "Authorization": f"Bearer {route['key']}",
                        "Content-Type": "application/json",
                    },
                    json={"model": route["model"], "prompt": prompt, "n": 1, "size": route["size"]},
                )
                if not is_retryable_status(resp.status_code):
                    # 401/402/403/404 — locked, out of quota, or unentitled key.
                    print(
                        f"  ! cover route {route['label']} -> HTTP {resp.status_code} "
                        "(non-retryable) — trying next route",
                        file=sys.stderr,
                    )
                    continue
                resp.raise_for_status()
                raw = _extract_image_bytes(resp.json(), http_client=client)
                if raw:
                    return raw, route["label"]
                print(f"  ! cover route {route['label']} returned no image data", file=sys.stderr)
            except Exception as e:  # network/JSON/HTTP/decode — fall through to the next route
                print(f"  ! cover route {route['label']} failed: {e}", file=sys.stderr)
        return None, ""
    finally:
        if own:
            client.close()


def generate_cover(slug: str, title: str, *, http_client: httpx.Client | None = None) -> bool:
    """Generate card + OG cover for an article.
    Saves PNG to frontend/public/cards/<slug>.png and frontend/public/og/<slug>.png.
    Returns True on success."""
    if not slug:
        return False

    raw, route_label = fetch_cover_bytes(title, http_client=http_client)
    if not raw:
        print("  !! cover gen failed on every configured route", file=sys.stderr)
        return False

    tmp = Path(f"/tmp/nm-cover-{slug}.jpg")
    tmp2 = Path(f"/tmp/nm-cover-{slug}-fit.jpg")
    try:
        tmp.write_bytes(raw)

        # Resize to fit 1200x1200 box (aspect kept), then center-crop to 1200x630,
        # and convert to PNG. macOS sips, no Pillow dependency.
        subprocess.run(
            ["sips", "-z", "1200", "1200", str(tmp), "--out", str(tmp2)],
            check=True, capture_output=True,
        )
        for out_dir in (PUBLIC_CARDS, PUBLIC_OG):
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"{slug}.png"
            subprocess.run(
                ["sips", "-c", str(CARD_H), str(CARD_W), str(tmp2),
                 "--out", str(out), "-s", "format", "png"],
                check=True, capture_output=True,
            )
        print(f"  cover generated via {route_label}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  !! sips failed: {e.stderr.decode()}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  !! cover gen failed: {e}", file=sys.stderr)
        return False
    finally:
        for p in (tmp, tmp2):
            if p.exists():
                p.unlink()


def commit_assets(slug: str) -> bool:
    """git add + commit the generated cover assets and the slug snapshot. Non-fatal."""
    if not slug:
        return False
    cards = f"frontend/public/cards/{slug}.png"
    og = f"frontend/public/og/{slug}.png"
    snapshot = "frontend/scripts/published-slugs.json"
    try:
        subprocess.run(["git", "add", cards, og, snapshot], check=True, cwd=REPO_ROOT,
                       capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat(frontend): cover art for {slug}"],
            check=True, cwd=REPO_ROOT, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"  !! git commit failed: {e.stderr.decode()}", file=sys.stderr)
        return False


def pending_asset_commits() -> int:
    """Commits on local main that origin/main does not have (-1 when unknown).

    Any nonzero value means cover art (or a slug snapshot) is committed locally
    and therefore NOT public yet. -1 = git could not tell us (no origin ref, git
    unavailable); the caller then simply attempts the push and lets it report.
    """
    try:
        p = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            check=True, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        return int(p.stdout.strip() or "0")
    except Exception:
        return -1


def push_assets() -> tuple[bool, str]:
    """Ship pending commits to origin/main — the step that makes art public.

    Returns (ok, detail). Never raises: a push failure must be reported, not
    swallowed (the runner records it and the wrapper exits non-zero), and it is
    bounded by PUSH_TIMEOUT_SECONDS so a wedged push/credential prompt cannot
    outlive the run.
    """
    ahead = pending_asset_commits()
    if ahead == 0:
        return True, "nothing to push (origin/main is up to date)"
    try:
        p = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=PUSH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"git push timed out after {PUSH_TIMEOUT_SECONDS}s"
    except Exception as e:
        return False, f"git push failed: {e}"
    if p.returncode != 0:
        return False, ((p.stderr or p.stdout or "").strip() or f"git push exit {p.returncode}")[:400]
    return True, f"pushed {ahead} commit(s)" if ahead > 0 else "pushed"


def asset_verify_bounds() -> tuple[int, float]:
    """Attempts + delay for the asset live check (env-overridable for rehearsals)."""
    try:
        attempts = max(1, int(os.environ.get("NOMADOMICS_ASSET_VERIFY_ATTEMPTS", ASSET_VERIFY_ATTEMPTS)))
    except (TypeError, ValueError):
        attempts = ASSET_VERIFY_ATTEMPTS
    try:
        delay = max(0.0, float(os.environ.get("NOMADOMICS_ASSET_VERIFY_DELAY", ASSET_VERIFY_DELAY_SECONDS)))
    except (TypeError, ValueError):
        delay = ASSET_VERIFY_DELAY_SECONDS
    return attempts, delay


def verify_assets_live(slug: str, site: str, *, attempts: int | None = None,
                       delay: float | None = None) -> dict:
    """Assert the card + og PNGs are actually served, retrying past deploy lag.

    Same two URLs the monitor asserts (`nomadomics_content_invariants.py`:190-193).
    A push -> Vercel deploy takes a minute or two, so a just-pushed asset can 404
    briefly; the bounded retry absorbs that window. It does NOT mask a real miss:
    art that was never pushed, or a failed deploy, still ends `assetsLive: false`
    after the last attempt, and publish_one then reports `live: false`.
    """
    n, d = asset_verify_bounds()
    if attempts is not None:
        n = max(1, attempts)
    if delay is not None:
        d = max(0.0, delay)

    status: dict[str, int] = {}
    pending = {kind: f"{site}/{kind}/{slug}.png" for kind in ("cards", "og")}
    for attempt in range(1, n + 1):
        for kind in list(pending):
            try:
                r = httpx.get(pending[kind], timeout=20, follow_redirects=True)
                code = r.status_code
            except Exception:
                code = 0  # unreachable / DNS / timeout -> not live
            status[kind] = code
            if code == 200:
                del pending[kind]
        if not pending:
            return {"assetsLive": True, "assetStatus": status, "assetAttempts": attempt}
        if attempt < n and d:
            time.sleep(d)
    return {"assetsLive": False, "assetStatus": status, "assetAttempts": n}


def write_slug_snapshot(slugs) -> bool:
    """Refresh frontend/scripts/published-slugs.json from the live published set.

    The image gate (`node frontend/scripts/check-images.mjs`) validates against this
    snapshot, and the publisher was the one path that never updated it — so every
    publish drifted it and the gate passed against a stale universe (20 published vs
    15 listed). Writes only when the set actually changed. Best-effort by design:
    a snapshot failure must never fail a publish.
    """
    try:
        ordered = sorted({s for s in (slugs or []) if s})
        if not ordered:
            return False
        payload = json.dumps(ordered, indent=2)
        if SNAPSHOT.exists() and SNAPSHOT.read_text() == payload:
            return False
        SNAPSHOT.write_text(payload)
        print(f"  slug snapshot refreshed -> {len(ordered)} published slugs")
        return True
    except Exception as e:
        print(f"  !! slug snapshot refresh failed (non-fatal): {e}", file=sys.stderr)
        return False


# ----------------------------------------------------------------------------
# Publish one
# ----------------------------------------------------------------------------

def publish_one(
    client: StrapiClient,
    cfg: Config,
    *,
    dry_run: bool = False,
    skip_image: bool = False,
    no_commit: bool = False,
) -> dict:
    """Publish the highest-confidence eligible in_review article.

    Idempotent: refuses to (a) publish twice on the same UTC day, and (b)
    re-publish any slug that was ever published by this runner.

    Quarantine gate (t_cae3c2d2): articles whose `topicDecision` is
    `quarantine` are never eligible — the draft lane recorded them as
    sensitive topics that require human review, so this runner skips them
    (and refuses if one is ever selected by another path). Release of a
    quarantined article is a human-only call via Strapi admin; see
    `engine.cli publish --release <slug>` for the operator path.
    """
    published_all = _published_slugs()
    published_today = _published_slugs(today_only=True)

    if published_today:
        return {
            "event": "skip",
            "reason": f"already published today: {', '.join(sorted(published_today))}",
        }

    articles = list_in_review(client)
    if not articles:
        return {"event": "skip", "reason": "no in_review articles"}

    # Journal join (legacy protection): documentIds the draft journal recorded
    # as QUARANTINE, loaded once per run so it never changes mid-loop. The
    # release-approval ledger (explicit human overrides) is loaded alongside.
    journal = journal_quarantined_docids()
    approvals = release_approved_docids()

    winner: dict | None = None
    for a in articles:
        slug = a.get("slug")
        if not slug or slug in published_all:
            continue
        if is_quarantined(a, journal, approvals):
            # Quarantine gate (t_cae3c2d2): a topic the draft lane recorded as
            # QUARANTINE must never be auto-published, even at high confidence.
            # It is skipped like any other ineligible candidate. The OTHER
            # in_review articles are still scanned, so a quarantined
            # high-confidence article does not block the daily lane.
            continue
        if int(a.get("confidence") or 0) >= MIN_CONFIDENCE:
            winner = a
            break

    if winner is None:
        top = articles[0] if articles else {}
        quarantined = [str(a.get("slug")) for a in articles if is_quarantined(a, journal, approvals)]
        suffix = f" · quarantined (skipped): {', '.join(quarantined)}" if quarantined else ""
        return {
            "event": "skip",
            "reason": (
                f"no eligible in_review article >= {MIN_CONFIDENCE} confidence "
                f"(top available: {top.get('slug')}={top.get('confidence')}){suffix}"
            ),
        }

    slug: str = winner.get("slug", "")
    doc_id: str = winner.get("documentId", "")
    title: str = winner.get("title", "")
    primary_kw: str = winner.get("focusKeyword") or ""
    if not slug or not doc_id:
        return {"event": "skip", "reason": f"article missing slug/docId: {slug}"}

    # Hard refuse (defense in depth): even if a quarantine-class article is
    # somehow selected here (legacy record with a missing topicDecision that a
    # concurrent actor flips to quarantine, a future code path, a manual
    # invocation), the runner must NOT ship it — release is a human-only call.
    refused = _hard_refuse_if_quarantined(winner, journal, approvals)
    if refused is not None:
        return refused

    original_md = winner.get("bodyMarkdown") or ""

    result: dict = {
        "event": "dry_run" if dry_run else "published",
        "slug": slug,
        "title": title,
        "docId": doc_id,
        "confidence": winner.get("confidence"),
    }

    # --- polish ---
    related = pick_link_targets(list_published(client))
    polished: dict | None = None
    if not dry_run:
        print(f"  polishing {slug}…")
        polished = polish_article(winner, primary_kw, related, cfg)
        if polished:
            result["polish"] = "ok"
        else:
            result["polish"] = "failed (kept original)"

    new_md = polished["markdown"] if polished else original_md
    new_meta_title = (polished.get("metaTitle") if polished else winner.get("metaTitle")) or ""
    new_meta_desc = (polished.get("metaDescription") if polished else winner.get("metaDescription")) or ""
    # Enforce Strapi schema length caps (LLM can overshoot). Trim at a word
    # boundary with no ellipsis: "..." spends three of the characters and leaves a
    # snippet that reads as broken, so a hard cut at 57 + "..." produced meta
    # titles like "Travel Hacking for Beginners: 10 Simple Ways to Fly Cheap..."
    # (measured live 2026-09-19). Fit to the cap instead of filling it.
    new_meta_title = _fit(new_meta_title, 60)
    new_meta_desc = _fit(new_meta_desc, 160)
    # Deterministic guard: a polish model can stamp a stale year into meta
    # fields (2026-09-14: "…2025" produced in 2026). Force the current year.
    cur_year = _current_year()
    new_meta_title = re.sub(r"\b20\d{2}\b", cur_year, new_meta_title)
    new_meta_desc = re.sub(r"\b20\d{2}\b", cur_year, new_meta_desc)

    # --- publish to Strapi ---
    if not dry_run:
        update_payload = {
            "bodyMarkdown": new_md,
            "metaTitle": new_meta_title,
            "metaDescription": new_meta_desc,
            "status": "published",
            "publishedAt": _now_iso(),
        }
        client.update_article(doc_id, update_payload)
        result["publishedAt"] = update_payload["publishedAt"]

        # cover art (non-fatal)
        if not skip_image:
            print(f"  generating cover for {slug}…")
            ok = generate_cover(slug, title)
            result["cover"] = "generated" if ok else "failed"
            if ok and not no_commit:
                # Refresh the gate's snapshot from the live set BEFORE committing, so
                # the same commit carries art + snapshot (see write_slug_snapshot).
                write_slug_snapshot([a.get("slug") for a in list_published(client, limit=200)])
                commit_assets(slug)
                # Ship it (2026-09-20, t_69dcb49a): committing is not publishing —
                # Vercel serves only what is on origin/main, so an unpushed commit
                # leaves the page 200 and its art 404.
                print("  pushing cover art to origin…")
                push_ok, push_detail = push_assets()
                result["push"] = "ok" if push_ok else "failed"
                result["pushDetail"] = push_detail
                print(f"  push: {push_detail}")
                if not push_ok:
                    print(f"  !! asset push failed: {push_detail}", file=sys.stderr)
        else:
            result["cover"] = "skipped"

        # log state (single writer)
        _append_state({
            "ts": _now_iso(),
            "event": "published",
            "slug": slug,
            "docId": doc_id,
            "confidence": winner.get("confidence"),
            "polish": result.get("polish", "n/a"),
            "cover": result.get("cover", "skipped"),
        })

        # verify live on the deployed frontend — the page AND its cover art.
        # The page renders dynamically (Strapi), so checking the page alone
        # reported `live: true` for art that 404'd (2026-09-20). Art is a static
        # file that exists only once origin/main's commit is deployed, so it is
        # asserted separately, with a bounded retry for deploy lag.
        site = (os.environ.get("SITE_URL") or "https://nomadomics-v2.vercel.app").rstrip("/")
        live_url = f"{site}/{slug}"
        result["liveUrl"] = live_url
        try:
            r = httpx.get(live_url, timeout=25, follow_redirects=True)
            result["httpStatus"] = r.status_code
            page_live = r.status_code == 200 and (title.split()[0] in r.text)
        except Exception as e:
            page_live = False
            result["verifyError"] = str(e)

        if not skip_image and not no_commit:
            # This run was supposed to ship art -> its live status is part of
            # "published", not a footnote. A true miss keeps live=false.
            print(f"  verifying cover art is live (up to {asset_verify_bounds()[0]} attempts)…")
            result.update(verify_assets_live(slug, site))
            result["live"] = page_live and bool(result.get("assetsLive"))
        else:
            result["live"] = page_live

    return result
