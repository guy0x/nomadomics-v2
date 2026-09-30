"""Tests for the topic-supply reclaims in pipeline_cli.

Two failure modes strand a topic where `list_pending_topics()` (status=pending
only) can never see it again, so without a reclaim the queue silently runs short
forever:

  * a run killed mid-topic leaves it in `researching`/`drafting`
    -> reclaim_stale_topics (stale -> pending, fresh -> untouched, article
       already written -> untouched);
  * a stage that dies on a TRANSIENT error leaves it in `failed`, which is
    terminal for the reclaim above -> reclaim_failed_topics (2026-09-25,
    PANT-173: five topics stranded that way took the pending queue to 0 and the
    09-24 batch drafted nothing).

This file pins the safety rules of both: stale -> pending, fresh -> untouched,
article already written -> untouched, and for the failure reclaim: transient
verdict only (never a policy REJECT), never a slug with an article, cooling-off
window honoured, retry attempts capped.
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline_cli  # noqa: E402
from config import Config  # noqa: E402
from pipeline_cli import (  # noqa: E402
    FAILED_RETRY_MAX_ATTEMPTS,
    FAILED_RETRY_SECONDS,
    FAILED_STATUSES,
    INFLIGHT_STATUSES,
    STALE_INFLIGHT_SECONDS,
    TOPIC_BUDGET_SECONDS,
    reclaim_failed_topics,
    reclaim_stale_topics,
)

NOW = dt.datetime(2026, 9, 18, 12, 0, 0, tzinfo=dt.timezone.utc)


def _utcnow():
    return dt.datetime.now(dt.timezone.utc)


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    """Never touch the real engine/state/pipeline.jsonl from tests."""
    monkeypatch.setattr(pipeline_cli, "STATE_FILE", tmp_path / "pipeline.jsonl")


def row(slug, status, age_seconds, document_id=None, base=NOW, last_error=None):
    """A Strapi v5 topic row — fields FLAT (verified against live Strapi)."""
    ts = (base - dt.timedelta(seconds=age_seconds)).isoformat().replace("+00:00", "Z")
    out = {
        "documentId": document_id or f"doc-{slug}",
        "slug": slug,
        "status": status,
        "updatedAt": ts,
    }
    if last_error is not None:
        out["lastError"] = last_error
    return out


class FakeInflightStrapi:
    """Duck-typed StrapiClient that can over-return rows on purpose."""

    def __init__(self, inflight=(), pending=()):
        self.inflight = list(inflight)
        self.pending = list(pending)
        self.calls = []
        self.inflight_params = None
        self.updates = []

    def list_inflight_topics(self, statuses, *, updated_before=None, limit=100):
        self.calls.append("list_inflight")
        self.inflight_params = {
            "statuses": tuple(statuses),
            "updated_before": updated_before,
            "limit": limit,
        }
        return list(self.inflight)

    def list_pending_topics(self, limit=5):
        self.calls.append("list_pending")
        return list(self.pending)

    def update_topic(self, doc_id, fields):
        self.calls.append("update_topic")
        self.updates.append((doc_id, fields))

    def close(self):
        pass


def journal(*entries):
    path = pipeline_cli.STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def journal_entries():
    path = pipeline_cli.STATE_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def make_cfg():
    return Config(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="key",
    )


# --- threshold arithmetic ----------------------------------------------------

def test_threshold_sits_between_topic_budget_and_cron_cap():
    """The reclaim window must exceed the worst-case topic budget (else a live run
    loses its topic) and stay under the cron tree-kill cap (3600s)."""
    assert STALE_INFLIGHT_SECONDS == TOPIC_BUDGET_SECONDS * 2 == 1800.0
    assert STALE_INFLIGHT_SECONDS > TOPIC_BUDGET_SECONDS
    assert STALE_INFLIGHT_SECONDS < 3600.0


def test_inflight_statuses_exclude_terminal_ones():
    assert set(INFLIGHT_STATUSES) == {"researching", "drafting"}
    for terminal in ("in_review", "failed", "published"):
        assert terminal not in INFLIGHT_STATUSES
        assert terminal in pipeline_cli.TERMINAL_STATUSES


# --- core behaviour ----------------------------------------------------------

def test_stale_inflight_topic_is_reclaimed_fresh_one_is_untouched():
    client = FakeInflightStrapi([
        row("stale-drafting", "drafting", 7200),      # killed 2h ago
        row("fresh-drafting", "drafting", 30),        # run still inside its budget
        row("stale-researching", "researching", 1810),  # just past the threshold
    ])

    reclaimed = reclaim_stale_topics(client, now=NOW)

    assert [r["slug"] for r in reclaimed] == ["stale-drafting", "stale-researching"]
    assert client.updates == [
        ("doc-stale-drafting", {"status": "pending"}),
        ("doc-stale-researching", {"status": "pending"}),
    ]
    events = journal_entries()
    assert [e["event"] for e in events] == ["reclaim_stale", "reclaim_stale"]
    assert events[0]["from"] == "drafting"
    assert events[0]["to"] == "pending"
    assert events[0]["ageSeconds"] == 7200.0
    assert events[1]["from"] == "researching"


def test_topic_inside_its_budget_window_is_never_touched():
    """Negative control: 1s and 1799s idle rows stay put (a live run owns them)."""
    client = FakeInflightStrapi([
        row("just-started", "researching", 1),
        row("mid-stage", "drafting", 899),
        row("one-second-short", "drafting", STALE_INFLIGHT_SECONDS - 1),
    ])

    assert reclaim_stale_topics(client, now=NOW) == []
    assert client.updates == []
    assert journal_entries() == []


def test_slug_with_article_created_is_never_reset():
    """A duplicate article is worse than a leaked topic: skip it, journal why."""
    journal(
        {"event": "article_created", "slug": "already-written", "articleDocumentId": "a-1"},
        {"event": "research_ok", "slug": "no-article-here"},
    )
    client = FakeInflightStrapi([row("already-written", "drafting", 99999)])

    assert reclaim_stale_topics(client, now=NOW) == []
    assert client.updates == []
    events = journal_entries()
    assert events[-1] == {
        "ts": events[-1]["ts"],
        "event": "reclaim_skipped",
        "slug": "already-written",
        "reason": "article_created",
        "from": "drafting",
        "ageSeconds": 99999.0,
    }


def test_terminal_status_row_returned_by_a_widened_query_is_ignored():
    """Defence in depth: even if the query ever over-returns, terminal rows are safe."""
    client = FakeInflightStrapi([
        row("reviewed", "in_review", 999999),
        row("done", "published", 999999),
        row("verdict", "failed", 999999),
    ])

    assert reclaim_stale_topics(client, now=NOW) == []
    assert client.updates == []
    assert journal_entries() == []


def test_undatable_updated_at_fails_safe():
    client = FakeInflightStrapi([
        {"documentId": "doc-x", "slug": "no-timestamp", "status": "drafting"},
        {"documentId": "doc-y", "slug": "garbage-ts", "status": "drafting", "updatedAt": "not-a-date"},
    ])

    assert reclaim_stale_topics(client, now=NOW) == []
    assert client.updates == []


def test_row_without_document_id_is_not_put_to():
    client = FakeInflightStrapi([
        {"slug": "idless", "status": "drafting", "updatedAt": NOW.isoformat()},
    ])

    assert reclaim_stale_topics(client, now=NOW) == []
    assert client.updates == []


def test_query_asks_only_for_inflight_statuses_and_passes_the_cutoff():
    client = FakeInflightStrapi([])

    reclaim_stale_topics(client, now=NOW)

    params = client.inflight_params
    assert params["statuses"] == INFLIGHT_STATUSES
    cutoff = dt.datetime.fromisoformat(params["updated_before"])
    assert cutoff == NOW - dt.timedelta(seconds=STALE_INFLIGHT_SECONDS)


def test_torn_journal_line_does_not_break_the_guard(tmp_path):
    """A killed run can leave a truncated final line — must not raise."""
    path = pipeline_cli.STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"event": "article_created", "slug": "written"}\n{"event": "article_cre'
    )
    client = FakeInflightStrapi([row("written", "drafting", 99999)])

    assert reclaim_stale_topics(client, now=NOW) == []
    assert client.updates == []


def test_threshold_override_is_honoured():
    client = FakeInflightStrapi([row("young", "drafting", 60)])

    reclaimed = reclaim_stale_topics(client, now=NOW, threshold_seconds=10)

    assert [r["slug"] for r in reclaimed] == ["young"]
    assert client.updates == [("doc-young", {"status": "pending"})]


# --- stranded `failed` reclaim (PANT-173) ------------------------------------

def test_failed_constants_are_pinned():
    assert FAILED_STATUSES == ("failed",)
    assert FAILED_RETRY_SECONDS == 3600.0
    assert FAILED_RETRY_MAX_ATTEMPTS == 2
    for status in FAILED_STATUSES:
        assert status in pipeline_cli.TERMINAL_STATUSES  # why this reclaim exists


def test_transiently_failed_topic_is_requeued():
    client = FakeInflightStrapi([
        row("dead-hop", "failed", 7200, last_error="draft: hop -> HTTP 404"),
    ])

    reclaimed = reclaim_failed_topics(client, now=NOW)

    assert [r["slug"] for r in reclaimed] == ["dead-hop"]
    assert reclaimed[0]["from"] == "failed"
    assert reclaimed[0]["attempt"] == 1
    assert reclaimed[0]["error"] == "draft: hop -> HTTP 404"
    assert client.updates == [("doc-dead-hop", {"status": "pending"})]
    events = journal_entries()
    assert [e["event"] for e in events] == ["reclaim_failed"]
    assert events[0]["to"] == "pending"
    assert events[0]["documentId"] == "doc-dead-hop"
    assert events[0]["attempt"] == 1
    assert client.inflight_params["statuses"] == FAILED_STATUSES


def test_failed_topic_without_last_error_is_never_requeued():
    """A policy REJECT also lands `failed` but sets no lastError — a verdict is
    not an error and must never be re-drafted."""
    client = FakeInflightStrapi([row("rejected", "failed", 999999)])

    assert reclaim_failed_topics(client, now=NOW) == []
    assert client.updates == []
    assert journal_entries() == []


def test_failed_topic_with_an_article_is_skipped_and_journalled():
    journal({"event": "article_created", "slug": "written", "articleDocumentId": "a-1"})
    client = FakeInflightStrapi([
        row("written", "failed", 99999, last_error="write: strapi 500"),
    ])

    assert reclaim_failed_topics(client, now=NOW) == []
    assert client.updates == []
    events = journal_entries()
    assert events[-1]["event"] == "reclaim_skipped"
    assert events[-1]["reason"] == "article_created"
    assert events[-1]["from"] == "failed"


def test_failed_topic_inside_cooling_off_window_is_untouched():
    client = FakeInflightStrapi([
        row("just-failed", "failed", 60, last_error="draft: hop -> HTTP 429"),
    ])

    assert reclaim_failed_topics(client, now=NOW) == []
    assert client.updates == []
    assert journal_entries() == []


def test_failed_retry_attempts_are_capped_and_journalled_once():
    journal(
        {"event": "reclaim_failed", "slug": "broken", "attempt": 1},
        {"event": "reclaim_failed", "slug": "broken", "attempt": 2},
    )
    client = FakeInflightStrapi([
        row("broken", "failed", 99999, last_error="draft: hop -> HTTP 404"),
    ])

    assert reclaim_failed_topics(client, now=NOW) == []
    assert client.updates == []
    events = journal_entries()
    assert [e["event"] for e in events] == ["reclaim_failed", "reclaim_failed", "reclaim_exhausted"]
    assert events[-1]["attempts"] == FAILED_RETRY_MAX_ATTEMPTS
    # a second run must not append the same exhausted row again
    assert reclaim_failed_topics(client, now=NOW) == []
    assert [e["event"] for e in journal_entries()][-1] == "reclaim_exhausted"


def test_failed_reclaim_attempt_cap_override_is_honoured():
    journal({"event": "reclaim_failed", "slug": "one-try-down"})
    client = FakeInflightStrapi([
        row("one-try-down", "failed", 99999, last_error="draft: hop -> HTTP 404"),
    ])

    assert reclaim_failed_topics(client, now=NOW, max_attempts=1) == []
    assert client.updates == []


def test_failed_reclaim_ignores_other_statuses_even_when_over_returned():
    """Defence in depth: `list_inflight_topics` is status-filtered, but a widened
    query (or a race) must never let this touch a non-`failed` row."""
    client = FakeInflightStrapi([
        row("inflight", "drafting", 99999, last_error="draft: hop -> HTTP 404"),
        row("done", "published", 99999, last_error="draft: hop -> HTTP 404"),
    ])

    assert reclaim_failed_topics(client, now=NOW) == []
    assert client.updates == []


def test_failed_reclaim_fails_safe_on_junk_rows():
    client = FakeInflightStrapi([
        {"slug": "no-doc", "status": "failed", "lastError": "x", "updatedAt": NOW.isoformat()},
        {"documentId": "d", "slug": "no-ts", "status": "failed", "lastError": "x"},
        {"documentId": "d2", "slug": "bad-ts", "status": "failed", "lastError": "x",
         "updatedAt": "not-a-date"},
    ])

    assert reclaim_failed_topics(client, now=NOW) == []
    assert client.updates == []


def test_journal_slug_counts_counts_per_slug_and_tolerates_torn_line():
    journal(
        {"event": "reclaim_failed", "slug": "a"},
        {"event": "reclaim_failed", "slug": "a"},
        {"event": "reclaim_failed", "slug": "b"},
        {"event": "research_ok", "slug": "a"},
    )
    path = pipeline_cli.STATE_FILE
    path.write_text(path.read_text() + '{"event": "reclaim_fai')

    counts = pipeline_cli._journal_slug_counts(None, "reclaim_failed")

    assert counts == {"a": 2, "b": 1}


def test_run_batch_requeues_failed_topics_before_listing(monkeypatch):
    """The re-queued topic must be back in the queue for THIS run, not the next."""
    base = _utcnow()
    failed_row = dict(
        row("was-failed", "failed", 7200, base=base, last_error="draft: hop -> HTTP 404"),
        title="Requeued",
    )
    client = FakeInflightStrapi(
        [failed_row],
        pending=[{"documentId": "doc-was-failed", "slug": "was-failed"}],
    )
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: {"slug": slug, "title": "Requeued", "confidence": 70,
                              "decision": "needs_review", "published": False},
    )

    results = pipeline_cli.run_batch(client, make_cfg(), 2)

    assert client.updates == [("doc-was-failed", {"status": "pending"})]
    assert [r["slug"] for r in results] == ["was-failed"]
    assert pipeline_cli.last_reclaimed() == []
    requeued = pipeline_cli.last_failed_reclaimed()
    assert [r["slug"] for r in requeued] == ["was-failed"]
    assert requeued[0]["from"] == "failed"
    assert requeued[0]["attempt"] == 1


def test_run_batch_failed_reclaim_can_be_disabled():
    client = FakeInflightStrapi([row("stranded", "failed", 99999, last_error="draft: 404")])

    pipeline_cli.run_batch(client, make_cfg(), 2, reclaim=False)

    assert client.updates == []
    assert pipeline_cli.last_failed_reclaimed() == []


def test_main_prints_requeue_notice_after_the_summary(monkeypatch, capsys):
    """Cron contract: line 1 stays the batch summary and '  - ' stays reserved for
    article rows — the requeue notice must break neither."""
    client = FakeInflightStrapi(
        [row("was-failed", "failed", 7200, base=_utcnow(), last_error="draft: hop -> HTTP 404")],
        pending=[{"documentId": "doc-was-failed", "slug": "was-failed"}],
    )
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: {"slug": slug, "title": "Requeued Topic", "confidence": 71,
                              "decision": "needs_review", "published": False},
    )

    assert pipeline_cli.main(["run-batch", "2"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Processed 1 topic(s)."
    assert lines[1] == "  - Requeued Topic | conf=71 | needs_review"
    assert lines[2].startswith("  ~ requeued failed topic was-failed (idle ")
    assert lines[2].endswith("): draft: hop -> HTTP 404")
    assert [ln for ln in lines if ln.startswith("  - ")] == [lines[1]]


# --- batch wiring ------------------------------------------------------------

def test_run_batch_reclaims_before_listing_pending(monkeypatch):
    """The reclaimed topic must be back in the queue for THIS run, not the next."""
    # run_batch() has no injectable clock — build rows against the real one.
    base = _utcnow()
    pending_row = dict(
        row("was-drafting", "drafting", 7200, base=base),
        title="Reclaimed",
        documentId="doc-was-drafting",
    )
    client = FakeInflightStrapi(
        [pending_row],
        pending=[{"documentId": "doc-was-drafting", "slug": "was-drafting"}],
    )
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: {"slug": slug, "title": "Reclaimed", "confidence": 70,
                              "decision": "needs_review", "published": False},
    )

    results = pipeline_cli.run_batch(client, make_cfg(), 2)

    # two filtered reads now precede the listing: the in-flight reclaim and the
    # stranded-`failed` reclaim, both before list_pending_topics()
    assert client.calls == ["list_inflight", "update_topic", "list_inflight", "list_pending"]
    assert client.updates == [("doc-was-drafting", {"status": "pending"})]
    assert [r["slug"] for r in results] == ["was-drafting"]
    reclaimed = pipeline_cli.last_reclaimed()
    assert len(reclaimed) == 1
    assert reclaimed[0]["slug"] == "was-drafting"
    assert reclaimed[0]["from"] == "drafting"
    assert reclaimed[0]["ageSeconds"] >= 7200.0
    assert pipeline_cli.last_reclaimed()[0]["ageSeconds"] <= 7200.0 + 60


def test_run_batch_does_not_write_when_nothing_is_stale():
    # run_batch() has no injectable clock — the row must be aged against the real
    # one. Using the module-level NOW (2026-09-18, for the pure-function tests
    # above) would make this "5-second-old" row ~19h old in wall-clock terms and
    # correctly reclaim it, so the test would assert the opposite of its name.
    client = FakeInflightStrapi([row("live", "drafting", 5, base=_utcnow())])

    results = pipeline_cli.run_batch(client, make_cfg(), 2)

    assert results == []
    assert client.updates == []
    assert client.calls == ["list_inflight", "list_inflight", "list_pending"]
    assert pipeline_cli.last_reclaimed() == []
    assert not pipeline_cli.STATE_FILE.exists()


def test_run_batch_reclaim_can_be_disabled(monkeypatch):
    client = FakeInflightStrapi([row("stale", "drafting", 99999)])

    pipeline_cli.run_batch(client, make_cfg(), 2, reclaim=False)

    assert "list_inflight" not in client.calls
    assert client.updates == []


def test_main_prints_summary_first_then_reclaim_notice(monkeypatch, capsys):
    """Cron contract: the entrypoint reads line 1 as the batch summary and greps
    '  - ' for article rows — the reclaim notice must break neither."""
    client = FakeInflightStrapi(
        [row("was-drafting", "drafting", 7200, base=_utcnow())],
        pending=[{"documentId": "doc-was-drafting", "slug": "was-drafting"}],
    )
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: {"slug": slug, "title": "Reclaimed Topic", "confidence": 71,
                              "decision": "needs_review", "published": False},
    )

    assert pipeline_cli.main(["run-batch", "2"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Processed 1 topic(s)."
    assert lines[1] == "  - Reclaimed Topic | conf=71 | needs_review"
    assert lines[2].startswith(
        "  ~ reclaimed stale topic was-drafting (drafting, idle "
    )
    assert lines[2].endswith("s) -> pending")
    # the notice is never mistaken for an article row by the cron grep
    assert [ln for ln in lines if ln.startswith("  - ")] == [lines[1]]
