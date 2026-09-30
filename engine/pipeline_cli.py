"""Pipeline orchestrator — chains research -> draft -> SEO -> policy -> Strapi.

CLI (via engine/cli.py):
  python -m engine.cli next                # show next pending topic
  python -m engine.cli draft-one <slug>    # run full pipeline on one topic
  python -m engine.cli run-batch [N]       # process up to N pending topics (N >= 1)
                                           # exit 0 = drained (or all deferred);
                                           # exit 1 = attempted-and-all-failed,
                                           # or 0 processed while a terminal
                                           # `failed` backlog is parked (t_79196ced)
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
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

from config import Config, load_config, redact
from editor.editor import edit_draft
from llm import STAGE_BUDGET_SECONDS
from research.research import research_topic, validate_research
from invariants import article_invariant_errors, check_write_invariants, ensure_body_citations
from freshness import freshness_report
from publish_ledger import LEDGER as PUBLISH_LEDGER
from publish_ledger import record as record_publish
from seo.analyze import analyze_seo
from writer.writer import draft_article
from policy.publish import Decision, apply_policy, is_sensitive
from publish import article_decision, is_quarantined, publish_one as _publish_one_runner
from smoke import run_smoke as run_gemini_smoke
from strapi import StrapiClient, StrapiError

STATE_FILE = Path(__file__).resolve().parent / "state" / "pipeline.jsonl"

# Checkpoint/resume (2026-09-21, t_bde3d77c): a batch killed by a timeout guard
# must not waste the items its predecessor already finished. draft_one appends
# one `article_completed` row as its LAST durable write — after the article
# exists in Strapi and the topic carries a terminal status — and run_batch
# skips any listed slug that already has one. The journal stays the single
# state file: the checkpoint is two more event types in the same append-only
# stream (every existing reader filters on its own event names, so the new
# rows are invisible to them — verified: publish.journal_quarantined_docids
# and _article_created_slugs both select event=="article_created"; the
# dashboard displays raw rows generically).
CHECKPOINT_EVENT = "article_completed"
RESUME_EVENT = "checkpoint_resume"

# Per-topic wall-clock budget across ALL stages (2026-09-18). The per-stage
# budgets in llm.STAGE_BUDGET_SECONDS bound each stage (240+360+300 = 900s); this
# bounds their sum so a single topic can never consume the whole job — the caller
# (cron entrypoint or dashboard) then still gets a clean, diagnosed return
# instead of a kill.
TOPIC_BUDGET_SECONDS = 900.0

# Strapi's `article.title` maxLength (src/api/article/content-types/article/
# schema.json). The seed `topic.title` has NO length limit, so every title that
# leaves this module for an article write must be fitted to this cap first —
# pinned against the schema by tests/test_title_cap.py.
TITLE_MAX_CHARS = 70


def _env_seconds(name: str, default: float) -> float:
    """Positive-float env override; absent/garbage/non-positive -> default."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        return default
    return val if val > 0 else default


# --- batch deadline awareness (2026-09-21, t_02673f32) ------------------------
# The 09-21 run died at the shell's 2700s SIGALRM guard (exit 142) because one
# in-flight POST outran every cooperative budget. deadline_post() now binds each
# POST to its stage budget, which makes the ladder's math real — and this gate is
# the backstop: run_batch stops STARTING new topics once the remaining guard time
# can no longer fit a worst-case topic, so the batch always self-terminates with
# a partial-result summary instead of being SIGKILLed mid-item.
#
# Worst-case topic wall-clock with hard per-POST deadlines: its full topic
# budget (stages now bind at their edges) plus ONE more full stage budget —
# the last in-flight POST may run to its own stage's edge after the topic
# budget is spent (stages do not share the topic budget). 900 + 300 = 1200s.
WORST_TOPIC_SECONDS = TOPIC_BUDGET_SECONDS + max(STAGE_BUDGET_SECONDS.values())
# Same guard the cron entrypoint enforces with perl alarm (default 2700s);
# read from the same env var so a guard rehearsal constrains the engine too.
BATCH_GUARD_SECONDS = _env_seconds("NOMADOMICS_BATCH_BUDGET", 2700.0)
# Margin for the pre-batch publish smoke (it front-runs the engine clock inside
# the guard), Strapi reads, and the final summary flush.
BATCH_SAFETY_SECONDS = 120.0

def _ship_cover_art(client, slug: str, title: str) -> str:
    """Generate + ship cover art for an article published by THIS lane.

    The 13:00 publish lane (publish.publish_one) generates art on every
    publish; this lane bypassed it, so AUTO_PUBLISH articles went live with
    no covers at all (2026-09-21, t_2c07d324). Reuses publish.py's own
    helpers verbatim — same writer, same push, same verifier downstream —
    and mirrors publish_one()'s sequence: generate, refresh the image
    gate's slug snapshot, commit art+snapshot together, push to origin
    (the deploy trigger).

    Non-fatal by convention (art must never fail an already-published
    article): returns "generated" | "push_failed" | "failed", and the
    caller journals it on the article_created row so a later monitoring
    failure is always explainable from state.
    """
    try:
        # Function-local import keeps this feature's diff separate from the
        # uncommitted batch-deadline work in this file (module already
        # imports publish at top level, so there is no extra import cost).
        from publish import (
            commit_assets,
            generate_cover,
            list_published,
            push_assets,
            write_slug_snapshot,
        )

        print(f"  generating cover for {slug}…")
        if not generate_cover(slug, title):
            return "failed"
        # Same commit shape as publish_one(): art staged in the same commit
        # as a fresh gate snapshot, so the image gate's universe never drifts.
        write_slug_snapshot([a.get("slug") for a in list_published(client, limit=200)])
        if not commit_assets(slug):
            return "failed"
        push_ok, push_detail = push_assets()
        print(f"  push: {push_detail}")
        return "generated" if push_ok else "push_failed"
    except Exception as e:  # noqa: BLE001 — art failure is reported, not raised
        print(f"  !! cover shipping failed (non-fatal): {e}", file=sys.stderr)
        return "failed"


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

# --- Stranded-failure reclaim (2026-09-25, PANT-173) -------------------------
# A topic whose research/draft stage dies on a TRANSIENT error is parked in
# `failed` with `lastError` set (draft_one's three failure paths). `failed` is a
# TERMINAL_STATUS, so the in-flight reclaim above never touches it and
# list_pending_topics() (= status pending) can never see it again — one dead LLM
# hop permanently deletes a unit of supply from the queue, silently.
#
# Live case (why this exists): on 2026-09-21/22 four topics were killed by the
# retired OpenRouter hop `nvidia/nemotron-nano-12b-v2-vl:free` (HTTP 404 on
# every call) and a fifth by a stage deadline. Those five were the whole
# remaining queue, so the 09-24 09:00 batch processed 0 topics and the cron lane
# reported "queue drained, nothing to do", while the 13:00 publish lane skipped
# both days (its only >=75 in_review candidate was quarantine-class). The weekly
# feeder could not restore them either: a taken uid slug cannot be re-POSTed
# (Strapi 400 "This attribute must be unique") and the feeder aborts the whole
# batch on a write error.
#
# The retry is deliberately narrow — a policy REJECT also ends in `failed`, and
# re-drafting a rejected topic forever is not a fix. A topic is re-queued only
# when ALL hold: `lastError` is set (transient verdict; REJECT sets the topic
# status with no lastError and always leaves an article_created row), no
# article_created row exists for the slug (nothing written, nothing to
# duplicate), it is idle past FAILED_RETRY_SECONDS, and it has fewer than
# FAILED_RETRY_MAX_ATTEMPTS prior reclaim_failed rows (a persistently broken
# topic stops instead of burning LLM budget every day forever).
FAILED_STATUSES = ("failed",)
FAILED_RETRY_SECONDS = 3600.0
FAILED_RETRY_MAX_ATTEMPTS = 2
FAILED_RECLAIM_EVENT = "reclaim_failed"
FAILED_EXHAUSTED_EVENT = "reclaim_exhausted"

# --- Parked-backlog reporting (2026-09-25, t_79196ced — PANT-173 residual) ----
# The reclaim above rescues the retryable part of a `failed` backlog, but a
# batch that processed 0 topics still printed the healthy "Processed 0 topic(s)."
# with exit 0 while the REST of the backlog sat there — exactly the shape that
# masked the 09-24 supply freeze (that day the reclaim did not exist yet, so all
# five stranded topics were "the rest"). main() therefore classifies what the
# reclaim left behind and fails the run instead of reporting success:
#   policy_verdict    — no lastError: a human/policy REJECT, never re-queued
#   article_attached  — an article_created row exists, so a re-draft duplicates
#   attempts_exhausted— FAILED_RETRY_MAX_ATTEMPTS reclaims already spent
#   retry_pending     — young failure, inside the cooling-off window (a run
#                       whose only failed topic is younger than one hour is by
#                       definition not the daily cron's 0-batch — see main()).
STRANDED_VERDICT = "policy_verdict"
STRANDED_ARTICLE = "article_attached"
STRANDED_EXHAUSTED = "attempts_exhausted"
STRANDED_RETRY = "retry_pending"

# Reclaim records from the most recent run_batch() in this process, surfaced by
# main() — see last_reclaimed().
_last_reclaimed: list[dict] = []
# Re-queued `failed` topics from the most recent run_batch() — see
# last_failed_reclaimed().
_last_failed_reclaimed: list[dict] = []

# Per-topic hard failures from the most recent run_batch() in this process
# (PANT-161, t_b3949432): a batch that ATTEMPTED topics but drafted nothing
# must not read as "queue drained — nothing to do" (the 09-21 dead-chain day
# was reported exactly that way). main() prints one reason line per failure
# and exits 1 when results are empty because of these.
_last_failed: list[dict] = []


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
    return _journal_slugs(state_file, "article_created")


def _completed_slugs(state_file: Path | None = None) -> set[str]:
    """Slugs whose pipeline run COMPLETED, per the checkpoint rows.

    Checkpoint/resume (t_bde3d77c): a `article_completed` row is appended as
    draft_one's LAST durable write, so a batch killed mid-run leaves every
    finished item with one. On startup, run_batch skips these slugs instead of
    re-drafting them (the acceptance for this task). Superset of
    `article_created` by construction — same run, written seconds later —
    but checked independently so a torn file degrades to "not completed"
    (fail-safe: re-drafting is recoverable via the duplicate guard below;
    skipping a half-written item is not).
    """
    return _journal_slugs(state_file, CHECKPOINT_EVENT)


def _journal_slugs(state_file: Path | None, event: str) -> set[str]:
    """Slugs carrying `event` in the journal; torn lines are skipped.

    A killed run can leave a truncated final line — the guard reads on, which
    is also what test_reclaim_stale's torn-line test pins.
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
            if entry.get("event") == event and entry.get("slug"):
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


def _journal_slug_counts(state_file: Path | None, event: str) -> dict[str, int]:
    """Slug -> number of `event` rows in the journal; torn lines skipped.

    Companion to _journal_slugs() for the one reader that needs HOW MANY times
    something happened rather than whether it ever did (retry attempts). Reads
    the same single journal, tolerates the same torn final line, never writes.
    """
    path = state_file or STATE_FILE
    counts: dict[str, int] = {}
    if not path.exists():
        return counts
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # a killed run can leave a torn final line
            if entry.get("event") == event and entry.get("slug"):
                slug = entry["slug"]
                counts[slug] = counts.get(slug, 0) + 1
    return counts


def _one_line(text, limit: int = 60) -> str:
    """Collapse a `lastError` (may contain newlines) into one bounded line."""
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def reclaimable_failed_topics(
    client: StrapiClient,
    *,
    now: _dt.datetime | None = None,
    min_age_seconds: float | None = None,
    max_attempts: int | None = None,
    state_file: Path | None = None,
) -> list[dict]:
    """READ-ONLY: `failed` topics the NEXT batch would re-queue (PANT-185 guard).

    The 11:30 retry cron (kanban t_367b9040) must answer "is the queue
    non-empty?" including the topics the 09:00 all-attempted-failed morning
    parked in `failed` — list_pending_topics() (status=pending only) cannot
    see them, so a plain pending count would never fire the retry on exactly
    the day PANT-185 is rescuing. This function applies the SAME four-safety
    selection as reclaim_failed_topics() and returns the candidates WITHOUT
    any write — no PUT, no journal row — so a guard process can count
    tomorrow's supply without moving it.

    Rule-for-rule mirror of reclaim_failed_topics(): transient verdict only
    (lastError set), never a slug that already wrote an article, cooling-off
    window honoured (idle >= min_age_seconds), retry attempts capped.
    test_reclaimable_matches_reclaim.py pins the two to each other so the
    mirror cannot drift.
    """
    age_threshold = FAILED_RETRY_SECONDS if min_age_seconds is None else min_age_seconds
    attempts_cap = (
        FAILED_RETRY_MAX_ATTEMPTS if max_attempts is None else max_attempts
    )
    now = now or _dt.datetime.now(_dt.timezone.utc)
    cutoff = now - _dt.timedelta(seconds=age_threshold)
    rows = client.list_inflight_topics(FAILED_STATUSES, updated_before=cutoff.isoformat())
    already_written = _article_created_slugs(state_file)
    attempts = _journal_slug_counts(state_file, FAILED_RECLAIM_EVENT)
    candidates: list[dict] = []

    for doc in rows:
        slug = doc.get("slug")
        doc_id = doc.get("documentId")
        if not slug or not doc_id or doc.get("status") not in FAILED_STATUSES:
            continue  # unknown/other status (or nothing to PUT to): never touch
        if not str(doc.get("lastError") or "").strip():
            continue  # a policy REJECT also lands `failed`, but is a verdict: never re-queue
        if slug in already_written:
            continue
        updated_at = _parse_strapi_ts(doc.get("updatedAt"))
        if updated_at is None:
            continue  # undatable -> fail safe, leave it alone
        age = (now - updated_at).total_seconds()
        if age < age_threshold:
            continue  # inside the cooling-off window: leave the verdict alone
        tries = attempts.get(slug, 0)
        if tries >= attempts_cap:
            continue  # permanently broken: stop burning retries
        candidates.append(
            {
                "slug": slug,
                "documentId": doc_id,
                "ageSeconds": round(age, 1),
                "attempt": tries + 1,
                "error": _one_line(doc.get("lastError")),
            }
        )

    return candidates


def reclaim_failed_topics(
    client: StrapiClient,
    *,
    now: _dt.datetime | None = None,
    min_age_seconds: float | None = None,
    max_attempts: int | None = None,
    state_file: Path | None = None,
) -> list[dict]:
    """Return topics STRANDED in `failed` by a transient error to `pending`.

    Companion to reclaim_stale_topics(): that one rescues topics orphaned in
    researching/drafting, this one rescues the `failed` verdicts that are
    technically terminal but carry no article — see the constants block above
    for the live case and the four safety rules (lastError present, no
    article_created row, idle past the cooling-off window, attempts remaining).

    Bounded: one filtered read plus one PUT per genuinely retryable topic; the
    journal (pipeline.jsonl) stays the single state file — attempts are counted
    from its reclaim_failed rows, so no new state file appears.
    """
    age_threshold = FAILED_RETRY_SECONDS if min_age_seconds is None else min_age_seconds
    attempts_cap = (
        FAILED_RETRY_MAX_ATTEMPTS if max_attempts is None else max_attempts
    )
    now = now or _dt.datetime.now(_dt.timezone.utc)
    cutoff = now - _dt.timedelta(seconds=age_threshold)
    # The client query is status-filtered, so the in-flight reader serves this
    # one too (same shape, same updated_before cutoff).
    rows = client.list_inflight_topics(FAILED_STATUSES, updated_before=cutoff.isoformat())
    already_written = _article_created_slugs(state_file)
    attempts = _journal_slug_counts(state_file, FAILED_RECLAIM_EVENT)
    exhausted_seen = _journal_slugs(state_file, FAILED_EXHAUSTED_EVENT)
    reclaimed: list[dict] = []

    for doc in rows:
        slug = doc.get("slug")
        doc_id = doc.get("documentId")
        if not slug or not doc_id or doc.get("status") not in FAILED_STATUSES:
            continue  # unknown/other status (or nothing to PUT to): never touch
        if not str(doc.get("lastError") or "").strip():
            # A policy REJECT also lands `failed`, but it is a verdict, not an
            # error: it never sets lastError. Never re-queue a human/policy call.
            continue
        if slug in already_written:
            _append_state(
                {
                    "ts": _now_iso(),
                    "event": "reclaim_skipped",
                    "slug": slug,
                    "reason": "article_created",
                    "from": "failed",
                }
            )
            continue
        updated_at = _parse_strapi_ts(doc.get("updatedAt"))
        if updated_at is None:
            continue  # undatable -> fail safe, leave it alone
        age = (now - updated_at).total_seconds()
        if age < age_threshold:
            continue  # inside the cooling-off window: leave the verdict alone
        tries = attempts.get(slug, 0)
        if tries >= attempts_cap:
            if slug not in exhausted_seen:
                # One row per slug, not one per run: a permanently broken topic
                # must not add a line to the single journal every single day.
                _append_state(
                    {
                        "ts": _now_iso(),
                        "event": FAILED_EXHAUSTED_EVENT,
                        "slug": slug,
                        "attempts": tries,
                        "lastError": _one_line(doc.get("lastError")),
                    }
                )
            continue

        client.update_topic(doc_id, {"status": "pending"})
        reclaimed.append(
            {
                "slug": slug,
                "from": "failed",
                "ageSeconds": round(age, 1),
                "attempt": tries + 1,
                "error": _one_line(doc.get("lastError")),
            }
        )
        _append_state(
            {
                "ts": _now_iso(),
                "event": FAILED_RECLAIM_EVENT,
                "slug": slug,
                "from": "failed",
                "to": "pending",
                "ageSeconds": round(age, 1),
                "attempt": tries + 1,
                "documentId": doc_id,
                "lastError": _one_line(doc.get("lastError")),
            }
        )

    return reclaimed


def stranded_failed_topics(
    client: StrapiClient,
    *,
    reclaimed: list[dict] | None = None,
    state_file: Path | None = None,
) -> list[dict]:
    """Topics still parked in `failed` AFTER this run's reclaim — the backlog the
    batch cannot drain by itself (t_79196ced).

    Read-only by construction: one status-filtered GET, no PUT, no journal row —
    it is a reporting read, so a dry inspection of the queue costs nothing and
    writes nothing. Every non-reclaimed `failed` topic counts, whatever the
    reason (see the STRANDED_* constants): the point is that the batch is idle
    while supply is parked, and only a human (or the next reclaim window) can
    move it.

    `reclaimed` is the reclaim_failed_topics() result from the same run: those
    slugs are excluded belt-and-braces — the reclaim already PUT them back to
    `pending`, so a consistent reader would not return them at all.
    """
    rows = client.list_inflight_topics(FAILED_STATUSES, limit=100)
    already_written = _article_created_slugs(state_file)
    attempts = _journal_slug_counts(state_file, FAILED_RECLAIM_EVENT)
    fixed = {r.get("slug") for r in (reclaimed or []) if r.get("slug")}
    now = _dt.datetime.now(_dt.timezone.utc)
    stranded: list[dict] = []

    for doc in rows:
        slug = doc.get("slug")
        # A duck-typed/over-returning reader may hand back other statuses: the
        # query is server-filtered, so anything else is not ours to report.
        if not slug or doc.get("status") not in FAILED_STATUSES:
            continue
        if slug in fixed:
            continue
        error = str(doc.get("lastError") or "").strip()
        tries = attempts.get(slug, 0)
        if not error:
            # Same distinction the reclaim makes: a policy REJECT also lands
            # `failed`, but it is a verdict, not a transient error.
            reason = STRANDED_VERDICT
        elif slug in already_written:
            reason = STRANDED_ARTICLE
        elif tries >= FAILED_RETRY_MAX_ATTEMPTS:
            reason = STRANDED_EXHAUSTED
        else:
            reason = STRANDED_RETRY
        updated_at = _parse_strapi_ts(doc.get("updatedAt"))
        stranded.append(
            {
                "slug": slug,
                "reason": reason,
                "attempts": tries,
                "ageSeconds": (
                    round((now - updated_at).total_seconds(), 1)
                    if updated_at is not None
                    else None
                ),
                "error": _one_line(error),
            }
        )

    return stranded


def _stranded_detail(rec: dict) -> str:
    """One-line human reason for a stranded topic (the '  ! stranded:' lines)."""
    reason = rec.get("reason")
    age = rec.get("ageSeconds")
    if reason == STRANDED_VERDICT:
        return (
            "no lastError — a human/policy REJECT parked it; reclaim never "
            "re-queues a verdict (review it in Strapi)"
        )
    if reason == STRANDED_ARTICLE:
        return "an article already exists for this slug — a re-draft would duplicate it"
    if reason == STRANDED_EXHAUSTED:
        return (
            f"reclaim attempts exhausted ({rec.get('attempts')}/"
            f"{FAILED_RETRY_MAX_ATTEMPTS}) — the same error keeps coming back: "
            f"{rec.get('error')}"
        )
    idle = f", idle {age:.0f}s" if isinstance(age, (int, float)) else ""
    return (
        f"failed inside the reclaim cooling-off window{idle} — reclaim retries it "
        f"on a later run: {rec.get('error')}"
    )


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


def _fit_title(title: str | None, limit: int = TITLE_MAX_CHARS) -> str:
    """Fit a seed topic title into the article's title cap, on a word boundary.

    Strapi caps `article.title` at 70 chars (src/api/article/content-types/
    article/schema.json) while the seed `topic.title` is unbounded, so a long
    seed 400s the whole draft at `create_article` ("title must be at most 70
    characters") and strands the topic in `failed` — which `list_pending_topics`
    (= status pending) can never pick up again. Live case: get-paid-freelancer-
    abroad, 71 chars, 2026-09-22 (t_22a3bbdc).

    Order: drop SEO-filler parentheticals ("... (Invoices + Payment Rails)")
    when that alone fits, else truncate on the last whole word. A non-empty
    input never yields an empty string.
    """
    t = " ".join((title or "").split())
    if len(t) <= limit:
        return t
    without_parens = " ".join(re.sub(r"\s*\([^)]*\)", " ", t).split())
    if without_parens and len(without_parens) <= limit:
        return without_parens
    cut = t[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    cut = cut.rstrip(" -–—:;,.")
    return cut or t[:limit]


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

    # Title cap (t_22a3bbdc): the article's title is the SEED topic title, and the
    # articles schema caps that field at 70 chars while the topics table does not
    # — an unfitted long seed 400s the whole draft here, after every paid stage.
    article_title = _fit_title(topic["title"])
    slug_out = _yearless_slug(topic["slug"])
    # Ratified E: the write itself requires a non-empty excerpt and meta, a
    # yearless slug, and two real citations. A failure is not published.
    # The citations are counted in the BODY (the same input the publish lane
    # reads) and topped up from the article's own research facts when the writer
    # did not inline them — one gate, one implementation, so a drafted article
    # can never clear the write check and then be unpublishable forever
    # (live 2026-09-25: 8 non-quarantine in_review rows, 0 with two citations).
    body_markdown = ensure_body_citations(to_score.markdown, research.facts)
    write_errors = article_invariant_errors(
        {
            "excerpt": seo.excerpt,
            "metaTitle": seo.meta_title,
            "metaDescription": seo.meta_description,
            "slug": slug_out,
            "bodyMarkdown": body_markdown,
        }
    )
    # Fact-freshness gate (t_00bfe56f): surface the freshness signal on the
    # write path too — the article's rule-anchored money figures and which of
    # them lack a dated source — so a stale YMYL number is visible in the
    # drafting result, not only buried in the stored confidence. Warnings are
    # not rejections: the hard gate stays excerpt/meta/slug/citations.
    fresh = freshness_report(body_markdown)
    if write_errors:
        client.update_topic(
            topic["documentId"],
            {"status": "failed", "lastError": "; ".join(write_errors)},
        )
        _append_state({"ts": _now_iso(), "event": "invariant_reject", "slug": slug, "errors": write_errors})
        return {
            "slug": slug,
            "title": article_title,
            "articleDocumentId": None,
            "seoScore": seo.seo_score,
            "confidence": seo.confidence,
            "decision": decision.decision.value,
            "published": False,
            "words": to_score.word_count,
            "edit_report": "",
            "invariant_errors": write_errors,
            "freshness_issues": [f"{i.kind}: {i.figure}" for i in fresh.issues],
            "freshness_penalty": fresh.penalty,
        }

    article = client.create_article(
        {
            "title": article_title,
            "slug": slug_out,
            "bodyMarkdown": body_markdown,
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

    # Publish mapping: non-sensitive AUTO_PUBLISH decisions publish once the
    # write-time invariants have passed (ratified E). Sensitive topics are
    # structurally quarantined (QUARANTINE -> never published here).
    # The policy decision is ALSO stamped onto the article (`topicDecision`,
    # 2026-09-20, t_cae3c2d2) so the publish lane can enforce the quarantine
    # gate instead of trusting the article's status alone.
    published = False
    topic_status = "in_review"
    # Art status for the journal (t_2c07d324): only the AUTO_PUBLISH branch
    # ships art, so every other path records "skipped".
    cover_status = "skipped"
    # Ratified E (2026-09-23): auto-publish when the policy says so and the
    # write-time invariants already passed. The env flag is no longer the gate.
    # Sensitive topics stay quarantined (they never take this branch). Guy
    # vetoes from the daily digest; this function does not post one.
    if decision.decision == Decision.AUTO_PUBLISH:
        # This branch IS the publish step for lane-B articles: it is the only
        # place allowed to write the published layer (status="published").
        client.update_article(
            article_id,
            {
                "status": "published",
                "publishedAt": _now_iso(),
                "topicDecision": decision.decision.value,
            },
            status="published",
        )
        topic_status = "published"
        published = True
        record_publish(
            {"ts": _now_iso(), "event": "published", "slug": slug, "lane": "draft"},
            PUBLISH_LEDGER,
        )
        # Ship art with the article (t_2c07d324): this lane publishes without
        # the 13:00 runner, which is the only other place covers are made.
        cover_status = _ship_cover_art(client, slug, article_title)
    elif decision.decision == Decision.REJECT:
        topic_status = "failed"
        # Article was just created as a draft and is never published here, so
        # the enum flip belongs on the DRAFT layer (explicit, not inherited).
        client.update_article(
            article_id,
            {"status": "rejected", "topicDecision": decision.decision.value},
            status="draft",
        )
    else:
        # QUARANTINE (sensitive) and NEEDS_REVIEW both land in_review for Guy.
        client.update_article(
            article_id,
            {"status": "in_review", "topicDecision": decision.decision.value},
            status="draft",
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
            # t_2c07d324: art status for lane-B publishes ("generated" |
            # "push_failed" | "failed"; absent = not auto-published).
            "cover": cover_status,
            "voiceScore": seo.voice_score,
            "factualScore": seo.factual_score,
            "freshnessPenalty": fresh.penalty,
            "freshnessIssues": len(fresh.issues),
            "edit_report": (edited.edit_report if edited else ""),
        }
    )

    # Checkpoint/resume (t_bde3d77c): LAST durable write of a successful run —
    # every state change above has landed in Strapi, so from here the item is
    # restart-safe: a later batch skips this slug instead of re-drafting it,
    # which would create a duplicate article.
    _append_state(
        {
            "ts": _now_iso(),
            "event": CHECKPOINT_EVENT,
            "slug": slug,
            "articleDocumentId": article_id,
            "topicStatus": topic_status,
            "decision": decision.decision.value,
        }
    )

    return {
        "slug": slug,
        "title": article_title,
        "articleDocumentId": article_id,
        "seoScore": seo.seo_score,
        "confidence": seo.confidence,
        "decision": decision.decision.value,
        "published": published,
        "words": to_score.word_count,
        "edit_report": (edited.edit_report if edited else ""),
        "freshness_issues": [f"{i.kind}: {i.figure}" for i in fresh.issues],
        "freshness_penalty": fresh.penalty,
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
    global _last_failed
    global _last_failed_reclaimed

    # Refuse a zero/negative limit before touching Strapi at all: no reclaim, no
    # listing, no state write, no draft. (See MIN_BATCH_LIMIT above.)
    if limit < MIN_BATCH_LIMIT:
        _last_reclaimed = []
        _last_failed_reclaimed = []
        _last_failed = []
        raise ValueError(
            f"run_batch: limit must be >= {MIN_BATCH_LIMIT} (got {limit}) — 'run-batch 0' "
            "is not a dry run (Strapi clamps pageSize=0 to one row); nothing was listed "
            "or drafted"
        )

    # Queue hygiene first: a previous run killed mid-topic left its topic in
    # researching/drafting, which list_pending_topics() can never see again; a
    # previous run that died on a transient error left its topic in `failed`,
    # which is terminal for that reader — both are restored to `pending` here,
    # before the queue is listed, so this run can use them.
    _last_reclaimed = reclaim_stale_topics(client) if reclaim else []
    _last_failed_reclaimed = reclaim_failed_topics(client) if reclaim else []
    _last_failed = []

    topics = client.list_pending_topics(limit=limit)
    if not topics:
        return []
    results = []
    batch_started = time.monotonic()
    skipped: list[dict] = []
    # Checkpoint/resume (t_bde3d77c): finished-by-a-previous-run slugs are
    # skipped BEFORE the deadline gate — a skip costs no guard time, so it must
    # not count against (or be blocked by) the batch deadline.
    completed = _completed_slugs()
    resumed: list[str] = []
    for topic_doc in topics:
        slug = _attrs(topic_doc).get("slug")
        if not slug:
            continue
        if slug in completed:
            resumed.append(slug)
            _append_state(
                {
                    "ts": _now_iso(),
                    "event": RESUME_EVENT,
                    "slug": slug,
                    "reason": "checkpoint_article_completed",
                }
            )
            continue
        # Deadline awareness (t_02673f32): once the remaining guard time can no
        # longer fit a worst-case topic, stop STARTING new work and hand the
        # caller a clean partial-result summary — never a guard SIGKILL
        # mid-item. The skipped topic stays pending and is picked up next run.
        remaining_guard = BATCH_GUARD_SECONDS - BATCH_SAFETY_SECONDS - (time.monotonic() - batch_started)
        if remaining_guard < WORST_TOPIC_SECONDS:
            note = (
                f"  ~ batch deadline awareness: {remaining_guard:.0f}s of guard left "
                f"< worst-case topic {WORST_TOPIC_SECONDS:.0f}s — deferring '{slug}' "
                "(stays pending for the next run)"
            )
            print(note, file=sys.stderr)
            _append_state(
                {
                    "ts": _now_iso(),
                    "event": "batch_deadline_defer",
                    "slug": slug,
                    "remainingGuardSeconds": round(remaining_guard, 1),
                    "worstTopicSeconds": WORST_TOPIC_SECONDS,
                }
            )
            skipped.append({"slug": slug, "reason": "batch_deadline"})
            continue
        try:
            results.append(draft_one(client, cfg, slug))
        except Exception as e:
            _last_failed.append(
                {"slug": slug, "error": f"{type(e).__name__}: {e}"}
            )
            print(f"  !! {slug}: failed ({e})", file=sys.stderr)
    if skipped:
        print(
            f"  ~ deferred {len(skipped)} topic(s) on the batch deadline: "
            + ", ".join(s["slug"] for s in skipped),
            file=sys.stderr,
        )
    if resumed:
        # stderr only: stdout line 1 must stay the batch summary and the '  - '
        # rows the article list (the cron entrypoint's grep contract), and the
        # '  ~ ' prefix keeps the notice out of every article-row grep.
        print(
            f"  ~ checkpoint resume: skipped {len(resumed)} completed topic(s): "
            + ", ".join(resumed),
            file=sys.stderr,
        )
    return results


def last_reclaimed() -> list[dict]:
    """Reclaim records produced by the most recent run_batch() in this process.

    Kept out of run_batch's return value (dashboards iterate it) and out of
    run_batch's own stdout: the cron entrypoint reads the FIRST line of output as
    the batch summary, so the reclaim notice is printed by main() after it.
    """
    return list(_last_reclaimed)


def last_failed_reclaimed() -> list[dict]:
    """Re-queued `failed` topics from the most recent run_batch() in this process.

    Same contract as last_reclaimed(): kept out of run_batch's return value and
    out of its stdout because the cron entrypoint reads the FIRST line of output
    as the batch summary, so main() prints the notice after it.
    """
    return list(_last_failed_reclaimed)


def last_failed() -> list[dict]:
    """Per-topic hard failures from the most recent run_batch() in this process.

    Same reporting channel as last_reclaimed(): main() prints one reason line
    per failure after the batch summary and exits non-zero when a batch that
    attempted topics produced nothing (PANT-161, t_b3949432)."""
    return list(_last_failed)


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
            # Parked-backlog check (t_79196ced — PANT-173 residual). Only a run
            # that attempted NOTHING can be idle *because of* a `failed` backlog:
            # a run whose own failures explain the 0 has the more precise
            # PANT-161 diagnostic below, so the two paths never both fire and the
            # pinned line 1 of the all-attempted-failed case is unchanged.
            stranded = (
                []
                if results or last_failed()
                else stranded_failed_topics(client, reclaimed=last_failed_reclaimed())
            )
            if stranded:
                # Deliberately NOT the drained-queue wording: the cron wrapper
                # greps "Processed 0 topic" to mean "nothing to do", which is a
                # lie while supply sits parked in `failed` (the 09-24 freeze was
                # reported exactly that way). Line 1 carries the ⚠️ verdict and
                # the exit code below makes it authoritative.
                print(
                    f"⚠️ Processed 0 topic(s) — {len(stranded)} topic(s) parked in "
                    "`failed`: backlog reclaim cannot fix (see '  ! stranded:' lines)"
                )
            else:
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
            # Same marker, distinct event: a topic re-queued out of a transient
            # `failed` verdict. Printed with the error that stranded it, because
            # a re-queue that keeps repeating is itself the signal (attempt N of
            # FAILED_RETRY_MAX_ATTEMPTS, then it stays failed for good).
            for rec in last_failed_reclaimed():
                print(
                    f'  ~ requeued failed topic {rec["slug"]} '
                    f'(idle {rec["ageSeconds"]:.0f}s, attempt {rec["attempt"]}): '
                    f'{rec["error"]}'
                )
            # PANT-161 (t_b3949432): a batch that ATTEMPTED topics and drafted
            # nothing must not read as "queue drained — nothing to do". Every
            # hard failure gets an explicit reason line; when that is the whole
            # outcome the batch FAILS (exit 1) so the cron lane reports the dead
            # chain instead of a drained queue. Genuinely empty queue and
            # all-deferred batches keep exit 0 — nothing was attempted, so
            # there is nothing to retry later.
            for f in last_failed():
                print(f'  ! failed: {f["slug"]} — {f["error"]}')
            # One reason line per parked topic, same '  ! ' family as the failure
            # lines (so no '  - ' article-row grep can match them) but a distinct
            # 'stranded:' label — the cron wrapper keys its all-attempted-failed
            # message off '  ! failed:' and must not confuse the two.
            for s in stranded:
                print(
                    f'  ! stranded: {s["slug"]} — {s["reason"]}: '
                    f'{_stranded_detail(s)}'
                )
            if not results and last_failed():
                print(
                    "  batch drafted 0 topic(s): every attempted topic failed "
                    "(see '  ! failed:' lines above) — check hop health, then re-run",
                    file=sys.stderr,
                )
                return 1
            if stranded:
                # The cron wrapper turns a non-zero exit into its FAILED lane
                # (the drained-queue branch is only reachable at exit 0), so the
                # parked backlog is reported instead of a false "nothing to do".
                print(
                    f"  batch processed 0 topic(s) while {len(stranded)} topic(s) "
                    "are parked in `failed` — the queue is NOT drained: inspect "
                    "them in Strapi (topics, status=failed), clear them by hand "
                    "(or leave them for the reclaim window), then re-run",
                    file=sys.stderr,
                )
                return 1
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
                from publish import (
                    PUBLIC_CARDS,
                    PUBLIC_OG,
                    is_quarantined,
                    journal_quarantined_docids,
                    record_release_approval,
                )

                journal = journal_quarantined_docids()
                if is_quarantined(article, journal):
                    # Explicit human release: flip the server-side field (when the
                    # field carries quarantine) AND write the durable approval
                    # ledger so the publish lane treats this article as released
                    # regardless of the draft journal (legacy rows have no field
                    # to flip).
                    if decision == "quarantine":
                        # The article is already PUBLISHED (that's why release
                        # exists) — a bare PUT would write through and re-stamp
                        # publishedAt (t_60ad2c8e). Pin the draft layer.
                        client.update_article(
                            doc_id, {"topicDecision": "needs_review"}, status="draft"
                        )
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
                    # Pre-publish art warning (kanban t_e8a369fc, 2026-09-23).
                    # `release` never publishes; the operator does, and when that
                    # write is made by hand it bypasses BOTH lanes that generate
                    # cover art (the 13:00 runner's publish_one and the draft
                    # lane's AUTO_PUBLISH branch). Two articles went live with a
                    # 404 og:image exactly that way — the release approval is the
                    # last moment the engine sees the article before it ships,
                    # so this is where a missing cover is still fixable.
                    art_missing = [
                        path.name
                        for path in (PUBLIC_CARDS / f"{release_slug}.png",
                                     PUBLIC_OG / f"{release_slug}.png")
                        if not path.exists()
                    ]
                    if art_missing:
                        print(
                            f"⚠️  release: cover art MISSING for {release_slug} "
                            f"({', '.join(art_missing)}) — publishing now ships an "
                            "og:image that 404s. Generate + ship it first: "
                            f"`python3 ~/.hermes/scripts/nomadomics_backfill_covers.py "
                            f"--slugs {release_slug}` (verify the headline spelling on "
                            "the generated art), then commit and push the PNGs."
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
