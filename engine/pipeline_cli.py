"""Pipeline orchestrator — chains research -> draft -> SEO -> policy -> Strapi.

CLI (via engine/cli.py):
  python -m engine.cli next                # show next pending topic
  python -m engine.cli draft-one <slug>    # run full pipeline on one topic
  python -m engine.cli run-batch [N]       # process up to N pending topics (N >= 1)
  python -m engine.cli drafts              # list drafts in Strapi
  python -m engine.cli publish [--dry-run] # daily publish lane (skips quarantined)
  python -m engine.cli publish --release <slug>  # explicit human release of a
                                           # quarantined article (topicDecision
                                           # quarantine -> needs_review; never
                                           # publishes by itself)
  python -m engine.cli info                # show config (redacted)
  python -m engine.cli gemini-smoke        # one live generateContent call with
                                           # the .env GEMINI_API_KEY; exit 0 the
                                           # key authenticates (200, or 429 =
                                           # live but rate-limited), 1 rejected
                                           # (401/403 -> rotate), 2 unset/other.
                                           # [--key-file P] also fingerprints a
                                           # candidate key file (never writes
                                           # .env) — Gemini rotation verify step.

State: appends one JSON line per run to engine/state/pipeline.jsonl
       (single writer: this module).
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import time
from pathlib import Path
from typing import Optional

from config import Config, load_config, redact
from editor.editor import edit_draft
from research.research import research_topic, validate_research
from seo.analyze import analyze_seo
from writer.writer import draft_article
from policy.publish import Decision, apply_policy, is_sensitive
from publish import article_decision, is_quarantined, publish_one as _publish_one_runner
from smoke import run_smoke as run_gemini_smoke
from strapi import StrapiClient, StrapiError

STATE_FILE = Path(__file__).resolve().parent / "state" / "pipeline.jsonl"

# Per-topic wall-clock budget across ALL stages (2026-09-18). The per-stage
# budgets in llm.STAGE_BUDGET_SECONDS bound each stage (240+360+300 = 900s); this
# bounds their sum so a single topic can never consume the whole job — the caller
# (cron entrypoint or dashboard) then still gets a clean, diagnosed return
# instead of a kill.
TOPIC_BUDGET_SECONDS = 900.0

# --- Stale in-flight reclaim (2026-09-18) ------------------------------------
# A topic whose run is killed mid-flight (cron tree-kill at the 3600s cap, a tool
# timeout, an OOM) is left in one of these statuses. list_pending_topics() only
# ever asks for `pending`, so such a topic becomes invisible to every later batch
# and the queue silently runs one topic short forever (two live instances on
# 2026-09-18 — one leaked by the production timeout, one by a killed trigger).
INFLIGHT_STATUSES = ("researching", "drafting")

# Terminal statuses are never candidates: `in_review`/`published` already have an
# article and `failed` is an explicit verdict — resetting one would re-draft a
# finished topic.
TERMINAL_STATUSES = ("in_review", "failed", "published")

# Staleness threshold for reclaiming an in-flight topic. Timeout ladder (must stay
# in sync with ~/.hermes/scripts/nomadomics_daily_draft.sh):
#   per-stage budgets 240/360/300s (llm.STAGE_BUDGET_SECONDS)
#     < per-topic budget TOPIC_BUDGET_SECONDS = 900s
#       < STALE_INFLIGHT_SECONDS = 2 x 900s = 1800s
#         < batch guard 2700s < cron tree-kill cap 3600s
# 2x the worst-case topic budget means a topic that is legitimately still running
# (even with every stage at its full budget) is never reclaimed, while one
# orphaned by a killed run is back in the queue by the next batch. Derived from
# TOPIC_BUDGET_SECONDS — never re-typed as a literal.
STALE_INFLIGHT_SECONDS = TOPIC_BUDGET_SECONDS * 2

# Reclaim records from the most recent run_batch() in this process, surfaced by
# main() — see last_reclaimed().
_last_reclaimed: list[dict] = []


def _topic_budget_check(started_at: float, stage: str) -> None:
    """Raise once a single topic has spent its whole cross-stage budget."""
    if time.monotonic() - started_at >= TOPIC_BUDGET_SECONDS:
        raise TimeoutError(
            f"{stage}: per-topic budget {TOPIC_BUDGET_SECONDS:.0f}s exhausted — "
            "aborting this topic (it stays pending for the next run)"
        )


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _append_state(entry: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _parse_strapi_ts(value) -> _dt.datetime | None:
    """Parse a Strapi timestamp ('...Z' or '+00:00') into an aware datetime.

    Returns None for anything unparseable, so the caller can fail safe (an
    undatable in-flight topic is left alone rather than reset blindly).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def _article_created_slugs(state_file: Path | None = None) -> set[str]:
    """Slugs that already produced an article, per the pipeline journal.

    A slug in here must never be reset to pending: the article exists, so a
    re-run of the pipeline would create a DUPLICATE article.
    """
    path = state_file or STATE_FILE
    slugs: set[str] = set()
    if not path.exists():
        return slugs
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # a killed run can leave a torn final line
            if entry.get("event") == "article_created" and entry.get("slug"):
                slugs.add(entry["slug"])
    return slugs


def reclaim_stale_topics(
    client: StrapiClient,
    *,
    now: _dt.datetime | None = None,
    threshold_seconds: float | None = None,
    state_file: Path | None = None,
) -> list[dict]:
    """Return topics orphaned in researching/drafting by a killed run to `pending`.

    Runs at the start of every batch, before the pending queue is listed. Bounded:
    one filtered read plus one PUT per genuinely stale topic; no new state file
    (pipeline.jsonl stays the single journal). Two hard safety rules:

    * a topic in a terminal status is never touched, and
    * a slug with an `article_created` row is never reset (no duplicate articles).
    """
    threshold = STALE_INFLIGHT_SECONDS if threshold_seconds is None else threshold_seconds
    now = now or _dt.datetime.now(_dt.timezone.utc)
    cutoff = now - _dt.timedelta(seconds=threshold)
    rows = client.list_inflight_topics(INFLIGHT_STATUSES, updated_before=cutoff.isoformat())
    already_written = _article_created_slugs(state_file)
    reclaimed: list[dict] = []

    for doc in rows:
        slug = doc.get("slug")
        doc_id = doc.get("documentId")
        status = doc.get("status")
        if not slug or not doc_id or status not in INFLIGHT_STATUSES:
            continue  # unknown/terminal status (or nothing to PUT to): never touch
        updated_at = _parse_strapi_ts(doc.get("updatedAt"))
        if updated_at is None:
            continue  # undatable -> fail safe, leave it alone
        age = (now - updated_at).total_seconds()
        if age < threshold:
            continue  # inside its budget window -> a live run still owns it
        if slug in already_written:
            _append_state(
                {
                    "ts": _now_iso(),
                    "event": "reclaim_skipped",
                    "slug": slug,
                    "reason": "article_created",
                    "from": status,
                    "ageSeconds": round(age, 1),
                }
            )
            continue

        client.update_topic(doc_id, {"status": "pending"})
        reclaimed.append({"slug": slug, "from": status, "ageSeconds": round(age, 1)})
        _append_state(
            {
                "ts": _now_iso(),
                "event": "reclaim_stale",
                "slug": slug,
                "from": status,
                "to": "pending",
                "ageSeconds": round(age, 1),
                "documentId": doc_id,
            }
        )

    return reclaimed


def _attrs(doc: dict) -> dict:
    """Strapi v5 REST returns fields flat at the top level of each item."""
    return doc or {}


def _yearless_slug(slug: str) -> str:
    """Hard rule (Guy, 2026-09-07): NO years in slugs.

    Strips years from a topic slug before it becomes the article's URL —
    including the dangling preposition ('-for-2025', '-in-2025') and the
    leading-year variant ('2025-europe-travel-rules'). Idempotent.
    Verified against all live slugs; see tests/test_yearless_slug.py.
    """
    import re

    s = slug or ""
    s = re.sub(r"-(?:for|in|of)-20\d{2}\b", "", s)
    s = re.sub(r"(?:^|-)20\d{2}(?:-|$)", "-", s)
    s = re.sub(r"-?20\d{2}-?", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def _topic_payload(topic: dict) -> dict:
    """Extract useful fields from a Strapi topic document (flat v5 shape)."""
    a = _attrs(topic)
    raw_kw = a.get("targetKeywords")
    if isinstance(raw_kw, list):
        kw_list = raw_kw
    elif isinstance(raw_kw, str) and raw_kw.strip():
        kw_list = [k.strip() for k in raw_kw.split(",") if k.strip()]
    else:
        kw_list = []
    return {
        "slug": a.get("slug"),
        "title": a.get("title"),
        "primaryKeyword": a.get("primaryKeyword"),
        "targetKeywords": kw_list,
        "category": a.get("category"),
        "targetWordCount": a.get("targetWordCount") or 1800,
        "documentId": topic.get("documentId"),
    }


def _pick_author(client) -> Optional[str]:
    """documentId of the author carrying the fewest articles, for an even split.

    Ties break on slug, so the choice is deterministic. Returns None when the CMS
    has no authors (or no authors content type) — the byline is optional, so a
    Strapi without it must not break the pipeline.
    """
    try:
        authors = client.list_authors()
    except (StrapiError, AttributeError):
        # No authors content type / client without author support: the byline is
        # optional, so drafting must not fail over it.
        return None
    candidates = [a for a in authors if a.get("documentId")]
    if not candidates:
        return None
    return sorted(candidates, key=lambda a: (a.get("articles", 0), a.get("slug") or ""))[0]["documentId"]


def draft_one(client: StrapiClient, cfg: Config, slug: str) -> dict:
    started_at = time.monotonic()
    topic_doc = client.get_topic_by_slug(slug)
    if not topic_doc:
        raise StrapiError(f"topic not found: {slug}")
    topic = _topic_payload(topic_doc)

    # mark researching
    client.update_topic(topic["documentId"], {"status": "researching"})

    primary = topic["primaryKeyword"] or (topic["targetKeywords"] or [""])[0]
    try:
        _topic_budget_check(started_at, "research")
        research = research_topic(topic["title"], primary, config=cfg)
        ok, errs, warns = validate_research(research)
        if not ok:
            raise StrapiError(f"research failed quality gate: {'; '.join(errs)}")
        _append_state({"ts": _now_iso(), "event": "research_ok", "slug": slug, "facts": len(research.facts), "warnings": warns})
    except Exception as e:
        client.update_topic(topic["documentId"], {"status": "failed", "lastError": f"research: {e}"})
        _append_state({"ts": _now_iso(), "event": "research_failed", "slug": slug, "error": str(e)})
        raise

    # draft
    client.update_topic(topic["documentId"], {"status": "drafting"})
    try:
        _topic_budget_check(started_at, "draft")
        draft = draft_article(
            topic["title"], primary, research, target_words=topic["targetWordCount"], config=cfg
        )
    except Exception as e:
        client.update_topic(topic["documentId"], {"status": "failed", "lastError": f"draft: {e}"})
        _append_state({"ts": _now_iso(), "event": "draft_failed", "slug": slug, "error": str(e)})
        raise

    # edit (QA/polish pass between draft and scoring — 2b)
    try:
        _topic_budget_check(started_at, "edit")
        edited = edit_draft(draft, topic["title"], primary, research, config=cfg)
    except Exception as e:
        # Editor degrades gracefully internally; this is a last-resort guard.
        edited = None
        _append_state({"ts": _now_iso(), "event": "edit_failed", "slug": slug, "error": str(e)})
    if edited is not None and getattr(edited, "failure_record", None):
        # Auth-degraded hop (401/403, t_8db05179): the pipeline CONTINUES on the
        # un-edited draft, but the key-rotation need is journaled here. The
        # record carries provider/model/status key names only — never key material.
        _append_state({"ts": _now_iso(), "event": "edit_degraded_auth", "slug": slug, **edited.failure_record})

    to_score = edited if edited is not None else draft

    # SEO + confidence — score the EDITED draft
    seo = analyze_seo(to_score, primary, secondary_keywords=topic["targetKeywords"], research=research)
    articles_reviewed = client.count_published()
    decision = apply_policy(
        seo.confidence,
        sensitive=is_sensitive(topic["category"]),
        first_n_human_review=cfg.first_n_human_review,
        articles_reviewed=articles_reviewed,
    )

    # write to Strapi
    kw_val = topic["targetKeywords"]
    if isinstance(kw_val, list):
        kw_val = ", ".join(kw_val)

    # Byline: the author carrying the fewest articles, so new posts keep the split
    # even without anyone assigning them by hand. Omitted if the CMS has no authors.
    author_id = _pick_author(client)

    article = client.create_article(
        {
            "title": topic["title"],
            "slug": _yearless_slug(topic["slug"]),
            "bodyMarkdown": to_score.markdown,
            "targetKeywords": kw_val,
            "focusKeyword": primary,
            "metaTitle": seo.meta_title,
            "metaDescription": seo.meta_description,
            "excerpt": seo.excerpt,
            "seoScore": seo.seo_score,
            "confidence": seo.confidence,
            "status": "draft",
            **({"author": author_id} if author_id else {}),
        }
    )
    article_doc = article.get("data", {})
    article_id = article_doc.get("documentId")

    # Publish mapping (J1): confidence-gated auto-publish >=80, only behind the
    # explicit AUTO_PUBLISH_ENABLED env flag. While the flag is off (default),
    # the v1 human gate holds and every article lands in_review. Sensitive topics
    # are structurally quarantined by the policy (QUARANTINE -> never published).
    # The policy decision is ALSO stamped onto the article (`topicDecision`,
    # 2026-09-20, t_cae3c2d2) so the publish lane can enforce the quarantine
    # gate instead of trusting the article's status alone.
    published = False
    topic_status = "in_review"
    if cfg.auto_publish_enabled and decision.decision == Decision.AUTO_PUBLISH:
        client.update_article(
            article_id,
            {
                "status": "published",
                "publishedAt": _now_iso(),
                "topicDecision": decision.decision.value,
            },
        )
        topic_status = "published"
        published = True
    elif decision.decision == Decision.REJECT:
        topic_status = "failed"
        client.update_article(
            article_id,
            {"status": "rejected", "topicDecision": decision.decision.value},
        )
    else:
        # QUARANTINE (sensitive) and NEEDS_REVIEW both land in_review for Guy.
        client.update_article(
            article_id,
            {"status": "in_review", "topicDecision": decision.decision.value},
        )
    client.update_topic(topic["documentId"], {"status": topic_status})

    _append_state(
        {
            "ts": _now_iso(),
            "event": "article_created",
            "slug": slug,
            "articleDocumentId": article_id,
            "authorDocumentId": author_id,
            "seoScore": seo.seo_score,
            "confidence": seo.confidence,
            "decision": decision.decision.value,
            "published": published,
            "voiceScore": seo.voice_score,
            "factualScore": seo.factual_score,
            "edit_report": (edited.edit_report if edited else ""),
        }
    )

    return {
        "slug": slug,
        "title": topic["title"],
        "articleDocumentId": article_id,
        "seoScore": seo.seo_score,
        "confidence": seo.confidence,
        "decision": decision.decision.value,
        "published": published,
        "words": to_score.word_count,
        "edit_report": (edited.edit_report if edited else ""),
    }


# `run-batch 0` is NOT a dry run (2026-09-18): Strapi clamps `pageSize=0` to a
# non-empty first page (measured live: pageSize=0 -> data=1 row, meta.total=2), so
# a zero limit reaches draft_one() and drafts one real topic — real LLM spend, a
# real article, a real review TODO. Zero/negative limits are therefore refused
# outright (loudly, before any Strapi read or write) instead of being clamped, so
# a misuse can never be mistaken for the legitimately empty "Processed 0 topic(s)."
# queue-drained result. To inspect the queue without drafting, use `engine.cli next`.
MIN_BATCH_LIMIT = 1


def _parse_batch_limit(raw: str) -> int:
    """Parse the `run-batch [N]` argument; raise ValueError on anything that is not
    a whole number >= MIN_BATCH_LIMIT."""
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"limit must be a whole number >= {MIN_BATCH_LIMIT} (got {raw!r})")
    if limit < MIN_BATCH_LIMIT:
        raise ValueError(
            f"limit must be >= {MIN_BATCH_LIMIT} (got {limit}) — 'run-batch 0' is not a "
            "dry run: Strapi clamps pageSize=0 to one row, so it would draft a real topic"
        )
    return limit


def run_batch(
    client: StrapiClient, cfg: Config, limit: int = 3, *, reclaim: bool = True
) -> list[dict]:
    global _last_reclaimed

    # Refuse a zero/negative limit before touching Strapi at all: no reclaim, no
    # listing, no state write, no draft. (See MIN_BATCH_LIMIT above.)
    if limit < MIN_BATCH_LIMIT:
        _last_reclaimed = []
        raise ValueError(
            f"run_batch: limit must be >= {MIN_BATCH_LIMIT} (got {limit}) — 'run-batch 0' "
            "is not a dry run (Strapi clamps pageSize=0 to one row); nothing was listed "
            "or drafted"
        )

    # Queue hygiene first: a previous run killed mid-topic left its topic in
    # researching/drafting, which list_pending_topics() can never see again.
    _last_reclaimed = reclaim_stale_topics(client) if reclaim else []

    topics = client.list_pending_topics(limit=limit)
    if not topics:
        return []
    results = []
    for topic_doc in topics:
        slug = _attrs(topic_doc).get("slug")
        if not slug:
            continue
        try:
            results.append(draft_one(client, cfg, slug))
        except Exception as e:
            print(f"  !! {slug}: failed ({e})", file=sys.stderr)
    return results


def last_reclaimed() -> list[dict]:
    """Reclaim records produced by the most recent run_batch() in this process.

    Kept out of run_batch's return value (dashboards iterate it) and out of
    run_batch's own stdout: the cron entrypoint reads the FIRST line of output as
    the batch summary, so the reclaim notice is printed by main() after it.
    """
    return list(_last_reclaimed)


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    cmd = argv[0] if argv else "next"
    cfg = load_config()
    client = StrapiClient(cfg)

    try:
        if cmd == "next":
            topics = client.list_pending_topics(limit=1)
            if not topics:
                print("No pending topics.")
                return 0
            t = _topic_payload(topics[0])
            print(f'Next: {t["title"]} ({t["slug"]}) | kw={t["primaryKeyword"]} | cat={t["category"]}')
            return 0

        if cmd == "draft-one":
            if len(argv) < 2:
                print("usage: python -m engine.pipeline draft-one <slug>", file=sys.stderr)
                return 2
            result = draft_one(client, cfg, argv[1])
            print(json.dumps(result, indent=2))
            return 0

        if cmd == "run-batch":
            # A zero/negative limit is rejected (exit 2), never passed through:
            # `pagination[pageSize]=0` is clamped by Strapi to a non-empty page, so
            # it would draft a real topic. See MIN_BATCH_LIMIT.
            try:
                n = _parse_batch_limit(argv[1] if len(argv) > 1 else "3")
            except ValueError as e:
                print(f"run-batch: refused — {e}", file=sys.stderr)
                print(
                    "  (nothing was listed or drafted; use 'python -m engine.cli next' "
                    "to inspect the queue)",
                    file=sys.stderr,
                )
                return 2
            results = run_batch(client, cfg, n)
            print(f"Processed {len(results)} topic(s).")
            for r in results:
                state = "PUBLISHED" if r.get("published") else r["decision"]
                print(f'  - {r["title"]} | conf={r["confidence"]} | {state}')
            # After the summary line (the cron entrypoint reads line 1 as the
            # batch summary) and with a marker that cannot be mistaken for an
            # article row (those start with "  - ").
            for rec in last_reclaimed():
                print(
                    f'  ~ reclaimed stale topic {rec["slug"]} '
                    f'({rec["from"]}, idle {rec["ageSeconds"]:.0f}s) -> pending'
                )
            return 0

        if cmd == "drafts":
            drafts = client.list_drafts()
            print(f"{len(drafts)} draft/in-review article(s):")
            for d in drafts:
                a = _attrs(d)
                print(f'  - [{a.get("status")}] {a.get("title")} (conf={a.get("confidence")})')
            return 0

        # publish one article (daily pipeline)
        if cmd == "publish":
            dry_run = "--dry-run" in argv
            skip_image = "--skip-image" in argv
            no_commit = "--no-commit" in argv
            # Explicit human release path for a quarantined article (t_cae3c2d2).
            # The daily lane refuses quarantine-class articles; an operator can
            # still ship one deliberately after Guy's sign-off by moving it out
            # of the quarantine class first. `--release <slug>` is that explicit
            # action: it marks the article approved-for-release (topicDecision
            # -> needs_review) and the article becomes eligible again — but only
            # if Guy (or the human operator) already moved status to in_review.
            # It is a WRITE; it never publishes by itself.
            release_slug = None
            if "--release" in argv:
                i = argv.index("--release")
                if i + 1 >= len(argv):
                    print(
                        "usage: python -m engine.cli publish --release <slug> [--dry-run]",
                        file=sys.stderr,
                    )
                    return 2
                release_slug = argv[i + 1]
            if release_slug:
                if not release_slug or release_slug.startswith("-"):
                    print(
                        "usage: python -m engine.cli publish --release <slug>",
                        file=sys.stderr,
                    )
                    return 2
                try:
                    topic = client.get_topic_by_slug(release_slug)
                except StrapiError as e:
                    print(f"release: Strapi error while looking up topic {release_slug}: {e}", file=sys.stderr)
                    return 1
                articles = client._request(
                    "GET",
                    "/api/articles",
                    params={
                        "filters[slug][$eq]": release_slug,
                        "pagination[pageSize]": 1,
                    },
                ).get("data", [])
                if not articles:
                    print(
                        f"release: no article with slug '{release_slug}' — nothing to approve",
                        file=sys.stderr,
                    )
                    return 1
                article = articles[0]
                doc_id = article.get("documentId")
                if not doc_id:
                    print("release: article has no documentId", file=sys.stderr)
                    return 1
                decision = article_decision(article)
                print(
                    f"release: {release_slug} — topic status: "
                    f"{(topic or {}).get('status') or '?'}, article decision: {decision}, "
                    f"article status: {article.get('status') or '?'}",
                )
                # A legacy article may be quarantine-class even when the server
                # field is absent ('unknown') — the draft journal's record is
                # authoritative for pre-topicDecision rows. Release must use the
                # SAME gate the publish lane uses (field OR journal), else a
                # journal-only quarantine can never be unblocked.
                from publish import is_quarantined, journal_quarantined_docids, record_release_approval

                journal = journal_quarantined_docids()
                if is_quarantined(article, journal):
                    # Explicit human release: flip the server-side field (when the
                    # field carries quarantine) AND write the durable approval
                    # ledger so the publish lane treats this article as released
                    # regardless of the draft journal (legacy rows have no field
                    # to flip).
                    if decision == "quarantine":
                        client.update_article(doc_id, {"topicDecision": "needs_review"})
                    recorded = record_release_approval(article, source="cli-release")
                    print(
                        f"release: {release_slug} approved for release — topicDecision "
                        f"{decision if decision != 'unknown' else '(no field, journal-only)'} "
                        f"{'quarantine -> needs_review' if decision == 'quarantine' else 'released via journal join'}, "
                        "approval ledger "
                        f"{'recorded' if recorded else 'NOT recorded (will block on journal join)'} "
                        "(still not published; flip status to in_review/published in "
                        "Strapi admin or run publish --dry-run to confirm eligibility)"
                    )
                else:
                    print(
                        f"release: {release_slug} is not quarantined (decision={decision}) — "
                        "nothing to do"
                    )
                return 0

            result = _publish_one_runner(
                client, cfg,
                dry_run=dry_run,
                skip_image=skip_image,
                no_commit=no_commit,
            )
            print(json.dumps(result, indent=2))
            # Exit non-zero when a publish shipped something that is NOT live
            # (kanban t_69dcb49a). `live: false` used to still exit 0, so the cron
            # lane reported success while the article page or its card/og art was
            # 404. A skip/dry-run is not a failure.
            if result.get("event") == "published" and result.get("live") is False:
                print(
                    "❌ publish reported live=false — "
                    f"httpStatus={result.get('httpStatus')} "
                    f"assetStatus={result.get('assetStatus')} "
                    f"push={result.get('push')} ({result.get('pushDetail', '')})",
                    file=sys.stderr,
                )
                return 1
            return 0

        # config/info
        if cmd == "info":
            print(json.dumps(redact(cfg), indent=2))
            return 0

        # live Gemini key check (rotation runbook verify step, t_7e0fea29).
        # Read-only: no Strapi client touched, no state file written — the
        # finally below just closes the idle client.
        if cmd == "gemini-smoke":
            key_file = None
            if "--key-file" in argv:
                i = argv.index("--key-file")
                if i + 1 >= len(argv):
                    print("usage: python -m engine.cli gemini-smoke [--key-file <path>]", file=sys.stderr)
                    return 2
                key_file = argv[i + 1]
            return run_gemini_smoke(config=cfg, key_file=key_file)

        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
