"""Tests for completing article-attached stranded topics (t_b01e56f4).

A run killed between article creation and the terminal topic flip left
schengen-90-180-rule-digital-nomads stuck in `drafting` from 2026-10-20 to
2026-10-26: reclaim_stale_topics deliberately never resets a slug with an
article_created row (no duplicate articles), but its only action was to SKIP —
so the topic sat in-flight forever, burning a reclaim_skipped row per run,
while a manual `draft-one <slug>` would have re-drafted a duplicate article
the engine token (no delete) could never remove.

This file pins the repair:
  1. reclaim completes an article-attached topic to its JOURNALED terminal
     status (reclaim_attached) and still refuses to act when the journal
     cannot vouch for a terminal status;
  2. draft_one refuses to re-draft an article that already exists (journal
     row or live working-layer lookup), completes the topic instead, and
     journals draft_skipped_duplicate — and a fresh slug still drafts.
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline_cli  # noqa: E402
from config import Config  # noqa: E402
from editor.editor import EditedDraft  # noqa: E402
from pipeline_cli import (  # noqa: E402
    CHECKPOINT_EVENT,
    reclaim_stale_topics,
)
from research.research import Fact, ResearchResult  # noqa: E402
from strapi import StrapiError  # noqa: E402
from writer.writer import ArticleDraft  # noqa: E402

NOW = dt.datetime(2026, 9, 18, 12, 0, 0, tzinfo=dt.timezone.utc)

SLUG = "schengen-90-180-rule-digital-nomads"


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    """Never touch the real engine/state/pipeline.jsonl from tests."""
    monkeypatch.setattr(pipeline_cli, "STATE_FILE", tmp_path / "pipeline.jsonl")


def make_cfg():
    return Config(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="key",
    )


def journal():
    path = pipeline_cli.STATE_FILE
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({"torn": line})
    return out


def write_journal(*entries):
    path = pipeline_cli.STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def row(slug, status, age_seconds, document_id=None, last_error=None):
    """A Strapi v5 topic row — fields FLAT (verified against live Strapi)."""
    ts = (NOW - dt.timedelta(seconds=age_seconds)).isoformat().replace("+00:00", "Z")
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
    """Duck-typed StrapiClient for reclaim tests."""

    def __init__(self, inflight=()):
        self.inflight = list(inflight)
        self.updates = []

    def list_inflight_topics(self, statuses, *, updated_before=None, limit=100):
        return [r for r in self.inflight if r.get("status") in statuses]

    def update_topic(self, doc_id, fields):
        self.updates.append((doc_id, fields))


class FakeDraftStrapi:
    """Duck-typed StrapiClient for draft_one duplicate-guard tests."""

    def __init__(self, slugs=(SLUG,), finder=None):
        self.slugs = list(slugs)
        self._finder = finder
        self.created = []
        self.topic_updates = []

    def get_topic_by_slug(self, slug):
        if slug not in self.slugs:
            return None
        return {
            "documentId": f"doc-{slug}",
            "slug": slug,
            "title": slug,
            "primaryKeyword": "kw",
            "targetKeywords": [],
            "category": "gear",
            "targetWordCount": 500,
        }

    def find_article_document_id_by_slug(self, slug):
        if self._finder is None:
            return None
        if isinstance(self._finder, Exception):
            raise self._finder
        return self._finder

    def update_topic(self, doc_id, fields):
        self.topic_updates.append((doc_id, fields))

    def create_article(self, fields):
        doc = {"documentId": f"art-{fields['slug']}", "attributes": dict(fields)}
        self.created.append(doc)
        return {"data": doc}

    def update_article(self, doc_id, fields, *, status="draft"):
        pass

    def count_published(self):
        return 0

    def list_authors(self):
        return []

    def list_published_titles(self, limit=200):
        return []

    def close(self):
        pass


@pytest.fixture
def stub_stages(monkeypatch):
    """Deterministic offline stages — no LLM, no network."""

    def research(topic, kw, config=None, **k):
        return ResearchResult(topic=topic, facts=[
            Fact(claim="Fact one.", source_url="https://e.com/1"),
            Fact(claim="Fact two.", source_url="https://e.com/2"),
            Fact(claim="Fact three.", source_url="https://e.com/3"),
        ])

    body = "# Title\n\n" + "word " * 400
    monkeypatch.setattr(pipeline_cli, "research_topic", research)
    monkeypatch.setattr(
        pipeline_cli, "validate_research", lambda r, min_facts=3: (True, [], [])
    )
    monkeypatch.setattr(
        pipeline_cli,
        "draft_article",
        lambda *a, **k: ArticleDraft(
            markdown=body, word_count=400, used_facts=["Fact one."]
        ),
    )
    monkeypatch.setattr(
        pipeline_cli,
        "edit_draft",
        lambda draft, topic, kw, research, config=None, **k: EditedDraft(
            markdown=draft.markdown,
            word_count=draft.word_count,
            used_facts=list(draft.used_facts),
            edit_report="pass",
        ),
    )


# --- 1. reclaim completes article-attached topics -------------------------------


def test_reclaim_completes_article_attached_topic_to_journaled_terminal():
    write_journal(
        {"event": "article_created", "slug": SLUG, "articleDocumentId": "art-1"},
        {"event": "research_ok", "slug": SLUG, "facts": 6},
        {"event": CHECKPOINT_EVENT, "slug": SLUG, "articleDocumentId": "art-1",
         "topicStatus": "in_review", "decision": "quarantine"},
    )
    client = FakeInflightStrapi([row(SLUG, "drafting", 99999)])

    reclaimed = reclaim_stale_topics(client, now=NOW)

    assert reclaimed == [
        {
            "slug": SLUG,
            "from": "drafting",
            "to": "in_review",
            "attached": True,
            "ageSeconds": 99999.0,
        }
    ]
    # completed to the JOURNALED terminal status, stale lastError cleared —
    # never reset to pending
    assert client.updates == [
        (f"doc-{SLUG}", {"status": "in_review", "lastError": None})
    ]
    events = journal()
    assert events[-1]["event"] == "reclaim_attached"
    assert events[-1]["to"] == "in_review"
    assert events[-1]["documentId"] == f"doc-{SLUG}"


def test_reclaim_completes_to_published_when_journal_says_published():
    write_journal(
        {"event": "article_created", "slug": SLUG, "articleDocumentId": "art-1"},
        {"event": CHECKPOINT_EVENT, "slug": SLUG, "articleDocumentId": "art-1",
         "topicStatus": "published", "decision": "auto_publish"},
    )
    client = FakeInflightStrapi([row(SLUG, "researching", 50000)])

    reclaimed = reclaim_stale_topics(client, now=NOW)

    assert reclaimed[0]["to"] == "published"
    assert client.updates == [
        (f"doc-{SLUG}", {"status": "published", "lastError": None})
    ]


def test_reclaim_without_checkpoint_verdict_still_skips():
    """No journaled terminal status -> nothing certain -> keep the old skip."""
    write_journal(
        {"event": "article_created", "slug": SLUG, "articleDocumentId": "art-1"},
    )
    client = FakeInflightStrapi([row(SLUG, "drafting", 99999)])

    assert reclaim_stale_topics(client, now=NOW) == []
    assert client.updates == []
    events = journal()
    assert events[-1]["event"] == "reclaim_skipped"
    assert events[-1]["reason"] == "article_created"


def test_reclaim_nonterminal_checkpoint_verdict_still_skips():
    """A checkpoint row that does not vouch a TERMINAL status is not a verdict."""
    write_journal(
        {"event": "article_created", "slug": SLUG, "articleDocumentId": "art-1"},
        {"event": CHECKPOINT_EVENT, "slug": SLUG, "articleDocumentId": "art-1",
         "topicStatus": "drafting", "decision": "quarantine"},
    )
    client = FakeInflightStrapi([row(SLUG, "drafting", 99999)])

    assert reclaim_stale_topics(client, now=NOW) == []
    assert client.updates == []
    assert journal()[-1]["event"] == "reclaim_skipped"


def test_reclaim_uses_last_checkpoint_verdict():
    """A slug redrafted after a publish records its LAST terminal status."""
    write_journal(
        {"event": "article_created", "slug": SLUG, "articleDocumentId": "art-1"},
        {"event": CHECKPOINT_EVENT, "slug": SLUG, "articleDocumentId": "art-1",
         "topicStatus": "published", "decision": "auto_publish"},
        {"event": "article_created", "slug": SLUG, "articleDocumentId": "art-2"},
        {"event": CHECKPOINT_EVENT, "slug": SLUG, "articleDocumentId": "art-2",
         "topicStatus": "in_review", "decision": "quarantine"},
    )
    client = FakeInflightStrapi([row(SLUG, "drafting", 99999)])

    reclaimed = reclaim_stale_topics(client, now=NOW)

    assert reclaimed[0]["to"] == "in_review"
    assert client.updates == [
        (f"doc-{SLUG}", {"status": "in_review", "lastError": None})
    ]


# --- 2. draft_one duplicate guard -----------------------------------------------


def test_draft_one_refuses_journal_duplicate_and_completes_topic(stub_stages):
    write_journal(
        {"event": "article_created", "slug": SLUG, "articleDocumentId": "art-1"},
        {"event": CHECKPOINT_EVENT, "slug": SLUG, "articleDocumentId": "art-1",
         "topicStatus": "in_review", "decision": "quarantine"},
    )
    client = FakeDraftStrapi(finder=None)  # no finder: journal-only veto

    result = pipeline_cli.draft_one(client, make_cfg(), SLUG)

    assert result["duplicate"] is True
    assert result["topicStatus"] == "in_review"
    assert client.created == [], "a duplicate article must never be created"
    # the guard fires BEFORE any pipeline stage touches the topic
    assert client.topic_updates == [
        (f"doc-{SLUG}", {"status": "in_review", "lastError": None})
    ]
    events = journal()
    assert events[-1]["event"] == "draft_skipped_duplicate"
    assert events[-1]["source"] == "journal"


def test_draft_one_refuses_live_duplicate_without_journal_row(stub_stages):
    """A pre-journal article is caught by the live working-layer lookup."""
    client = FakeDraftStrapi(finder="art-legacy")

    result = pipeline_cli.draft_one(client, make_cfg(), SLUG)

    assert result["duplicate"] is True
    assert result["topicStatus"] == "in_review"  # no verdict -> safe default
    assert client.created == []
    assert journal()[-1]["source"] == "live"


def test_draft_one_proceeds_when_finder_errors(stub_stages):
    """An unreachable CMS degrades the guard; the run proceeds as before."""
    client = FakeDraftStrapi(finder=StrapiError("connection refused"))

    result = pipeline_cli.draft_one(client, make_cfg(), SLUG)

    assert result.get("duplicate") is None
    assert len(client.created) == 1, "a fresh slug must still draft normally"
    statuses = [f["status"] for _, f in client.topic_updates]
    assert statuses[0] == "researching"
    assert statuses[-1] in ("in_review", "published", "failed")


def test_draft_one_proceeds_for_fresh_slug(stub_stages):
    """No journal row, live lookup says none -> normal drafting, unchanged."""
    client = FakeDraftStrapi(finder=None)

    result = pipeline_cli.draft_one(client, make_cfg(), SLUG)

    assert result.get("duplicate") is None
    assert len(client.created) == 1
    assert [f["status"] for _, f in client.topic_updates][0] == "researching"
