"""Tests for checkpoint/resume (t_bde3d77c).

A batch killed by the guard must not waste completed work, and a re-run must
never duplicate a finished draft. draft_one appends an `article_completed`
checkpoint row as its LAST durable write; run_batch loads the checkpoint set
at startup and skips those slugs before anything else.

Cross-process (SIGKILL mid-run, re-run, compare to a clean run) is covered by
the workspace rehearsal — this file pins the in-process contract:
  1. the checkpoint row exists and is written last,
  2. a completed slug is skipped BEFORE the batch-deadline gate,
  3. the cron stdout contract survives (notice is stderr-only),
  4. a lost/torn checkpoint degrades to re-drafting, never to a bad skip.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline_cli  # noqa: E402
from config import Config  # noqa: E402
from editor.editor import EditedDraft  # noqa: E402
from pipeline_cli import CHECKPOINT_EVENT, RESUME_EVENT, run_batch  # noqa: E402
from research.research import Fact, ResearchResult  # noqa: E402
from writer.writer import ArticleDraft  # noqa: E402


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


class FakeStrapi:
    """Duck-typed StrapiClient over two pending topics."""

    def __init__(self, slugs=("topic-a", "topic-b")):
        self.slugs = list(slugs)
        self.created = []
        self.topic_updates = []

    def list_pending_topics(self, limit=5):
        return [
            {"documentId": f"doc-{s}", "slug": s, "title": s, "primaryKeyword": "kw",
             "targetKeywords": [], "category": "gear", "targetWordCount": 500}
            for s in self.slugs[:limit]
        ]

    def list_inflight_topics(self, statuses, *, updated_before=None, limit=100):
        return []

    def get_topic_by_slug(self, slug):
        if slug not in self.slugs:
            return None
        return {"documentId": f"doc-{slug}", "slug": slug, "title": slug,
                "primaryKeyword": "kw", "targetKeywords": [], "category": "gear",
                "targetWordCount": 500}

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

    def close(self):
        pass


@pytest.fixture
def stub_stages(monkeypatch):
    """Deterministic offline stages — no LLM, no network (test_pipeline style)."""
    def research(topic, kw, config=None, **k):
        return ResearchResult(topic=topic, facts=[
            Fact(claim="Fact one.", source_url="https://e.com/1"),
            Fact(claim="Fact two.", source_url="https://e.com/2"),
            Fact(claim="Fact three.", source_url="https://e.com/3"),
        ])

    body = "# Title\n\n" + "word " * 400
    monkeypatch.setattr(pipeline_cli, "research_topic", research)
    monkeypatch.setattr(pipeline_cli, "validate_research", lambda r, min_facts=3: (True, [], []))
    monkeypatch.setattr(
        pipeline_cli, "draft_article",
        lambda *a, **k: ArticleDraft(markdown=body, word_count=400, used_facts=["Fact one."]),
    )
    monkeypatch.setattr(
        pipeline_cli, "edit_draft",
        lambda draft, topic, kw, research, config=None, **k: EditedDraft(
            markdown=draft.markdown, word_count=draft.word_count,
            used_facts=list(draft.used_facts), edit_report="pass",
        ),
    )


# --- 1. the checkpoint write ---------------------------------------------------


def test_draft_one_writes_checkpoint_row_last(stub_stages):
    client = FakeStrapi(slugs=["topic-a"])
    pipeline_cli.draft_one(client, make_cfg(), "topic-a")

    events = [e["event"] for e in journal()]
    assert events[-1] == CHECKPOINT_EVENT
    assert events == ["research_ok", "article_created", CHECKPOINT_EVENT]

    cp = journal()[-1]
    assert cp["slug"] == "topic-a"
    assert cp["articleDocumentId"] == "art-topic-a"
    assert cp["topicStatus"] in ("in_review", "published", "failed")
    assert cp["decision"]  # policy verdict recorded


def test_checkpoint_row_is_written_after_the_topic_reaches_its_terminal_status(stub_stages):
    """The checkpoint must never precede the durable state it vouches for."""
    client = FakeStrapi(slugs=["topic-a"])
    pipeline_cli.draft_one(client, make_cfg(), "topic-a")

    # the last topic status update (gear is non-sensitive, conf<60 -> failed)
    # is terminal BEFORE the checkpoint line exists — no state change follows it
    assert client.topic_updates[-1][1]["status"] in ("in_review", "published", "failed")
    assert journal()[-1]["event"] == CHECKPOINT_EVENT


# --- 2. the resume skip --------------------------------------------------------


def test_run_batch_skips_slug_with_checkpoint_row(monkeypatch, capsys):
    write_journal(
        {"ts": "t", "event": CHECKPOINT_EVENT, "slug": "topic-a",
         "articleDocumentId": "art-topic-a", "topicStatus": "in_review",
         "decision": "needs_review"},
    )
    drafted = []
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: drafted.append(slug) or {"slug": slug, "title": slug,
                                                      "confidence": 70,
                                                      "decision": "needs_review",
                                                      "published": False},
    )

    results = run_batch(FakeStrapi(), make_cfg(), 2, reclaim=False)

    assert drafted == ["topic-b"], "the completed slug must not be re-drafted"
    assert [r["slug"] for r in results] == ["topic-b"]
    resumes = [e for e in journal() if e["event"] == RESUME_EVENT]
    assert [e["slug"] for e in resumes] == ["topic-a"]
    assert resumes[0]["reason"] == "checkpoint_article_completed"


def test_article_created_alone_does_not_trigger_the_skip(monkeypatch):
    """Legacy rows predate the checkpoint: only `article_completed` resumes.

    (A slug whose article exists is unreachable via run-batch anyway — its topic
    left `pending` the moment the article was created — but the skip must not
    widen to half-finished items.)
    """
    write_journal(
        {"ts": "t", "event": "article_created", "slug": "topic-a",
         "articleDocumentId": "art-topic-a", "decision": "needs_review"},
    )
    drafted = []
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: drafted.append(slug) or {"slug": slug, "title": slug,
                                                      "confidence": 70,
                                                      "decision": "needs_review",
                                                      "published": False},
    )

    run_batch(FakeStrapi(), make_cfg(), 2, reclaim=False)

    assert drafted == ["topic-a", "topic-b"]


def test_checkpoint_skip_runs_before_the_deadline_gate(monkeypatch):
    """A completed slug is skipped even inside a spent guard — a skip is free."""
    write_journal(
        {"ts": "t", "event": CHECKPOINT_EVENT, "slug": "topic-a",
         "articleDocumentId": "art-topic-a", "topicStatus": "in_review",
         "decision": "needs_review"},
    )
    monkeypatch.setattr(pipeline_cli, "BATCH_GUARD_SECONDS", 10.0)
    drafted = []
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: drafted.append(slug) or {"slug": slug, "title": slug,
                                                      "confidence": 70,
                                                      "decision": "needs_review",
                                                      "published": False},
    )

    results = run_batch(FakeStrapi(), make_cfg(), 2, reclaim=False)

    # topic-a skipped via checkpoint, topic-b deferred by the spent guard
    assert drafted == []
    assert [r["slug"] for r in results] == []
    events = [e["event"] for e in journal()]
    assert RESUME_EVENT in events and "batch_deadline_defer" in events
    defer = [e for e in journal() if e["event"] == "batch_deadline_defer"]
    assert [e["slug"] for e in defer] == ["topic-b"]


def test_completed_slug_is_never_drafted_twice(monkeypatch):
    """The duplicate guard: a second run over the same queue re-drafts nothing."""
    drafted = []
    real_draft = pipeline_cli.draft_one

    def counting_draft(client, cfg, slug):
        drafted.append(slug)
        write_journal({"ts": "t", "event": CHECKPOINT_EVENT, "slug": slug,
                       "articleDocumentId": f"art-{slug}",
                       "topicStatus": "in_review", "decision": "needs_review"})
        return {"slug": slug, "title": slug, "confidence": 70,
                "decision": "needs_review", "published": False}

    monkeypatch.setattr(pipeline_cli, "draft_one", counting_draft)
    run_batch(FakeStrapi(), make_cfg(), 2, reclaim=False)
    assert sorted(drafted) == ["topic-a", "topic-b"]

    # re-run over the SAME two pending topics (as after a guard kill + reclaim)
    drafted.clear()
    run_batch(FakeStrapi(), make_cfg(), 2, reclaim=False)
    assert drafted == [], "a completed draft was re-drafted"


# --- 3. the cron stdout contract ------------------------------------------------


def test_resume_notice_is_stderr_only_stdout_contract_unchanged(monkeypatch, capsys):
    write_journal(
        {"ts": "t", "event": CHECKPOINT_EVENT, "slug": "topic-a",
         "articleDocumentId": "art-topic-a", "topicStatus": "in_review",
         "decision": "needs_review"},
    )
    client = FakeStrapi()
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: {"slug": slug, "title": f"T {slug}", "confidence": 70,
                              "decision": "needs_review", "published": False},
    )

    assert pipeline_cli.main(["run-batch", "2"]) == 0

    out = capsys.readouterr()
    lines = out.out.splitlines()
    # topic-a is resumed (no work, no limit slot consumed), topic-b is drafted
    assert lines[0] == "Processed 1 topic(s)."
    assert "checkpoint" not in out.out, "the notice must never enter stdout"
    # '  - ' rows stay article-only (the cron grep contract)
    assert [ln for ln in lines if ln.startswith("  - ")] == ["  - T topic-b | conf=70 | needs_review"]
    assert "  ~ checkpoint resume: skipped 1 completed topic(s): topic-a" in out.err


# --- 4. fail-safe degradation -----------------------------------------------------


def test_torn_checkpoint_line_degrades_to_not_completed(monkeypatch):
    """A truncated final line must not silently swallow a real completion.

    json.loads fails on the torn row, so the slug is treated as NOT completed
    and re-drafted — the safe direction (re-drafting is recoverable via the
    article_created duplicate audit; skipping a half-written item is not).
    """
    path = pipeline_cli.STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"event": "article_completed", "slug": "topic-a"')
    drafted = []
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: drafted.append(slug) or {"slug": slug, "title": slug,
                                                      "confidence": 70,
                                                      "decision": "needs_review",
                                                      "published": False},
    )

    run_batch(FakeStrapi(), make_cfg(), 2, reclaim=False)

    assert drafted == ["topic-a", "topic-b"]


def test_missing_journal_file_resumes_nothing(monkeypatch):
    drafted = []
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: drafted.append(slug) or {"slug": slug, "title": slug,
                                                      "confidence": 70,
                                                      "decision": "needs_review",
                                                      "published": False},
    )

    run_batch(FakeStrapi(), make_cfg(), 2, reclaim=False)

    assert drafted == ["topic-a", "topic-b"]
    assert not pipeline_cli.STATE_FILE.exists() or journal()
