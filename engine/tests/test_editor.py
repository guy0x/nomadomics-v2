"""Tests for the editor stage (voice/structure/grounding QA pass)."""
import json

import pytest

from config import Config
from editor.editor import EditedDraft, _extract_edit, edit_draft
from research.research import Fact, ResearchResult
from writer.writer import ArticleDraft


def make_cfg(**over):
    kw = dict(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="or-key",
        gemini_api_key="g-key",
    )
    kw.update(over)
    return Config(**kw)


def _long_body(prefix="Best eSIM Plans"):
    # >500 chars so the editor's 500-char floor keeps the edited markdown.
    filler = (
        "Picture this: you land in Bangkok, still half-asleep from the redeye, and your "
        "carrier has already billed you $50 for the privilege of receiving one spam text. "
        "Roaming is a scam, and eSIMs are the loophole. A travel eSIM drops that border-crossing "
        "bill to a flat $15, sometimes less, and you never touch a plastic SIM tray again. "
        "The math is simple: five countries in a month at $10 saved each is $50 back in your "
        "pocket, every single trip. Here's the thing — most nomads don't switch because they "
        "think setup is a hassle. It isn't. Scan a QR code, tap install, and you're online "
        "before your luggage hits the belt. "
    )
    return (
        f"# {prefix} for Digital Nomads in 2026\n\n{filler}\n\n"
        "## Airalo\nAiralo covers 200+ countries from $15 per plan.\n\n"
        "## Bottom Line\nPick the plan that fits your route, not your ego.\n\n"
        "## FAQ\n### Is eSIM better than roaming?\nYes, dramatically cheaper.\n"
        "### Can I keep my number?\nYes, with dual-SIM phones.\n"
        "### How much does it cost?\nAbout $15 per plan.\n"
    )


def make_draft():
    body = _long_body()
    return ArticleDraft(markdown=body, word_count=len(body.split()), used_facts=["Airalo covers 200+ countries."])


def make_research():
    return ResearchResult(
        topic="eSIM",
        facts=[
            Fact(claim="Airalo covers 200+ countries.", source_url="https://airalo.com"),
            Fact(claim="Roaming costs average $50+ per trip.", source_url="https://example.com/r"),
        ],
    )


def sample_edit_json():
    body = _long_body().replace(
        "you land in Bangkok", "you touch down in Bangkok", 1
    )
    return json.dumps({"markdown": body, "edit_report": "- tightened opener\n- kept facts grounded"})


def test_extract_edit_parses_json():
    d = make_draft()
    e = _extract_edit(sample_edit_json(), d)
    assert e.has_content
    assert "Best eSIM Plans" in e.markdown
    assert e.word_count > 0
    assert e.used_facts == d.used_facts  # facts preserved
    assert "tightened opener" in e.edit_report


def test_extract_edit_falls_back_to_original_when_unparseable():
    d = make_draft()
    e = _extract_edit("this is not json at all", d)
    assert e.markdown == d.markdown
    assert e.used_facts == d.used_facts
    assert "unparseable" in e.edit_report


class FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
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


def test_edit_draft_with_mock_client_routes_to_gemini():
    client = FakeClient([FakeResp(200, {"choices": [{"message": {"content": sample_edit_json()}}]})])
    e = edit_draft(
        make_draft(), "Best eSIM Plans", "eSIM", make_research(),
        config=make_cfg(), http_client=client, model="gemini-2.5-flash",
    )
    assert e.has_content
    # routed to the Gemini OpenAI-compatible endpoint
    assert "generativelanguage.googleapis.com" in client.calls[0][0]
    assert client.calls[0][2]["Authorization"] == "Bearer g-key"


def test_edit_draft_degrades_to_original_on_total_failure():
    client = FakeClient([FakeResp(500, {"error": "boom"})])
    d = make_draft()
    e = edit_draft(d, "T", "kw", make_research(), config=make_cfg(), http_client=client, model="m:free", max_retries=0)
    assert e.markdown == d.markdown
    assert "editor unavailable" in e.edit_report
