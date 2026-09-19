"""Tests for the `run-batch 0` guard (pipeline_cli.MIN_BATCH_LIMIT).

Strapi clamps `pagination[pageSize]=0` to a non-empty first page (measured live:
pageSize=0 -> data=1 row, meta.total=2), so a zero/negative limit used to reach
draft_one() and draft one REAL topic — real LLM spend, a real article in Strapi, a
real review TODO. These tests pin the refusal: zero/negative limits are rejected
loudly (CLI exit 2) and before any Strapi call, while every limit >= 1 keeps the
existing behaviour byte-for-byte (the 09:00 cron runs `run-batch 2`).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline_cli  # noqa: E402
from config import Config  # noqa: E402
from pipeline_cli import MIN_BATCH_LIMIT, _parse_batch_limit, run_batch  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    """Never touch the real engine/state/pipeline.jsonl from tests."""
    monkeypatch.setattr(pipeline_cli, "STATE_FILE", tmp_path / "pipeline.jsonl")


class FakeStrapi:
    """Records every client call so 'zero Strapi writes' is provable, not assumed."""

    def __init__(self, inflight=(), pending=()):
        self.inflight = list(inflight)
        self.pending = list(pending)
        self.calls = []
        self.pending_limit = None
        self.updates = []

    def list_inflight_topics(self, statuses, *, updated_before=None, limit=100):
        self.calls.append("list_inflight")
        return list(self.inflight)

    def list_pending_topics(self, limit=5):
        self.calls.append("list_pending")
        self.pending_limit = limit
        return list(self.pending)

    def update_topic(self, doc_id, fields):
        self.calls.append("update_topic")
        self.updates.append((doc_id, fields))

    def close(self):
        pass


def make_cfg():
    return Config(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="key",
    )


def _draft_stub(c, cfg, slug):
    return {
        "slug": slug,
        "title": f"Titled {slug}",
        "confidence": 70,
        "decision": "needs_review",
        "published": False,
    }


# --- the guard itself --------------------------------------------------------

@pytest.mark.parametrize("limit", [0, -1, -5, -100])
def test_zero_and_negative_limits_are_refused_before_any_strapi_call(limit, monkeypatch):
    """The whole point: a 0/-N limit must not list, reclaim, or draft ANYTHING."""
    client = FakeStrapi(
        inflight=[{"documentId": "doc-x", "slug": "x", "status": "drafting",
                   "updatedAt": "2020-01-01T00:00:00Z"}],
        pending=[{"documentId": "doc-y", "slug": "y"}],
    )
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: pytest.fail(f"draft_one called with limit={limit}"),
    )

    with pytest.raises(ValueError) as excinfo:
        run_batch(client, make_cfg(), limit)

    assert "limit must be >=" in str(excinfo.value)
    assert client.calls == []          # no list, no reclaim, no write
    assert client.updates == []
    assert not pipeline_cli.STATE_FILE.exists()  # no state written


def test_zero_limit_does_not_leak_a_previous_reclaim_notice(monkeypatch):
    """main() prints last_reclaimed() after the batch — a refused run must print
    nothing, so a stale in-process reclaim record can never be reported as work."""
    base = pipeline_cli._dt.datetime.now(pipeline_cli._dt.timezone.utc)
    stale = {
        "documentId": "doc-stale",
        "slug": "stale",
        "status": "drafting",
        "updatedAt": (base - pipeline_cli._dt.timedelta(seconds=99999))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    client = FakeStrapi([stale], pending=[{"documentId": "doc-stale", "slug": "stale"}])
    monkeypatch.setattr(pipeline_cli, "draft_one", _draft_stub)

    run_batch(client, make_cfg(), 2)
    assert pipeline_cli.last_reclaimed()  # populated by the limit>=1 run

    with pytest.raises(ValueError):
        run_batch(client, make_cfg(), 0)

    assert pipeline_cli.last_reclaimed() == []


def test_limit_one_is_still_forwarded_unchanged(monkeypatch):
    """Defence against over-clamping: limit=1 must reach Strapi as pageSize=1."""
    client = FakeStrapi(pending=[{"documentId": "doc-y", "slug": "y"}])
    monkeypatch.setattr(pipeline_cli, "draft_one", _draft_stub)

    results = run_batch(client, make_cfg(), 1)

    assert client.pending_limit == 1
    assert [r["slug"] for r in results] == ["y"]
    assert client.calls == ["list_inflight", "list_pending"]


# --- argument parsing --------------------------------------------------------

def test_parse_batch_limit_accepts_whole_numbers_at_or_above_min():
    assert _parse_batch_limit("2") == 2
    assert _parse_batch_limit("1") == 1
    assert _parse_batch_limit("10") == 10
    assert MIN_BATCH_LIMIT == 1


@pytest.mark.parametrize("raw", ["0", "-1", "-100", "abc", "", "1.5", None])
def test_parse_batch_limit_rejects_junk_and_zero(raw):
    with pytest.raises(ValueError):
        _parse_batch_limit(raw)


# --- CLI wiring (the operator-facing footgun) --------------------------------

def _wire(monkeypatch, client):
    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(pipeline_cli, "load_config", make_cfg)


@pytest.mark.parametrize("arg", ["0", "-1", "abc"])
def test_cli_run_batch_bad_limit_exits_2_without_touching_strapi(arg, monkeypatch, capsys):
    client = FakeStrapi(pending=[{"documentId": "doc-y", "slug": "y"}])
    _wire(monkeypatch, client)
    monkeypatch.setattr(
        pipeline_cli, "draft_one",
        lambda c, cfg, slug: pytest.fail("draft_one reached from a refused run-batch"),
    )

    assert pipeline_cli.main(["run-batch", arg]) == 2

    captured = capsys.readouterr()
    assert "run-batch: refused" in captured.err
    assert "nothing was listed or drafted" in captured.err
    # Never the drained-queue wording: the cron greps "Processed 0 topic" to mean
    # "queue is empty", which is a different thing from a refused argument.
    assert "Processed" not in captured.out
    assert "Processed 0 topic" not in captured.err
    assert client.calls == []
    assert not pipeline_cli.STATE_FILE.exists()


def test_cli_run_batch_zero_accepts_an_explicit_limit_argument_order(monkeypatch, capsys):
    """`run-batch 0` with trailing flags still refuses (no arg-slot confusion)."""
    client = FakeStrapi()
    _wire(monkeypatch, client)

    assert pipeline_cli.main(["run-batch", "0"]) == 2
    assert client.calls == []


def test_cli_run_batch_defaults_to_three(monkeypatch, capsys):
    """`run-batch` with no argument still defaults to 3 (the parse line changed, so
    pin the default)."""
    client = FakeStrapi(pending=[{"documentId": "doc-a", "slug": "a"}])
    _wire(monkeypatch, client)
    monkeypatch.setattr(pipeline_cli, "draft_one", _draft_stub)

    assert pipeline_cli.main(["run-batch"]) == 0

    assert client.pending_limit == 3
    assert capsys.readouterr().out.splitlines()[0] == "Processed 1 topic(s)."


def test_cli_run_batch_two_is_unchanged(monkeypatch, capsys):
    """The 09:00 cron contract for the limit>=1 path: line 1 is the summary, the
    article rows start with '  - ', nothing else is emitted."""
    client = FakeStrapi(pending=[{"documentId": "doc-a", "slug": "a"}])
    _wire(monkeypatch, client)
    monkeypatch.setattr(pipeline_cli, "draft_one", _draft_stub)

    assert pipeline_cli.main(["run-batch", "2"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "Processed 1 topic(s).",
        "  - Titled a | conf=70 | needs_review",
    ]
    assert client.pending_limit == 2
    assert pipeline_cli.last_reclaimed() == []
