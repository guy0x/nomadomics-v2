"""Tests for the 2026-09-21 retry/budget hardening (t_02673f32).

Context (DIAGNOSIS.md on t_541d35ee): the 09-21 draft batch hit the shell's
2700s guard because ONE edit-stage POST hung ~33 min in-flight (httpx per-op
timeouts cannot preempt a dribbling peer) while gemma:free hops burned ~8
attempts on hard 429s. These tests pin the four fixes:

  1. llm.deadline_post  — every POST is bound to the remaining stage budget.
  2. hop-health memo    — sustained 429s bench a hop for the rest of the run.
  3. pre-attempt journal — every attempt logs an OPEN line BEFORE its POST.
  4. batch deadline gate — run_batch defers topics that cannot fit the guard.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llm
from config import Config
from llm import StageDeadlineExceeded, deadline_post
from pipeline_cli import run_batch
from writer.writer import draft_article


# --- local fakes (same shape as test_llm_budget's) ----------------------------

class FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=self)

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None):
        # snapshot the payload: the stage mutates payload["model"] per attempt,
        # so a bare reference would make every call record the LAST model
        self.calls.append((url, dict(json or {}), headers))
        if isinstance(self.responses[0], Exception):
            raise self.responses.pop(0)
        return self.responses.pop(0)


def _article_api():
    """OpenAI-shaped 200 body whose content is a strict-JSON article."""
    body = "# Title\n\n" + "word " * 600
    content = json.dumps({"markdown": body, "word_count": 600, "cited_facts": ["c"]})
    return {"choices": [{"message": {"content": content}}]}


def _research():
    from research.research import Fact, ResearchResult

    return ResearchResult(topic="X", facts=[Fact(claim="c", source_url="https://e.com/a")])


def _cfg():
    return Config(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="or-key",
        gemini_api_key="",
        research_provider="openrouter",
        draft_provider="openrouter",
        edit_provider="openrouter",
        research_model="m1:free",
        draft_model="m1:free",
        fallback_models=("m2:free",),
    )


@pytest.fixture(autouse=True)
def _clean_hop_health():
    llm._clear_hop_health()
    yield
    llm._clear_hop_health()


# --- 1. deadline_post: the hard per-POST bound --------------------------------


def test_deadline_post_abandons_in_flight_post_past_deadline():
    """The 09-21 root cause: one POST hung ~33 min inside the edit stage."""

    class Hanging:
        def __init__(self):
            self.calls = 0

        def post(self, url, json=None, headers=None):
            self.calls += 1
            time.sleep(1.5)  # simulates a dribbling peer: past any per-op timer
            return FakeResp(200, {})

    h = Hanging()
    t0 = time.monotonic()
    with pytest.raises(StageDeadlineExceeded):
        deadline_post(h, "http://x/chat/completions", headers={}, payload={}, deadline=0.3)
    # returned at the deadline, NOT when the peer finished
    assert time.monotonic() - t0 < 1.2


def test_deadline_post_returns_response_and_reraises_client_errors():
    class Ok:
        def post(self, url, json=None, headers=None):
            return FakeResp(200, {"ok": True})

    resp = deadline_post(Ok(), "http://x", headers={}, payload={}, deadline=5.0)
    assert resp.json() == {"ok": True}

    class Err:
        def post(self, url, json=None, headers=None):
            raise httpx.ConnectError("no route")

    with pytest.raises(httpx.ConnectError):
        deadline_post(Err(), "http://x", headers={}, payload={}, deadline=5.0)


def test_deadline_post_refuses_a_nonpositive_deadline():
    with pytest.raises(StageDeadlineExceeded):
        deadline_post(FakeClient([]), "http://x", headers={}, payload={}, deadline=0.0)


def test_hung_post_cannot_outlive_stage_budget(monkeypatch):
    """Stage-level: a trickling peer now exits as budget exhaustion, fast."""
    monkeypatch.setitem(llm.STAGE_BUDGET_SECONDS, "draft", 1.0)

    class Trickler:
        calls = 0

        def post(self, url, json=None, headers=None):
            Trickler.calls += 1
            time.sleep(0.6)
            raise httpx.ReadTimeout("dribbling peer")

    t0 = time.monotonic()
    with pytest.raises(StageDeadlineExceeded):
        draft_article("X", "", _research(), config=_cfg(), http_client=Trickler(), max_retries=5)
    assert Trickler.calls <= 3, "stage kept opening attempts with no budget left"
    assert time.monotonic() - t0 < 5.0, "stage ran past a 1s budget"


# --- 2. hop-health memo: sustained 429s bench the hop --------------------------


def test_two_consecutive_429s_bench_the_hop_for_later_stages():
    """The 09-21 run re-paid the same dead gemma hops in every stage."""
    # Stage 1: m1 429s three times (attempt cap), m2 answers 200.
    client = FakeClient([FakeResp(429), FakeResp(429), FakeResp(429), FakeResp(200, _article_api())])
    d = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=2)
    assert d.has_content
    models = [c[1]["model"] for c in client.calls]
    assert models.count("m1:free") == 3 and models[-1] == "m2:free"
    # benched after HOP_429_SKIP_THRESHOLD consecutive 429s, journaled for guards
    assert llm._hop_benched("openrouter", "m1:free")
    health = json.loads(llm._hop_path().read_text())
    assert health["event"] == "hop_benched_429" and health["model"] == "m1:free"

    # "Later stage" (same process): m1 is skipped with NO attempt at all.
    client2 = FakeClient([FakeResp(200, _article_api())])
    d2 = draft_article("X", "", _research(), config=_cfg(), http_client=client2, max_retries=2)
    assert d2.has_content
    assert [c[1]["model"] for c in client2.calls] == ["m2:free"]


def test_a_200_resets_the_hop_consecutive_429_streak():
    client = FakeClient([FakeResp(429), FakeResp(200, _article_api())])
    draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=1)
    assert llm._hop_429_strikes == {}, "a successful answer must clear the streak"


# --- 3. pre-attempt journal: the OPEN line -------------------------------------


def test_attempt_journals_open_line_before_its_post(capsys):
    client = FakeClient([FakeResp(429), FakeResp(200, _article_api())])
    d = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=1)
    assert d.has_content
    err = capsys.readouterr().err
    open_idx = err.find("-> OPEN")
    r429_idx = err.find("429 rate-limited")
    assert open_idx != -1 and r429_idx != -1, err
    assert open_idx < r429_idx, "the OPEN line must precede the attempt's outcome"
    assert "@ 20" in err, "OPEN line carries a wall-clock timestamp (survives SIGKILL)"


# --- 4. batch deadline gate -----------------------------------------------------


class _Strapi:
    def list_pending_topics(self, limit=1):
        return [{"slug": "topic-a", "documentId": "d1"}, {"slug": "topic-b", "documentId": "d2"}]

    def close(self):
        pass


def test_run_batch_defers_topics_that_cannot_fit_the_guard(monkeypatch, capsys):
    """With no guard time left, no new topic STARTS — clean partial result."""
    monkeypatch.setattr(llm_pipeline(), "BATCH_GUARD_SECONDS", 10.0)
    journal = []
    monkeypatch.setattr(llm_pipeline(), "_append_state", lambda entry: journal.append(entry))
    started = []
    monkeypatch.setattr(llm_pipeline(), "draft_one", lambda client, cfg, slug: started.append(slug))

    results = run_batch(_Strapi(), _cfg(), 2, reclaim=False)

    assert results == [] and started == [], "topics must not start inside a spent guard"
    defers = [e for e in journal if e["event"] == "batch_deadline_defer"]
    assert [e["slug"] for e in defers] == ["topic-a", "topic-b"]
    assert "deferred 2 topic(s)" in capsys.readouterr().err


def test_run_batch_keeps_drafting_while_the_guard_allows_it(monkeypatch):
    monkeypatch.setattr(llm_pipeline(), "BATCH_GUARD_SECONDS", 2700.0)
    monkeypatch.setattr(llm_pipeline(), "_append_state", lambda entry: None)
    started = []
    monkeypatch.setattr(llm_pipeline(), "draft_one", lambda client, cfg, slug: started.append(slug))

    run_batch(_Strapi(), _cfg(), 2, reclaim=False)
    assert started == ["topic-a", "topic-b"]


def llm_pipeline():
    import pipeline_cli

    return pipeline_cli
