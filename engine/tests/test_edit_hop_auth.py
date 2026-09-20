"""Tests for the fail-soft edit hop (t_8db05179).

Context: a dead Gemini key (HTTP 401) used to HALT the Nomadomics edit hop —
one dead key killed the whole cron cycle. The hop now treats credential
rejections (401/403) as a distinct ProviderAuthError class, skips to the
fallback model, degrades to the original draft with a structured failure
record, and emits the "Gemini key invalid - rotation needed" alarm line.
"""
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from editor.editor import EditedDraft, edit_draft
from llm import (
    GEMINI_KEY_ALARM,
    ProviderAuthError,
    auth_failure_record,
    is_auth_status,
)
from research.research import Fact, ResearchResult
from writer.writer import ArticleDraft


def make_cfg(**over):
    kw = dict(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="or-key",
        gemini_api_key="g-key",
        research_provider="gemini",
        draft_provider="gemini",
        edit_provider="gemini",
    )
    kw.update(over)
    return Config(**kw)


def _long_body():
    return (
        "# Best eSIM Plans for Digital Nomads in 2026\n\n"
        "Picture this: you land in Bangkok, still half-asleep from the redeye, and your "
        "carrier has already billed you $50 for the privilege of receiving one spam text. "
        "Roaming is a scam, and eSIMs are the loophole. A travel eSIM drops that border-crossing "
        "bill to a flat $15, sometimes less, and you never touch a plastic SIM tray again. "
        "The math is simple: five countries in a month at $10 saved each is $50 back in your "
        "pocket, every single trip. Here's the thing — most nomads don't switch because they "
        "think setup is a hassle. It isn't. Scan a QR code, tap install, and you're online "
        "before your luggage hits the belt. "
        "## Bottom Line\nPick the plan that fits your route.\n"
        "## FAQ\n### Is eSIM better than roaming?\nYes, dramatically cheaper.\n"
    )


def make_draft():
    body = _long_body()
    return ArticleDraft(markdown=body, word_count=len(body.split()), used_facts=["Airalo covers 200+ countries."])


def make_research():
    return ResearchResult(
        topic="eSIM",
        facts=[Fact(claim="Airalo covers 200+ countries.", source_url="https://airalo.com")],
    )


def valid_edit_json():
    return json.dumps({"markdown": _long_body(), "edit_report": "- tightened opener"})


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


# --- shared classification layer ---------------------------------------------


def test_auth_status_class_is_401_and_403():
    assert is_auth_status(401) is True
    assert is_auth_status(403) is True
    # Transient / other failures are NOT auth
    assert is_auth_status(429) is False
    assert is_auth_status(500) is False
    assert is_auth_status(503) is False
    assert is_auth_status(402) is False


def test_provider_auth_error_carries_no_key_material():
    err = ProviderAuthError("gemini", "gemini-2.5-flash", 401)
    assert err.provider == "gemini"
    assert err.model_id == "gemini-2.5-flash"
    assert err.status == 401
    # The message names the hop, never a key value
    assert "g-key" not in str(err)
    assert "key" not in str(err).lower().replace("gemini", "")


def test_auth_failure_record_shape_and_alarm():
    rec = auth_failure_record("gemini", "gemini-2.5-flash", 401, "edit")
    assert rec["kind"] == "provider_auth_failure"
    assert rec["stage"] == "edit"
    assert rec["provider"] == "gemini"
    assert rec["model"] == "gemini-2.5-flash"
    assert rec["status"] == 401
    # The exact alarm string the cron surface greps for
    assert rec["alarm"] == GEMINI_KEY_ALARM == "Gemini key invalid - rotation needed"
    # No key material anywhere in the record
    assert "g-key" not in json.dumps(rec)


# --- hop behavior: invalid key, fallback, degradation -------------------------


def test_invalid_gemini_key_skips_to_fallback_hop_and_succeeds(capsys):
    """401 on the Gemini hop -> one attempt, alarm line, fallback delivers."""
    cfg = make_cfg(fallback_models=())  # chain: gemini primary -> OR primary only
    client = FakeClient([
        FakeResp(401, {"error": "invalid credentials"}),
        FakeResp(200, {"choices": [{"message": {"content": valid_edit_json()}}]}),
    ])
    e = edit_draft(
        make_draft(), "Best eSIM Plans", "eSIM", make_research(),
        config=cfg, http_client=client, max_retries=2,
    )
    # Pipeline continues via the fallback hop
    assert e.has_content
    assert len(client.calls) == 2
    assert "generativelanguage.googleapis.com" in client.calls[0][0]
    assert "openrouter.ai" in client.calls[1][0]
    # A successful fallback is NOT a degraded run
    assert e.failure_record is None
    out = capsys.readouterr().err
    assert "ALARM: Gemini key invalid - rotation needed" in out
    assert "401 auth rejected" in out
    assert "g-key" not in out


def test_all_hops_auth_dead_degrades_with_failure_record(capsys):
    """Every hop 401 -> original draft kept + structured failure record."""
    cfg = make_cfg(fallback_models=())  # chain: gemini primary -> OR primary only
    client = FakeClient([
        FakeResp(401, {"error": "invalid credentials"}),
        FakeResp(401, {"error": "invalid credentials"}),
    ])
    d = make_draft()
    e = edit_draft(d, "T", "kw", make_research(), config=cfg, http_client=client, max_retries=2)
    # Pipeline continues on the un-edited draft
    assert e.markdown == d.markdown
    assert e.word_count == d.word_count
    # One attempt per hop, zero retries on auth
    assert len(client.calls) == 2
    # Structured failure record: machine-readable, key-free
    rec = e.failure_record
    assert rec["kind"] == "stage_degraded_auth"
    assert rec["stage"] == "edit"
    assert rec["outcome"] == "kept_original_draft"
    assert [h["status"] for h in rec["hops"]] == [401, 401]
    assert rec["hops"][0]["alarm"] == "Gemini key invalid - rotation needed"
    assert "g-key" not in json.dumps(rec)
    assert "auth_failure:" in e.edit_report
    out = capsys.readouterr().err
    # One alarm per rejected hop: the Gemini one + the generic openrouter one
    assert out.count("ALARM: ") == 2
    assert out.count("ALARM: Gemini key invalid - rotation needed") == 1


def test_403_is_treated_as_auth_class_no_retry(capsys):
    cfg = make_cfg(fallback_models=())
    client = FakeClient([
        FakeResp(403, {"error": "forbidden"}),
        FakeResp(200, {"choices": [{"message": {"content": valid_edit_json()}}]}),
    ])
    e = edit_draft(
        make_draft(), "T", "kw", make_research(),
        config=cfg, http_client=client, max_retries=2,
    )
    assert e.has_content
    assert len(client.calls) == 2  # skipped to fallback, did not burn retries
    assert "ALARM: Gemini key invalid - rotation needed" in capsys.readouterr().err


def test_transient_500_still_retries_then_falls_back(monkeypatch, capsys):
    """5xx stays retryable (once) — auth is the only skip-fast class here."""
    import editor.editor as ed

    monkeypatch.setattr(ed.time, "sleep", lambda s: None)  # keep the suite fast
    client = FakeClient([
        FakeResp(500, {"error": "boom"}),
        FakeResp(200, {"choices": [{"message": {"content": valid_edit_json()}}]}),
    ])
    e = edit_draft(
        make_draft(), "T", "kw", make_research(),
        config=make_cfg(), http_client=client, model="m:free", max_retries=1,
    )
    assert e.has_content
    assert len(client.calls) == 2  # same hop retried once
    assert e.failure_record is None
    assert "ALARM" not in capsys.readouterr().err


def test_valid_key_path_unchanged(capsys):
    """Healthy path: single 200, no failure record, no alarm, real edit kept."""
    client = FakeClient([FakeResp(200, {"choices": [{"message": {"content": valid_edit_json()}}]})])
    e = edit_draft(
        make_draft(), "Best eSIM Plans", "eSIM", make_research(),
        config=make_cfg(), http_client=client, model="gemini-2.5-flash",
    )
    assert e.has_content
    assert e.failure_record is None
    assert "tightened opener" in e.edit_report
    assert "auth_failure" not in e.edit_report
    assert "ALARM" not in capsys.readouterr().err
    assert len(client.calls) == 1


# --- pipeline journal ----------------------------------------------------------


class FakeStrapi:
    def __init__(self):
        self.topic = {
            "documentId": "topic-1",
            "attributes": {
                "slug": "esim-plans",
                "title": "Best eSIM Plans",
                "primaryKeyword": "eSIM",
                "targetKeywords": ["eSIM"],
                "category": "gear",
                "targetWordCount": 1800,
            },
        }
        self.topic_updates = []
        self.articles = []
        self.published = []

    def get_topic_by_slug(self, slug):
        if self.topic["attributes"]["slug"] != slug:
            return None
        merged = dict(self.topic["attributes"])
        merged["documentId"] = self.topic["documentId"]
        return merged

    def update_topic(self, doc_id, fields):
        self.topic_updates.append((doc_id, fields))

    def create_article(self, fields):
        doc = {"documentId": "article-1", "attributes": dict(fields)}
        self.articles.append(doc)
        return {"data": doc}

    def update_article(self, doc_id, fields):
        self.published.append((doc_id, fields))

    def count_published(self):
        return 0

    def close(self):
        pass


def test_pipeline_journals_auth_degradation_and_continues(tmp_path, monkeypatch):
    """An auth-degraded edit hop journals edit_degraded_auth; the article is
    still created from the un-edited draft."""
    import pipeline_cli
    from research.research import validate_research as _vr  # noqa: F401  (patched below)

    state_file = tmp_path / "pipeline.jsonl"
    monkeypatch.setattr(pipeline_cli, "STATE_FILE", state_file)
    monkeypatch.setattr(pipeline_cli, "validate_research", lambda r, min_facts=3: (True, [], []))
    monkeypatch.setattr(
        pipeline_cli, "research_topic",
        lambda topic, kw, config=None, **k: make_research(),
    )
    monkeypatch.setattr(
        pipeline_cli, "draft_article",
        lambda topic, kw, research, target_words=1800, config=None, **k: make_draft(),
    )
    degraded = EditedDraft(
        markdown=make_draft().markdown,
        word_count=make_draft().word_count,
        used_facts=list(make_draft().used_facts),
        edit_report="editor unavailable (auth) — kept original draft",
        failure_record={
            "kind": "stage_degraded_auth",
            "stage": "edit",
            "outcome": "kept_original_draft",
            "hops": [{"kind": "provider_auth_failure", "stage": "edit", "provider": "gemini",
                      "model": "gemini-2.5-flash", "status": 401,
                      "alarm": "Gemini key invalid - rotation needed"}],
            "error": "gemini/gemini-2.5-flash -> HTTP 401 (auth rejected)",
        },
    )
    monkeypatch.setattr(
        pipeline_cli, "edit_draft",
        lambda draft, topic, kw, research, config=None, **k: degraded,
    )

    client = FakeStrapi()
    cfg = Config(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="key",
        first_n_human_review=0,
    )
    result = pipeline_cli.draft_one(client, cfg, "esim-plans")

    # Pipeline continued: article created from the (un-edited) draft
    assert result["articleDocumentId"] == "article-1"
    assert len(client.articles) == 1

    # The rotation need is journaled as a structured event
    lines = [json.loads(l) for l in state_file.read_text().splitlines()]
    auth_events = [e for e in lines if e.get("event") == "edit_degraded_auth"]
    assert len(auth_events) == 1
    evt = auth_events[0]
    assert evt["slug"] == "esim-plans"
    assert evt["kind"] == "stage_degraded_auth"
    assert evt["hops"][0]["status"] == 401
    assert evt["hops"][0]["alarm"] == "Gemini key invalid - rotation needed"
    # No key material ever lands in the journal
    assert "g-key" not in state_file.read_text()
