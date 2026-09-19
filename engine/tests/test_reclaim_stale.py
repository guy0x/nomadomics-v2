"""Tests for the stale in-flight topic reclaim (pipeline_cli.reclaim_stale_topics).

A run killed mid-topic leaves its topic in `researching`/`drafting`; those rows are
invisible to `list_pending_topics()` (status=pending only), so without the reclaim
the queue silently runs short forever. These tests pin the three safety rules:
stale -> pending, fresh -> untouched, article already written -> untouched.
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
    INFLIGHT_STATUSES,
    STALE_INFLIGHT_SECONDS,
    TOPIC_BUDGET_SECONDS,
    reclaim_stale_topics,
)

NOW = dt.datetime(2026, 9, 18, 12, 0, 0, tzinfo=dt.timezone.utc)


def _utcnow():
    return dt.datetime.now(dt.timezone.utc)


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    """Never touch the real engine/state/pipeline.jsonl from tests."""
    monkeypatch.setattr(pipeline_cli, "STATE_FILE", tmp_path / "pipeline.jsonl")


def row(slug, status, age_seconds, document_id=None, base=NOW):
    """A Strapi v5 topic row — fields FLAT (verified against live Strapi)."""
    ts = (base - dt.timedelta(seconds=age_seconds)).isoformat().replace("+00:00", "Z")
    return {
        "documentId": document_id or f"doc-{slug}",
        "slug": slug,
        "status": status,
        "updatedAt": ts,
    }


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

    assert client.calls == ["list_inflight", "update_topic", "list_pending"]
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
    assert client.calls == ["list_inflight", "list_pending"]
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
