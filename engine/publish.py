"""Daily publish pipeline runner.

Picks the highest-confidence in_review article, runs a focused final polish
(TL;DR + internal links + meta tightening), generates card/OG cover art via
Cake Nano, publishes to Strapi (status=published, publishedAt=now), commits
the cover assets, and verifies the article renders on the live site.

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
from llm import endpoint_for, headers_for, resolve, stage_chain
from strapi import StrapiClient, StrapiError

PUBLISH_STATE_FILE = Path(__file__).resolve().parent / "state" / "publish-pipeline.jsonl"
REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_CARDS = REPO_ROOT / "frontend" / "public" / "cards"
PUBLIC_OG = REPO_ROOT / "frontend" / "public" / "og"
CARD_W, CARD_H = 1200, 630
MIN_CONFIDENCE = 75
CAKE_BASE = "https://cake.nano-gpt.com/api/v1"
CAKE_MODEL = "hidream"
CAKE_SIZE = "1536x1024"
CAKE_KEY_ENV = "HERMES_CUSTOM_CAKE_NANO_GPT_COM_API_KEY"
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
    return (
        f"TITLE: {article.get('title')}\n"
        f"PRIMARY KEYWORD: {primary_kw}\n"
        f"EXCERPT: {article.get('excerpt') or ''}\n\n"
        "=== RELATED ARTICLES (link to 2-3 of these) ===\n"
        f"{rel_lines}\n\n"
        "=== ARTICLE BODY (markdown) ===\n"
        f"{article.get('bodyMarkdown')}\n\n"
        "Polish now per the rules and return strict JSON."
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
    client = httpx.Client(timeout=180)
    try:
        for entry in chain:
            provider, model_id = resolve(cfg, entry)
            base_url, _ = endpoint_for(cfg, provider)
            headers = headers_for(cfg, provider)
            payload["model"] = model_id
            try:
                resp = client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
                if resp.status_code == 429:
                    time.sleep(2)
                    continue
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                result = _parse_polish(content, article)
                if result is not None:
                    return result
            except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                print(f"  ! polish attempt failed ({provider}/{model_id}): {e}", file=sys.stderr)
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

def generate_cover(slug: str, title: str, *, http_client: httpx.Client | None = None) -> bool:
    """Generate card + OG cover for an article via Cake Nano HiDream.
    Saves PNG to frontend/public/cards/<slug>.png and frontend/public/og/<slug>.png.
    Returns True on success."""
    if not slug:
        return False
    key = os.environ.get(CAKE_KEY_ENV, "")
    if not key:
        print("  !! cake key missing — skipping image gen", file=sys.stderr)
        return False

    prompt = (
        f"Professional blog article cover image, 1200x630. Title: \"{title}\". "
        "Clean modern layout, bold readable title text centered, subtle geometric "
        "or travel-themed background with green (#27976d) and dark ink tones, "
        "minimalist flat vector style, generous margins, important content centered. "
        "No people, no watermarks, no logos."
    )
    client = http_client or httpx.Client(timeout=180)
    own = http_client is None
    tmp = Path(f"/tmp/nm-cover-{slug}.jpg")
    tmp2 = Path(f"/tmp/nm-cover-{slug}-fit.jpg")
    try:
        resp = client.post(
            f"{CAKE_BASE}/images/generations",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={"model": CAKE_MODEL, "prompt": prompt, "n": 1, "size": CAKE_SIZE},
        )
        resp.raise_for_status()
        item = resp.json().get("data", [{}])[0]
        b64 = (item.get("b64_json") or "").strip()
        if not b64:
            return False
        raw = base64.b64decode(b64)
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
        return True
    except subprocess.CalledProcessError as e:
        print(f"  !! sips failed: {e.stderr.decode()}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  !! cover gen failed: {e}", file=sys.stderr)
        return False
    finally:
        if own:
            client.close()
        for p in (tmp, tmp2):
            if p.exists():
                p.unlink()


def commit_assets(slug: str) -> bool:
    """git add + commit the generated cover assets. Non-fatal."""
    if not slug:
        return False
    cards = f"frontend/public/cards/{slug}.png"
    og = f"frontend/public/og/{slug}.png"
    try:
        subprocess.run(["git", "add", cards, og], check=True, cwd=REPO_ROOT,
                       capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat(frontend): cover art for {slug}"],
            check=True, cwd=REPO_ROOT, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"  !! git commit failed: {e.stderr.decode()}", file=sys.stderr)
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
    """Publish the highest-confidence in_review article.

    Idempotent: refuses to (a) publish twice on the same UTC day, and (b)
    re-publish any slug that was ever published by this runner.
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

    winner: dict | None = None
    for a in articles:
        slug = a.get("slug")
        if not slug or slug in published_all:
            continue
        if int(a.get("confidence") or 0) >= MIN_CONFIDENCE:
            winner = a
            break

    if winner is None:
        top = articles[0] if articles else {}
        return {
            "event": "skip",
            "reason": (
                f"no eligible in_review article >= {MIN_CONFIDENCE} confidence "
                f"(top available: {top.get('slug')}={top.get('confidence')})"
            ),
        }

    slug: str = winner.get("slug", "")
    doc_id: str = winner.get("documentId", "")
    title: str = winner.get("title", "")
    primary_kw: str = winner.get("focusKeyword") or ""
    if not slug or not doc_id:
        return {"event": "skip", "reason": f"article missing slug/docId: {slug}"}

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
    # Enforce Strapi schema length caps (LLM can overshoot).
    if len(new_meta_title) > 60:
        new_meta_title = new_meta_title[:57].rstrip() + "..."
    if len(new_meta_desc) > 160:
        new_meta_desc = new_meta_desc[:157].rstrip() + "..."

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
                commit_assets(slug)
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

        # verify live on the deployed frontend
        site = (os.environ.get("SITE_URL") or "https://nomadomics-v2.vercel.app").rstrip("/")
        live_url = f"{site}/{slug}"
        result["liveUrl"] = live_url
        try:
            r = httpx.get(live_url, timeout=25, follow_redirects=True)
            result["httpStatus"] = r.status_code
            result["live"] = r.status_code == 200 and (title.split()[0] in r.text)
        except Exception as e:
            result["live"] = False
            result["verifyError"] = str(e)

    return result
