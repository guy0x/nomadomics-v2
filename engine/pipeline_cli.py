"""Pipeline orchestrator — chains research -> draft -> SEO -> policy -> Strapi.

CLI (via engine/cli.py):
  python -m engine.cli next                # show next pending topic
  python -m engine.cli draft-one <slug>    # run full pipeline on one topic
  python -m engine.cli run-batch [N]       # process up to N pending topics
  python -m engine.cli drafts              # list drafts in Strapi
  python -m engine.cli info                # show config (redacted)

State: appends one JSON line per run to engine/state/pipeline.jsonl
       (single writer: this module).
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

from config import Config, load_config, redact
from research.research import research_topic, validate_research
from seo.analyze import analyze_seo
from writer.writer import draft_article
from policy.publish import apply_policy, is_sensitive
from strapi import StrapiClient, StrapiError

STATE_FILE = Path(__file__).resolve().parent / "state" / "pipeline.jsonl"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _append_state(entry: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _attrs(doc: dict) -> dict:
    """Strapi v5 REST returns fields flat at the top level of each item."""
    return doc or {}


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


def draft_one(client: StrapiClient, cfg: Config, slug: str) -> dict:
    topic_doc = client.get_topic_by_slug(slug)
    if not topic_doc:
        raise StrapiError(f"topic not found: {slug}")
    topic = _topic_payload(topic_doc)

    # mark researching
    client.update_topic(topic["documentId"], {"status": "researching"})

    primary = topic["primaryKeyword"] or (topic["targetKeywords"] or [""])[0]
    try:
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
        draft = draft_article(
            topic["title"], primary, research, target_words=topic["targetWordCount"], config=cfg
        )
    except Exception as e:
        client.update_topic(topic["documentId"], {"status": "failed", "lastError": f"draft: {e}"})
        _append_state({"ts": _now_iso(), "event": "draft_failed", "slug": slug, "error": str(e)})
        raise

    # SEO + confidence
    seo = analyze_seo(draft, primary, secondary_keywords=topic["targetKeywords"], research=research)
    decision = apply_policy(
        seo.confidence,
        sensitive=is_sensitive(topic["category"]),
        first_n_human_review=cfg.first_n_human_review,
    )

    # write to Strapi
    kw_val = topic["targetKeywords"]
    if isinstance(kw_val, list):
        kw_val = ", ".join(kw_val)

    article = client.create_article(
        {
            "title": topic["title"],
            "slug": topic["slug"],
            "bodyMarkdown": draft.markdown,
            "targetKeywords": kw_val,
            "focusKeyword": primary,
            "metaTitle": seo.meta_title,
            "metaDescription": seo.meta_description,
            "excerpt": seo.excerpt,
            "seoScore": seo.seo_score,
            "confidence": seo.confidence,
            "status": "draft",
        }
    )
    article_doc = article.get("data", {})
    article_id = article_doc.get("documentId")

    # v1 rule: automation NEVER publishes. Record the policy decision for the
    # dashboard/state log, but every article lands in_review for Guy's gate.
    client.update_article(article_id, {"status": "in_review"})

    # mark topic
    topic_status = "in_review"
    if decision.decision.value == "reject":
        topic_status = "failed"
        client.update_article(article_id, {"status": "rejected"})
    elif decision.decision.value == "quarantine":
        topic_status = "in_review"
    client.update_topic(topic["documentId"], {"status": topic_status})

    _append_state(
        {
            "ts": _now_iso(),
            "event": "article_created",
            "slug": slug,
            "articleDocumentId": article_id,
            "seoScore": seo.seo_score,
            "confidence": seo.confidence,
            "decision": decision.decision.value,
            "voiceScore": seo.voice_score,
            "factualScore": seo.factual_score,
        }
    )

    return {
        "slug": slug,
        "title": topic["title"],
        "articleDocumentId": article_id,
        "seoScore": seo.seo_score,
        "confidence": seo.confidence,
        "decision": decision.decision.value,
        "words": draft.word_count,
    }


def run_batch(client: StrapiClient, cfg: Config, limit: int = 3) -> list[dict]:
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
            n = int(argv[1]) if len(argv) > 1 else 3
            results = run_batch(client, cfg, n)
            print(f"Processed {len(results)} topic(s).")
            for r in results:
                print(f'  - {r["title"]} | conf={r["confidence"]} | {r["decision"]}')
            return 0

        if cmd == "drafts":
            drafts = client.list_drafts()
            print(f"{len(drafts)} draft/in-review article(s):")
            for d in drafts:
                a = _attrs(d)
                print(f'  - [{a.get("status")}] {a.get("title")} (conf={a.get("confidence")})')
            return 0

        # config/info
        if cmd == "info":
            print(json.dumps(redact(cfg), indent=2))
            return 0

        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
