"""Tests for the KeyError 'choices' hop-skip hardening (t_e4077c91).

Context: draft-batch 2026-09-21 logged 11 KeyError 'choices' retries across
the edit/writer/research stages — nemotron-3-super answered HTTP 200 with
invalid JSON lacking 'choices', and the stages' catch-all treated the
extraction KeyError as transient, re-POSTing the same dead hop until the
budget burned. These tests pin the fix:

  1. A 200 body without 'choices' costs ONE attempt per hop, then the stage
     advances to the next hop (no re-POST of the same hop).
  2. The journal carries exactly one MalformedHopResponse line per hop.
  3. Other KeyErrors (real extraction bugs) and transient errors keep the
     old retry behavior.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llm
from config import Config
from llm import is_malformed_hop_response, is_transient_hop_error_body
from editor.editor import edit_draft
from research.research import research_topic
from writer.writer import ArticleDraft, draft_article


# --- local fakes (same shape as test_retry_hardening's) -----------------------

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
        self.calls.append((url, dict(json or {}), headers))
        if isinstance(self.responses[0], Exception):
            raise self.responses.pop(0)
        return self.responses.pop(0)


def _article_api():
    body = "# Title\n\n" + "word " * 600
    content = json.dumps({"markdown": body, "word_count": 600, "cited_facts": ["c"]})
    return {"choices": [{"message": {"content": content}}]}


def _research_api():
    content = json.dumps(
        {"facts": [{"claim": "c", "source_url": "https://e.com/a"}], "keywords": ["k"]}
    )
    return {"choices": [{"message": {"content": content}}]}


def _research():
    from research.research import Fact, ResearchResult

    return ResearchResult(topic="X", facts=[Fact(claim="c", source_url="https://e.com/a")])


def _draft():
    body = "# Draft\n\n" + "word " * 600
    return ArticleDraft(markdown=body, word_count=600)


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


# --- classifier ---------------------------------------------------------------


def test_classifier_matches_only_choices_keyerror():
    assert is_malformed_hop_response(KeyError("choices"))
    assert is_malformed_hop_response(KeyError("message")), "streaming-shaped body (choices[0].delta) is the same malformed-200 class"
    assert is_malformed_hop_response(IndexError("list index out of range")), "empty choices[] is the same malformed-200 class"
    assert is_malformed_hop_response(TypeError("'int' object is not subscriptable")), "non-subscriptable choices is the same malformed-200 class"
    assert not is_malformed_hop_response(ValueError("x"))


# --- 1. malformed 200: one attempt, then the next hop --------------------------


def test_streaming_shaped_body_skips_the_hop_after_one_attempt():
    # Free providers occasionally serve choices[0].delta (streaming shape) on a
    # non-stream call: content extraction KeyErrors on 'message'.
    client = FakeClient([FakeResp(200, {"choices": [{"delta": {"content": "hi"}}]}), FakeResp(200, _article_api())])
    d = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=3)
    assert d.has_content, "batch must continue on the fallback hop"
    models = [c[1]["model"] for c in client.calls]
    assert models == ["m1:free", "m2:free"], f"the broken hop must not be re-POSTed: {models}"


# --- 1. malformed 200: one attempt, then the next hop --------------------------


def test_writer_skips_malformed_hop_after_one_attempt():
    client = FakeClient([FakeResp(200, {"error": "invalid JSON"}), FakeResp(200, _article_api())])
    d = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=3)
    assert d.has_content, "batch must continue on the fallback hop"
    models = [c[1]["model"] for c in client.calls]
    assert models == ["m1:free", "m2:free"], f"the broken hop must not be re-POSTed: {models}"


def test_research_skips_malformed_hop_after_one_attempt():
    client = FakeClient([FakeResp(200, []), FakeResp(200, _research_api())])
    r = research_topic("X", config=_cfg(), http_client=client, max_retries=3)
    assert r.facts, "batch must continue on the fallback hop"
    models = [c[1]["model"] for c in client.calls]
    assert models == ["m1:free", "m2:free"], f"the broken hop must not be re-POSTed: {models}"


def test_editor_skips_malformed_hop_after_one_attempt():
    client = FakeClient([FakeResp(200, {"detail": "upstream html error page"}), FakeResp(200, _article_api())])
    e = edit_draft(_draft(), "X", "", _research(), config=_cfg(), http_client=client, max_retries=3)
    assert e.has_content, "batch must continue on the fallback hop"
    models = [c[1]["model"] for c in client.calls]
    assert models == ["m1:free", "m2:free"], f"the broken hop must not be re-POSTed: {models}"


# --- 2. the journal: exactly one hop-skip line per broken hop ------------------


def test_malformed_hop_journals_one_error_line_per_stage(capsys):
    client = FakeClient([FakeResp(200, {}), FakeResp(200, _article_api())])
    draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=3)
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if "MalformedHopResponse" in ln]
    assert len(lines) == 1, f"expected exactly one hop-skip journal line, got {len(lines)}: {lines}"
    assert "m1:free" in lines[0] and "error MalformedHopResponse" in lines[0]


# --- 3. retry behavior for everything else is unchanged ------------------------


def test_transient_error_still_retries_the_same_hop():
    client = FakeClient([httpx.ConnectError("blip"), FakeResp(200, _article_api())])
    d = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=1)
    assert d.has_content
    models = [c[1]["model"] for c in client.calls]
    assert models == ["m1:free", "m1:free"], f"transient errors must retry the same hop: {models}"


# --- 4. a 200 wrapping a TRANSIENT upstream error gets ONE same-hop retry -------


def test_transient_classifier_only_matches_wrapped_transient_errors():
    # The OpenRouter shape seen live on 2026-09-22 (t_22a3bbdc).
    assert is_transient_hop_error_body({"error": {"code": 503, "message": "provider_overloaded"}})
    assert is_transient_hop_error_body({"error": {"code": "529"}})
    assert is_transient_hop_error_body({"error": {"status": 500}})
    assert is_transient_hop_error_body({"error": "rate limited, try again"})
    assert is_transient_hop_error_body({"error": {"message": "Upstream provider temporarily unavailable"}})
    # Everything else is NOT transient: a re-POST cannot help.
    assert not is_transient_hop_error_body({"error": {"code": 401, "message": "invalid api key"}})
    assert not is_transient_hop_error_body({"error": {"code": 404}})
    assert not is_transient_hop_error_body({})  # shape is simply broken
    assert not is_transient_hop_error_body({"choices": [{"delta": {"content": "hi"}}]})
    assert not is_transient_hop_error_body("<html>502 bad gateway</html>")
    assert not is_transient_hop_error_body(None)


def test_wrapped_transient_503_retries_the_same_hop_once_then_succeeds():
    """The live failure mode: nemotron-3-super answers HTTP 200 whose body is an
    upstream 'provider_overloaded' 503. The same hop answers a second later."""
    client = FakeClient([
        FakeResp(200, {"error": {"code": 503, "message": "provider_overloaded"}}),
        FakeResp(200, _article_api()),
    ])
    d = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=3)
    assert d.has_content
    models = [c[1]["model"] for c in client.calls]
    assert models == ["m1:free", "m1:free"], f"a transient wrapped 503 must retry the same hop: {models}"


def test_transient_retry_is_bounded_to_one_then_the_next_hop():
    """Two transient bodies in a row: one retry, then advance — never the 09-21
    budget burn (11 re-POSTs of one hop, t_e4077c91)."""
    client = FakeClient([
        FakeResp(200, {"error": {"code": 503, "message": "provider_overloaded"}}),
        FakeResp(200, {"error": {"code": 503, "message": "provider_overloaded"}}),
        FakeResp(200, _article_api()),
    ])
    d = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=3)
    assert d.has_content
    models = [c[1]["model"] for c in client.calls]
    assert models == ["m1:free", "m1:free", "m2:free"], f"transient retry must be bounded: {models}"


def test_non_transient_error_body_still_skips_the_hop_without_retry():
    """A 200 carrying a permanent error (401/404) is still a dead hop."""
    client = FakeClient([
        FakeResp(200, {"error": {"code": 404, "message": "no endpoints found"}}),
        FakeResp(200, _article_api()),
    ])
    d = draft_article("X", "", _research(), config=_cfg(), http_client=client, max_retries=3)
    assert d.has_content
    models = [c[1]["model"] for c in client.calls]
    assert models == ["m1:free", "m2:free"], f"a permanent error body must not be retried: {models}"


def test_research_retries_a_wrapped_transient_503_once():
    client = FakeClient([
        FakeResp(200, {"error": {"code": 503, "message": "provider_overloaded"}}),
        FakeResp(200, _research_api()),
    ])
    r = research_topic("X", config=_cfg(), http_client=client, max_retries=3)
    assert r.facts
    models = [c[1]["model"] for c in client.calls]
    assert models == ["m1:free", "m1:free"], f"research must retry a transient wrapped 503: {models}"


def test_editor_retries_a_wrapped_transient_503_once():
    client = FakeClient([
        FakeResp(200, {"error": {"code": 503, "message": "provider_overloaded"}}),
        FakeResp(200, _article_api()),
    ])
    e = edit_draft(_draft(), "X", "", _research(), config=_cfg(), http_client=client, max_retries=3)
    assert e.has_content
    models = [c[1]["model"] for c in client.calls]
    assert models == ["m1:free", "m1:free"], f"edit must retry a transient wrapped 503: {models}"
