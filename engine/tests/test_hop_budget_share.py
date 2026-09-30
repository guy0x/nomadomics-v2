"""Tests for the per-attempt stage-budget share + wedge bench (t_afaa4c2f).

Context: the 2026-09-28 draft batch lost BOTH topics to `StageDeadlineExceeded`.
`research.py` / `writer.py` / `editor.py` handed `deadline_post` the WHOLE
remaining stage (`deadline=budget.remaining()`), and StageDeadlineExceeded is a
RuntimeError absent from their handler tuples — so one wedged hop consumed the
entire stage AND escaped the hop loop. Topic 2 died on hop 1 of 4 with 238s of
its research budget unspent; topic 1 died on hop 4 of 4 with 207s unspent.

These tests pin the three properties of the fix:

  1. attempt_deadline — an attempt gets a FRACTION of the stage while another
     usable hop follows, and the whole remainder when it is the last one (the
     last-hop rule is what preserves a slow-but-real win: the 09-22 draft stage
     succeeded through nemotron-3.5-lightning at 315.6s of a 360s budget).
  2. A wedged hop is abandoned at its share and the stage moves to the NEXT hop
     instead of dying with the fallbacks untried.
  3. Two wedges in a row bench the hop for the rest of the run (llm hop-health),
     so a hanging hop cannot re-earn its share in every stage of every topic.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import editor.editor as editor_mod
import llm
import research.research as research_mod
import writer.writer as writer_mod
from config import Config
from editor.editor import edit_draft
from llm import StageBudget, StageDeadlineExceeded, attempt_deadline, usable_hops_after
from research.research import research_topic
from writer.writer import ArticleDraft, draft_article


# --- fakes --------------------------------------------------------------------

class FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=self)

    def json(self):
        return self._json


def _article_api():
    body = "# Title\n\n" + "word " * 600
    return {"choices": [{"message": {"content": json.dumps({"markdown": body, "word_count": 600})}}]}


def _research_api():
    payload = {
        "topic": "X",
        "facts": [{"claim": "c", "source_url": "https://e.com/a"}],
        "keywords": ["k"],
    }
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


class HopClient:
    """Answers per model.

    ``wedges`` block far past the whole stage (a dribbling peer: it then returns a
    perfectly good body the caller must never see). ``slow`` sleep less than the
    stage but more than a half-stage share — the shape of a real slow hop.
    """

    def __init__(self, *, wedges=(), slow=None, wedge_block=1.6, slow_block=1.3,
                 good=None, statuses=None):
        self.wedges = set(wedges)
        self.slow = set(slow or ())
        self.wedge_block = wedge_block
        self.slow_block = slow_block
        self.good = good if good is not None else _article_api()
        self.statuses = dict(statuses or {})
        self.calls: list[str] = []

    def post(self, url, json=None, headers=None):
        model = (json or {}).get("model")
        self.calls.append(model)
        if model in self.wedges:
            time.sleep(self.wedge_block)
            return FakeResp(200, self.good)
        if model in self.slow:
            time.sleep(self.slow_block)
            return FakeResp(200, self.good)
        code = self.statuses.get(model, 200)
        return FakeResp(code, self.good if code == 200 else {"error": "nope"})


def _cfg(fallback_models=("m2:free",), **over):
    kw = dict(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="or-key",
        gemini_api_key="",
        research_provider="openrouter",
        draft_provider="openrouter",
        edit_provider="openrouter",
        research_model="m1:free",
        draft_model="m1:free",
        fallback_models=fallback_models,
    )
    kw.update(over)
    return Config(**kw)


def _research():
    from research.research import Fact, ResearchResult

    return ResearchResult(topic="X", facts=[Fact(claim="c", source_url="https://e.com/a")])


def _draft():
    return ArticleDraft(markdown="# T\n\n" + "word " * 600, word_count=600)


@pytest.fixture(autouse=True)
def _clean_hop_health():
    llm._clear_hop_health()
    yield
    llm._clear_hop_health()


@pytest.fixture
def fast_stage(monkeypatch):
    """A 2s stage whose 'spent' floor is small enough for a unit-speed test.

    Both namespaces matter: StageBudget.expired() reads llm.MIN_USABLE_STAGE_SECONDS
    at call time, while each stage module holds its own imported copy for the
    backoff arithmetic.
    """

    def _apply(stage: str, seconds: float = 2.0) -> None:
        monkeypatch.setitem(llm.STAGE_BUDGET_SECONDS, stage, seconds)
        monkeypatch.setattr(llm, "MIN_USABLE_STAGE_SECONDS", 0.05, raising=False)
        for mod in (writer_mod, research_mod, editor_mod):
            monkeypatch.setattr(mod, "MIN_USABLE_STAGE_SECONDS", 0.05, raising=False)

    return _apply


# --- 1. attempt_deadline / usable_hops_after ----------------------------------


def test_attempt_deadline_is_half_the_stage_until_the_last_usable_hop():
    b = StageBudget("research", seconds=240.0)
    assert attempt_deadline(b, hops_after=3) == 120.0
    assert attempt_deadline(b, hops_after=1) == 120.0
    # Nothing follows: hand over everything left — a cap here could only turn a
    # slow success into a failure (the 09-22 lightning win at 315.6s/360s).
    assert attempt_deadline(b, hops_after=0) == pytest.approx(240.0, abs=0.5)


def test_attempt_deadline_never_exceeds_what_is_left():
    b = StageBudget("draft", seconds=10.0)
    time.sleep(0.05)
    assert attempt_deadline(b, hops_after=2) <= b.remaining()


def test_usable_hops_after_ignores_benched_hops():
    chain = [("openrouter", "m1:free"), ("openrouter", "m2:free"), ("openrouter", "m3:free")]
    cfg = _cfg(fallback_models=("m2:free", "m3:free"))
    assert usable_hops_after(cfg, chain, 0) == 2
    llm._record_429("openrouter", "m2:free")
    llm._record_429("openrouter", "m2:free")
    assert llm._hop_benched("openrouter", "m2:free")
    # m2 will be skipped, so m1 is not really followed by two usable hops.
    assert usable_hops_after(cfg, chain, 0) == 1


# --- 2. a wedged hop advances to the next hop ----------------------------------


def test_wedged_hop_is_abandoned_at_its_share_and_the_next_hop_still_runs(fast_stage):
    """The 09-28 topic-2 failure: hop 1 hung and the topic died with 238s unspent."""
    fast_stage("draft", 2.0)
    client = HopClient(wedges={"m1:free"})
    t0 = time.monotonic()
    draft = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=2)
    elapsed = time.monotonic() - t0
    assert draft.has_content, "the fallback hop must still be tried"
    # one attempt on the wedged hop (never re-paid), then the fallback
    assert client.calls == ["m1:free", "m2:free"]
    # abandoned at its half-stage share: not the peer's 1.6s, not the whole 2s stage
    assert 1.0 <= elapsed < 1.6, f"wedge was not bounded by its share ({elapsed:.2f}s)"


def test_last_hop_keeps_the_whole_remaining_stage(fast_stage):
    """A slow-but-real last hop must still win (09-22: lightning at 315.6s/360s).

    m1 fails fast, so m2 IS the last usable hop. It needs 1.3s — more than a
    blanket half-stage cap (1.0s) would allow, less than the stage it is owed.
    """
    fast_stage("draft", 2.0)
    client = HopClient(statuses={"m1:free": 404}, slow={"m2:free"}, slow_block=1.3)
    draft = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=0)
    assert draft.has_content, "the last hop must be given the whole remaining stage"
    assert client.calls == ["m1:free", "m2:free"]


def test_open_journal_line_carries_the_attempt_deadline(fast_stage, capsys):
    """The 09-28 post-mortem could only see the stage budget; both are now logged."""
    fast_stage("draft", 2.0)
    client = HopClient(statuses={"m1:free": 404})
    draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=0)
    err = capsys.readouterr().err
    assert "-> OPEN" in err, err
    # half of the 2s stage while a usable hop follows...
    assert "attempt-deadline 1s" in err, err
    # ...and the whole remainder on the last usable hop
    assert "attempt-deadline 2s" in err, err


def test_research_stage_also_advances_past_a_wedged_hop(fast_stage):
    fast_stage("research", 2.0)
    client = HopClient(wedges={"m1:free"}, good=_research_api())
    result = research_topic("X", "k", config=_cfg(), http_client=client, max_retries=2)
    assert len(result.facts) >= 1
    assert client.calls == ["m1:free", "m2:free"]


def test_edit_stage_also_advances_past_a_wedged_hop(fast_stage):
    fast_stage("edit", 2.0)
    client = HopClient(wedges={"m1:free"})
    edited = edit_draft(_draft(), "X", "k", _research(), config=_cfg(), http_client=client, max_retries=1)
    assert edited.has_content
    assert client.calls == ["m1:free", "m2:free"]


def test_a_wedge_is_not_retried_on_the_same_hop(fast_stage):
    """A hop that spent its whole window will not answer sooner on a retry."""
    fast_stage("draft", 2.0)
    client = HopClient(wedges={"m1:free"})
    draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=2)
    assert client.calls.count("m1:free") == 1


def test_stage_still_raises_when_every_hop_wedges(fast_stage):
    """The fix must not paper over a genuinely dead chain."""
    fast_stage("draft", 2.0)
    client = HopClient(wedges={"m1:free", "m2:free"})
    with pytest.raises(StageDeadlineExceeded):
        draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=2)


# --- 3. wedges bench the hop for the rest of the run ---------------------------


def test_two_wedges_bench_the_hop_for_the_rest_of_the_run(fast_stage):
    fast_stage("draft", 2.0)

    def wedged_run():
        client = HopClient(wedges={"m1:free"})
        draft = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=1)
        assert draft.has_content
        return client

    wedged_run()
    assert not llm._hop_benched("openrouter", "m1:free"), "one wedge is not enough to bench"

    wedged_run()
    assert llm._hop_benched("openrouter", "m1:free")
    health = json.loads(llm._hop_path().read_text())
    assert health["event"] == "hop_benched_wedged" and health["model"] == "m1:free"

    # Later stage, same process: the wedged hop is skipped with NO attempt at all.
    client = HopClient(wedges={"m1:free"})
    draft = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=1)
    assert draft.has_content
    assert client.calls == ["m2:free"]
