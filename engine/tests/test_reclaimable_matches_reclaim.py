"""Conformance test: reclaimable_failed_topics() mirrors reclaim_failed_topics().

The 11:30 retry guard (PANT-185, kanban t_367b9040) needs a READ-ONLY answer to
"would the next batch have supply?" — the topics the 09:00 all-failed morning
parked in `failed` are invisible to list_pending_topics() (status=pending only),
so a plain pending count would never fire the retry. reclaimable_failed_topics()
applies the SAME four-safety selection as reclaim_failed_topics() but returns the
candidates without any PUT or journal write.

This file pins the mirror to the writer: for every input shape (transient, young,
policy REJECT, article already written, attempts exhausted, undatable), both
functions must select the exact same slug set, and the read-only twin must never
write — no update_topic call, no journal line.
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline_cli  # noqa: E402
from pipeline_cli import (  # noqa: E402
    FAILED_RECLAIM_EVENT,
    FAILED_RETRY_SECONDS,
    reclaim_failed_topics,
    reclaimable_failed_topics,
)

NOW = dt.datetime(2026, 9, 28, 6, 30, 0, tzinfo=dt.timezone.utc)  # 09:30 IDT


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    """Never touch the real engine/state/pipeline.jsonl from tests."""
    monkeypatch.setattr(pipeline_cli, "STATE_FILE", tmp_path / "pipeline.jsonl")


def failed_row(slug, age_seconds, *, last_error: "str | None" = "draft: hop -> HTTP 404", updated=None):
    """A Strapi v5 topic doc parked in `failed`, aged against fixed NOW (UTC)."""
    ts = (updated or (NOW - dt.timedelta(seconds=age_seconds))).isoformat()
    row = {"documentId": f"doc-{slug}", "slug": slug, "status": "failed",
           "updatedAt": ts}
    if last_error is not None:
        row["lastError"] = last_error
    return row


class FakeStrapi:
    """Duck-typed StrapiClient: records calls, never touches real Strapi."""

    def __init__(self, failed=()):
        self.failed = list(failed)
        self.calls = []
        self.updates = []

    def list_inflight_topics(self, statuses, *, updated_before=None, limit=100):
        self.calls.append("list_inflight")
        if tuple(statuses) != tuple(pipeline_cli.FAILED_STATUSES):
            return []
        # Mirror the live client's server-side updated_before filter. A row we
        # cannot parse passes through untouched: the real Strapi decides, and
        # the engine's _parse_strapi_ts() fail-safe handles a bad timestamp.
        out = []
        for row in self.failed:
            try:
                ts = dt.datetime.fromisoformat(row["updatedAt"].replace("Z", "+00:00"))
            except ValueError:
                out.append(row)
                continue
            if updated_before is None or ts < dt.datetime.fromisoformat(updated_before):
                out.append(row)
        return out

    def update_topic(self, doc_id, fields):
        self.calls.append("update_topic")
        self.updates.append((doc_id, fields))


def write_journal(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def run_pair(client, journal):
    """Both functions over the same inputs; returns (mirror, writer)."""
    mirror = reclaimable_failed_topics(client, now=NOW, state_file=journal)
    writer = reclaim_failed_topics(client, now=NOW, state_file=journal)
    return mirror, writer


def slugs(items):
    return sorted(i["slug"] for i in items)


def test_transient_old_enough_selected_by_both(tmp_path):
    """The PANT-185 morning shape: 09:00 failures idle >1h are reclaimable."""
    journal = tmp_path / "pipeline.jsonl"
    write_journal(journal, [])
    client = FakeStrapi(failed=[
        failed_row("coliving-vs-apartment-rental-digital-nomads", age_seconds=7200),
        failed_row("currency-risk-for-digital-nomads", age_seconds=7200),
    ])
    mirror, writer = run_pair(client, journal)

    assert slugs(mirror) == ["coliving-vs-apartment-rental-digital-nomads",
                             "currency-risk-for-digital-nomads"]
    assert slugs(writer) == slugs(mirror)
    # The mirror must have made NO write; the writer reclaimed both.
    assert client.updates == [("doc-coliving-vs-apartment-rental-digital-nomads",
                               {"status": "pending"}),
                              ("doc-currency-risk-for-digital-nomads",
                               {"status": "pending"})]


def test_mirror_is_read_only(tmp_path):
    """reclaimable_failed_topics() must never PUT or append a journal row."""
    journal = tmp_path / "pipeline.jsonl"
    write_journal(journal, [])
    client = FakeStrapi(failed=[failed_row("topic-a", age_seconds=7200)])

    reclaimable_failed_topics(client, now=NOW, state_file=journal)

    assert "update_topic" not in client.calls
    assert journal.read_text(encoding="utf-8") == ""  # nothing appended


def test_too_young_selected_by_neither(tmp_path):
    """A failure inside the 3600s cooling-off window is not supply yet."""
    journal = tmp_path / "pipeline.jsonl"
    write_journal(journal, [])
    client = FakeStrapi(failed=[failed_row("topic-young", age_seconds=60)])

    mirror, writer = run_pair(client, journal)

    assert slugs(mirror) == []
    assert slugs(writer) == []
    assert client.updates == []


def test_policy_reject_selected_by_neither(tmp_path):
    """A REJECT lands `failed` with no lastError: a verdict, never re-queued."""
    journal = tmp_path / "pipeline.jsonl"
    write_journal(journal, [])
    client = FakeStrapi(failed=[failed_row("topic-rejected", age_seconds=7200,
                                           last_error=None)])

    mirror, writer = run_pair(client, journal)

    assert slugs(mirror) == []
    assert slugs(writer) == []
    assert client.updates == []


def test_article_already_written_selected_by_neither(tmp_path):
    """A slug with an article_created row must never be re-drafted."""
    journal = tmp_path / "pipeline.jsonl"
    write_journal(journal, [
        {"ts": "2026-09-28T05:00:00+00:00", "event": "article_created",
         "slug": "topic-done", "decision": "auto_publish", "confidence": 95},
    ])
    client = FakeStrapi(failed=[failed_row("topic-done", age_seconds=7200)])

    mirror, writer = run_pair(client, journal)

    assert slugs(mirror) == []
    assert slugs(writer) == []
    assert client.updates == []


def test_attempts_exhausted_selected_by_neither(tmp_path):
    """A topic past FAILED_RETRY_MAX_ATTEMPTS reclaims stops burning budget."""
    journal = tmp_path / "pipeline.jsonl"
    # _journal_slug_counts() counts reclaim_failed ROWS, so two prior reclaims
    # = two rows (one per re-queue), matching the real journal's shape.
    write_journal(journal, [
        {"ts": "2026-09-27T06:00:00+00:00", "event": FAILED_RECLAIM_EVENT,
         "slug": "topic-broken", "attempt": 1},
        {"ts": "2026-09-27T07:00:00+00:00", "event": FAILED_RECLAIM_EVENT,
         "slug": "topic-broken", "attempt": 2},
    ])
    client = FakeStrapi(failed=[failed_row("topic-broken", age_seconds=7200)])

    mirror, writer = run_pair(client, journal)

    assert slugs(mirror) == []
    assert slugs(writer) == []
    assert client.updates == []


def test_undatable_updated_at_selected_by_neither(tmp_path):
    """An unparseable updatedAt fails safe: nobody touches the topic."""
    journal = tmp_path / "pipeline.jsonl"
    write_journal(journal, [])
    row = failed_row("topic-undatable", age_seconds=7200)
    row["updatedAt"] = "not-a-timestamp"
    client = FakeStrapi(failed=[row])

    mirror, writer = run_pair(client, journal)

    assert slugs(mirror) == []
    assert slugs(writer) == []
    assert client.updates == []


def test_different_windows_stay_in_lockstep(tmp_path):
    """Overriding the cooling-off window moves both functions identically."""
    journal = tmp_path / "pipeline.jsonl"
    write_journal(journal, [])
    client = FakeStrapi(failed=[failed_row("topic-mid", age_seconds=1800)])

    mirror = reclaimable_failed_topics(client, now=NOW, min_age_seconds=3600,
                                       state_file=journal)
    writer = reclaim_failed_topics(client, now=NOW, min_age_seconds=3600,
                                   state_file=journal)
    assert slugs(mirror) == []
    assert slugs(writer) == []

    mirror2 = reclaimable_failed_topics(client, now=NOW, min_age_seconds=300,
                                        state_file=journal)
    writer2 = reclaim_failed_topics(client, now=NOW, min_age_seconds=300,
                                    state_file=journal)
    assert slugs(mirror2) == ["topic-mid"]
    assert slugs(writer2) == slugs(mirror2)


def test_guard_supply_semantics(tmp_path):
    """The guard's 'queue non-empty' = pending + reclaimable failed, both paths."""
    journal = tmp_path / "pipeline.jsonl"
    write_journal(journal, [])

    # PANT-185 morning: 0 pending, 2 reclaimable -> supply is non-empty.
    client = FakeStrapi(failed=[failed_row("topic-a", age_seconds=7200),
                                failed_row("topic-b", age_seconds=7200)])
    reclaimable = reclaimable_failed_topics(client, now=NOW, state_file=journal)
    assert len(reclaimable) == 2  # queue is NOT empty
    assert reclaimable[0]["attempt"] == 1

    # Drained morning: 0 pending, 0 reclaimable -> nothing to retry.
    empty = FakeStrapi(failed=[])
    assert reclaimable_failed_topics(empty, now=NOW, state_file=journal) == []