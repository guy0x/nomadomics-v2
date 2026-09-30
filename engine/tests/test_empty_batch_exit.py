"""Tests for the all-topics-failed batch exit (PANT-161, t_b3949432) and for the
parked-backlog verdict (t_79196ced).

The 09-21 crash-loop day ended with every topic hard-failed and the engine
still printing "Processed 0 topic(s)." with exit 0 — the cron lane then
reported "queue drained, nothing to do", masking a dead LLM hop chain as a
normal quiet day. run_batch now records per-topic hard failures
(last_failed()), main() prints one '  ! failed:' reason line each, and a
batch that ATTEMPTED topics and drafted nothing exits 1.

The 09-24 supply freeze was the same lie from the other side: the queue held
ZERO pending topics because five were parked in the terminal `failed` status,
so the run attempted nothing at all and "Processed 0 topic(s)." + exit 0 was
technically true and operationally false. main() now asks
stranded_failed_topics() what the reclaim left parked and reports THAT
(⚠️ line 1 + '  ! stranded:' reason lines + exit 1) instead of the healthy
drained-queue wording.

Pinned contract:
  1. genuinely empty queue -> exit 0, "Processed 0 topic(s).", no failure lines
     (unchanged — the cron greps this wording for the drained-queue report),
  2. every attempted topic failed -> exit 1 + one reason line per topic,
  3. partial failure (some drafted) -> exit 0, failures still reported,
  4. all-deferred (batch deadline) -> exit 0, no failure lines (nothing was
     attempted, so there is nothing to retry),
  5. the failure record is per-run: a later clean run in the same process
     must not inherit the previous run's failures,
  6. stdout shape is unchanged in every case (line 1 = summary, article rows
     start with "  - ", failure lines use "  ! " like the per-topic stderr
     marker so no article-row grep can ever match them),
  7. empty pending + a parked `failed` backlog -> line 1 is the ⚠️ verdict,
     exit 1, one '  ! stranded:' line per parked topic (t_79196ced),
  8. that verdict never fires when the run's own failures explain the 0 (rule 2)
     or when the batch drafted anything (rule 3).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline_cli  # noqa: E402
from config import Config  # noqa: E402
from pipeline_cli import last_failed, run_batch  # noqa: E402


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


def failed_row(slug, *, status="failed", age_seconds=7200,
               last_error: "str | None" = "draft: hop -> HTTP 404"):
    """A Strapi topic document parked in a terminal state, aged against real now."""
    import datetime as _dt

    ts = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=age_seconds)
    row = {"documentId": f"doc-{slug}", "slug": slug, "status": status,
           "updatedAt": ts.isoformat()}
    if last_error is not None:
        row["lastError"] = last_error
    return row


class FakeStrapi:
    """Duck-typed StrapiClient over a fixed pending queue + `failed` backlog."""

    def __init__(self, slugs=("topic-a", "topic-b"), failed=()):
        self.slugs = list(slugs)
        self.failed = list(failed)
        self.updates = []
        self.calls = []

    def list_pending_topics(self, limit=5):
        self.calls.append("list_pending")
        return [
            {"documentId": f"doc-{s}", "slug": s, "title": s, "primaryKeyword": "kw",
             "targetKeywords": [], "category": "gear", "targetWordCount": 500}
            for s in self.slugs[:limit]
        ]

    def list_inflight_topics(self, statuses, *, updated_before=None, limit=100):
        self.calls.append("list_inflight")
        # The live client filters by status server-side; only the `failed`
        # readers (reclaim + parked-backlog) ask for FAILED_STATUSES.
        if tuple(statuses) != tuple(pipeline_cli.FAILED_STATUSES):
            return []
        return list(self.failed)

    def update_topic(self, doc_id, fields):
        self.calls.append("update_topic")
        self.updates.append((doc_id, fields))

    def close(self):
        pass


def ok_draft(slug):
    return {"slug": slug, "title": f"T {slug}", "confidence": 70,
            "decision": "needs_review", "published": False}


def failing_draft(exc):
    def _draft(client, cfg, slug):
        raise exc
    return _draft


# --- 1. genuinely empty queue: unchanged exit 0 --------------------------------


def test_empty_queue_exits_zero_with_drained_wording(monkeypatch, capsys):
    """Rule 1 + rule 7's zero-backlog half: genuinely empty, nothing parked."""
    client = FakeStrapi(slugs=[])
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)
    drafted = []
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: drafted.append(slug) or ok_draft(slug),
    )

    assert pipeline_cli.main(["run-batch", "2"]) == 0

    out = capsys.readouterr()
    assert out.out.splitlines()[0] == "Processed 0 topic(s)."
    assert "  ! failed:" not in out.out
    assert "  ! stranded:" not in out.out
    assert "⚠️" not in out.out
    assert drafted == []
    assert last_failed() == []
    assert pipeline_cli.stranded_failed_topics(client) == []


# --- 2. every attempted topic failed: exit 1 + reason lines --------------------


def test_all_topics_failed_exits_one_with_reason_lines(monkeypatch, capsys):
    client = FakeStrapi()
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        failing_draft(RuntimeError("openrouter chain dead: all hops 404/429")),
    )

    assert pipeline_cli.main(["run-batch", "2"]) == 1

    out = capsys.readouterr()
    lines = out.out.splitlines()
    # cron stdout contract survives: line 1 is still the batch summary
    assert lines[0] == "Processed 0 topic(s)."
    failed_lines = [ln for ln in lines if ln.startswith("  ! failed:")]
    assert len(failed_lines) == 2
    assert any("topic-a" in ln and "RuntimeError" in ln for ln in failed_lines)
    assert any("topic-b" in ln and "RuntimeError" in ln for ln in failed_lines)
    assert "hop health" in out.err


def test_all_failed_run_batch_returns_empty_but_records_failures(monkeypatch):
    # The REAL 09-21 incident shape: a dead chain surfaces as
    # StageDeadlineExceeded (stage budget burned by 404/429/malformed hops —
    # llm.py:202), not a bare RuntimeError.
    from llm import StageDeadlineExceeded

    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        failing_draft(StageDeadlineExceeded("draft: per-stage budget 360s exhausted")),
    )

    results = run_batch(FakeStrapi(), make_cfg(), 2, reclaim=False)

    assert results == []
    rec = last_failed()
    assert [f["slug"] for f in rec] == ["topic-a", "topic-b"]
    assert all("StageDeadlineExceeded" in f["error"] for f in rec)


# --- 3. partial failure: exit 0, failures still reported ------------------------


def test_partial_failure_still_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: FakeStrapi())
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)

    def draft(client, cfg, slug):
        if slug == "topic-a":
            raise RuntimeError("research failed quality gate: no facts")
        return ok_draft(slug)

    monkeypatch.setattr(pipeline_cli, "draft_one", draft)

    assert pipeline_cli.main(["run-batch", "2"]) == 0

    out = capsys.readouterr()
    assert out.out.splitlines()[0] == "Processed 1 topic(s)."
    failed_lines = [ln for ln in out.out.splitlines() if ln.startswith("  ! failed:")]
    assert len(failed_lines) == 1 and "topic-a" in failed_lines[0]
    assert "  - T topic-b | conf=70 | needs_review" in out.out


# --- 4. all-deferred (deadline): exit 0, NOT a failure --------------------------


def test_all_deferred_keeps_exit_zero(monkeypatch, capsys):
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: FakeStrapi())
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)
    monkeypatch.setattr(pipeline_cli, "BATCH_GUARD_SECONDS", 10.0)
    drafted = []
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: drafted.append(slug) or ok_draft(slug),
    )

    assert pipeline_cli.main(["run-batch", "2"]) == 0

    out = capsys.readouterr()
    assert out.out.splitlines()[0] == "Processed 0 topic(s)."
    assert "  ! failed:" not in out.out
    assert "batch deadline awareness" in out.err
    assert drafted == []
    assert last_failed() == []


# --- 5. the failure record is per-run --------------------------------------------


def test_failure_record_does_not_leak_into_next_run(monkeypatch, capsys):
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: FakeStrapi())
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)

    monkeypatch.setattr(
        pipeline_cli, "draft_one", failing_draft(RuntimeError("chain dead"))
    )
    assert pipeline_cli.main(["run-batch", "2"]) == 1
    assert len(last_failed()) == 2
    capsys.readouterr()  # drain run 1's output before evaluating run 2

    # same process, next run: the queue is now empty (a real cron hour later)
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: FakeStrapi(slugs=[]))
    assert pipeline_cli.main(["run-batch", "2"]) == 0
    out = capsys.readouterr()
    assert "  ! failed:" not in out.out
    assert last_failed() == []


# --- 6. stdout contract: failure lines can never pass for article rows ----------


def test_failure_marker_is_not_an_article_row(monkeypatch, capsys):
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        failing_draft(RuntimeError("boom")),
    )
    run_batch(FakeStrapi(slugs=["topic-a"]), make_cfg(), 1, reclaim=False)
    rec = last_failed()
    assert rec and rec[0]["slug"] == "topic-a"
    # every per-topic failure the cron lane sees uses '  ! ', never '  - '
    assert not any(f["slug"].startswith("-") for f in rec)


# --- 7. empty pending + a parked `failed` backlog: NOT a drained queue -----------
# t_79196ced (PANT-173 residual). The 09-24 freeze shape: zero pending topics
# BECAUSE supply is parked in the terminal `failed` status, so "Processed 0
# topic(s)." + exit 0 was technically true and operationally false.


def test_parked_backlog_with_empty_queue_exits_one(monkeypatch, capsys):
    client = FakeStrapi(
        slugs=[],
        failed=[
            # aged far past the cooling-off window with attempts spent -> reclaim
            # tried it FAILED_RETRY_MAX_ATTEMPTS times and will not try again
            failed_row("used-up", last_error="draft: gemini 429"),
            # no lastError: a human/policy REJECT, a verdict reclaim never touches
            failed_row("rejected", last_error=None),
        ],
    )
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)
    for _ in range(pipeline_cli.FAILED_RETRY_MAX_ATTEMPTS):
        pipeline_cli._append_state(
            {"ts": "2026-09-24T00:00:00+00:00", "event": pipeline_cli.FAILED_RECLAIM_EVENT,
             "slug": "used-up"}
        )
    drafted = []
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: drafted.append(slug) or ok_draft(slug),
    )

    assert pipeline_cli.main(["run-batch", "2"]) == 1

    out = capsys.readouterr()
    lines = out.out.splitlines()
    # line 1 is the warning verdict, NOT the drained-queue wording the cron greps
    assert lines[0].startswith("⚠️") and "2 topic(s) parked" in lines[0]
    assert "Processed 0 topic(s)." not in out.out
    stranded_lines = [ln for ln in lines if ln.startswith("  ! stranded:")]
    assert len(stranded_lines) == 2
    assert any("used-up" in ln and "attempts_exhausted" in ln for ln in stranded_lines)
    assert any("rejected" in ln and "policy_verdict" in ln for ln in stranded_lines)
    # the parked topics are reported, never re-drafted
    assert drafted == []
    # the failure lines stay a distinct family (the wrapper keys off '  ! failed:')
    assert "  ! failed:" not in out.out
    # no article-row shape can match a stranded line
    assert [ln for ln in lines if ln.startswith("  - ")] == []
    assert "NOT drained" in out.err
    # read-only: the parked backlog costs one GET and no write
    assert client.updates == []
    assert client.calls == ["list_inflight", "list_inflight", "list_pending", "list_inflight"]


def test_parked_backlog_counts_young_failures_too(monkeypatch, capsys):
    """A failure inside the cooling-off window is still 'the queue is not drained'.

    The daily cron only ever sees such a row if something outside this run parked
    it (this run's own failures take the PANT-161 path instead), and the shape is
    the same operational lie: 0 processed, supply parked."""
    client = FakeStrapi(
        slugs=[], failed=[failed_row("fresh", age_seconds=60, last_error="draft: 404")]
    )
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)

    assert pipeline_cli.main(["run-batch", "2"]) == 1

    out = capsys.readouterr()
    assert out.out.splitlines()[0].startswith("⚠️")
    assert "  ! stranded: fresh — retry_pending:" in out.out


def test_parked_backlog_with_article_attached_is_reported(monkeypatch, capsys):
    """`failed` with an article_created row: reclaim must not re-draft it, and the
    human must see it — this is the shape the 8 invariant-blocked rows are in."""
    client = FakeStrapi(
        slugs=[], failed=[failed_row("has-article", last_error="excerpt missing")]
    )
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)
    pipeline_cli._append_state(
        {"ts": "2026-09-24T00:00:00+00:00", "event": "article_created", "slug": "has-article"}
    )

    assert pipeline_cli.main(["run-batch", "2"]) == 1

    out = capsys.readouterr()
    assert "  ! stranded: has-article — article_attached:" in out.out


def test_parked_backlog_verdict_does_not_override_the_failure_verdict(monkeypatch, capsys):
    """Rule 8: when this run's OWN failures explain the 0, the pinned PANT-161
    wording and line 1 stay exactly as they are."""
    client = FakeStrapi(
        slugs=["topic-a"], failed=[failed_row("topic-a", age_seconds=5)]
    )
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)
    monkeypatch.setattr(
        pipeline_cli, "draft_one", failing_draft(RuntimeError("chain dead"))
    )

    assert pipeline_cli.main(["run-batch", "1"]) == 1

    out = capsys.readouterr()
    assert out.out.splitlines()[0] == "Processed 0 topic(s)."
    assert "  ! failed: topic-a" in out.out
    assert "  ! stranded:" not in out.out
    assert "hop health" in out.err


def test_stranded_verdict_never_fires_when_the_batch_drafted(monkeypatch, capsys):
    """Rule 8: a productive run is a healthy run, parked backlog or not."""
    client = FakeStrapi(
        slugs=["topic-a"], failed=[failed_row("used-up", last_error="draft: 429")]
    )
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)
    monkeypatch.setattr(
        pipeline_cli, "draft_one", lambda c, cfg, slug: ok_draft(slug)
    )

    assert pipeline_cli.main(["run-batch", "1"]) == 0

    out = capsys.readouterr()
    assert out.out.splitlines()[0] == "Processed 1 topic(s)."
    assert "⚠️" not in out.out
    assert "  ! stranded:" not in out.out


def test_reclaimed_topic_is_not_reported_as_stranded():
    """The reclaim PUT the slug back to `pending`; belt-and-braces, an
    eventually-consistent reader that still lists it must not double-report."""
    client = FakeStrapi(
        slugs=[], failed=[failed_row("was-failed", last_error="draft: 404")]
    )

    stranded = pipeline_cli.stranded_failed_topics(
        client, reclaimed=[{"slug": "was-failed", "from": "failed"}]
    )

    assert stranded == []


def test_stranded_classification_is_status_filtered():
    """A duck-typed over-returning reader (test_reclaim_stale's) hands back rows in
    other statuses — the live query is server-filtered, so those are not ours."""
    client = FakeStrapi(
        slugs=[],
        failed=[
            {"documentId": "doc-x", "slug": "drafting-row", "status": "drafting"},
            {"documentId": "doc-y", "status": "failed"},  # no slug: no report
            failed_row("real-backlog"),
        ],
    )

    stranded = pipeline_cli.stranded_failed_topics(client)

    assert [s["slug"] for s in stranded] == ["real-backlog"]
    assert stranded[0]["reason"] == pipeline_cli.STRANDED_RETRY
    assert stranded[0]["ageSeconds"] >= 7200.0
    assert "HTTP 404" in stranded[0]["error"]


def test_stranded_read_is_read_only_and_journal_silent():
    """The check is a reporting read: no PUT, no journal row, no state file."""
    client = FakeStrapi(slugs=[], failed=[failed_row("parked")])

    assert pipeline_cli.stranded_failed_topics(client)

    assert client.updates == []
    assert client.calls == ["list_inflight"]
    assert not pipeline_cli.STATE_FILE.exists()
