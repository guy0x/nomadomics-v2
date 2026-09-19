"""Tests for the wall-clock safety layer (llm.StageBudget + non-retryable hops).

Context: the 2026-09-18 draft cron run stalled 3506s inside draft_article() and was
tree-killed by cron's 3600s cap. httpx's `timeout=` is a per-operation bound, and the
stage had no total deadline, so 5 hops x 3 attempts could stack to hours. These tests
pin the two mechanisms that now bound it.
"""
import time

import httpx
import pytest

import llm
from llm import LLM_TIMEOUT, NON_RETRYABLE_STATUS, StageBudget, StageDeadlineExceeded, is_retryable_status
from writer.writer import draft_article


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
        self.calls.append((url, json, headers))
        if isinstance(self.responses[0], Exception):
            raise self.responses.pop(0)
        return self.responses.pop(0)


class SlowTimeoutClient:
    """Every attempt blocks like a trickling peer, then fails."""

    def __init__(self, delay: float = 0.15):
        self.delay = delay
        self.calls = 0

    def post(self, url, json=None, headers=None):
        self.calls += 1
        time.sleep(self.delay)
        raise httpx.ReadTimeout("timed out")


def test_llm_timeout_is_an_explicit_per_operation_envelope():
    assert (LLM_TIMEOUT.connect, LLM_TIMEOUT.read) == (10.0, 120.0)
    assert (LLM_TIMEOUT.write, LLM_TIMEOUT.pool) == (10.0, 10.0)


def test_stage_budget_take_respects_attempt_cap():
    b = StageBudget("draft", seconds=60.0, max_attempts=3)
    assert [b.take() for _ in range(4)] == [True, True, True, False]
    assert b.expired() is True
    assert b.attempts == 3


def test_stage_budget_expires_on_wall_clock():
    b = StageBudget("draft", seconds=0.05)
    assert b.take() is True
    time.sleep(0.06)
    assert b.expired() is True
    assert b.take() is False


def test_non_retryable_statuses():
    assert is_retryable_status(429) is True
    assert is_retryable_status(500) is True
    for s in sorted(NON_RETRYABLE_STATUS):
        assert is_retryable_status(s) is False


def test_draft_stage_aborts_on_budget_instead_of_running_all_attempts(monkeypatch):
    """5 hops x 3 attempts x a trickling peer is what broke the 09-18 run.

    With a 0.5s stage budget and a client that burns 0.15s per attempt, the stage
    must stop after the first attempt and raise — not walk the whole chain.
    """
    monkeypatch.setitem(llm.STAGE_BUDGET_SECONDS, "draft", 0.5)
    client = SlowTimeoutClient(delay=0.15)
    t0 = time.monotonic()
    with pytest.raises(StageDeadlineExceeded):
        draft_article("X", "", _research(), http_client=client, model=None, max_retries=2)
    elapsed = time.monotonic() - t0
    assert client.calls <= 5, f"stage kept attempting after its budget ({client.calls} calls)"
    assert elapsed < 5.0, f"stage ran {elapsed:.1f}s past a 0.5s budget"


def test_stage_deadline_keeps_the_underlying_error_as_cause(monkeypatch):
    monkeypatch.setitem(llm.STAGE_BUDGET_SECONDS, "draft", 0.4)
    client = SlowTimeoutClient(delay=0.1)
    with pytest.raises(StageDeadlineExceeded) as ei:
        draft_article("X", "", _research(), http_client=client, model="m:free", max_retries=0)
    assert isinstance(ei.value.__cause__, httpx.ReadTimeout)
    assert "budget" in str(ei.value)


def test_non_retryable_hop_is_skipped_after_one_attempt():
    """A 404 hop must not consume 3 attempts + backoff sleeps."""
    client = FakeClient([FakeResp(404, {"error": "model not found"})])
    with pytest.raises(Exception):
        draft_article("X", "", _research(), http_client=client, model="gone:free", max_retries=2)
    assert len(client.calls) == 1


def test_retryable_hop_still_retries():
    client = FakeClient([FakeResp(500), FakeResp(500)])
    with pytest.raises(Exception):
        draft_article("X", "", _research(), http_client=client, model="m:free", max_retries=1)
    assert len(client.calls) == 2


def _research():
    from research.research import Fact, ResearchResult

    return ResearchResult(
        topic="X",
        facts=[Fact(claim="c", source_url="https://e.com/a")],
    )