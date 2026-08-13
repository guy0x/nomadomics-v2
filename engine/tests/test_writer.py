"""Tests for the draft writer (mocked OpenRouter client)."""
import json

import pytest

from research.research import Fact, ResearchResult
from writer.writer import ArticleDraft, _extract_draft, draft_article, ensure_research_cited


def sample_article_json():
    body = (
        "# FEIE Guide for Digital Nomads in 2025\n\n"
        "Picture this: the taxman knocking on your hostel door. "
        "Actually, the IRS doesn't do that. But foreign earnings and U.S. "
        "federal income tax still collide for digital nomads everywhere.\n\n"
        "## How the FEIE Works\n\n"
        "The Foreign Earned Income Exclusion (FEIE) allows qualifying expats to "
        "exclude up to $126,500 of foreign earnings from US federal income tax "
        "for the 2024 tax year. That means hundreds — sometimes thousands — of "
        "dollars stay in your pocket every year.\n\n"
        "## What You Need to Know\n\n"
        "To qualify for FEIE, digital nomads must meet either the Physical "
        "Presence Test or the Bona Fide Residence Test. Understanding which one "
        "applies to your travel pattern is the difference between a big refund "
        "and a big headache.\n\n"
        "## Bottom Line\n\n"
        "Do the math before you file. And hire a professional who knows expat "
        "tax law if your income justifies it.\n\n"
        "## FAQ\n\n"
        "### Is the FEIE automatic?\n"
        "No. You must file Form 2555 with your U.S. tax return to claim it.\n\n"
        "### Can I use FEIE and the Foreign Tax Credit together?\n"
        "On different income, sometimes. On the same income, usually not — "
        "double-dipping is disallowed.\n\n"
        "### Do I still need to file if my income is fully excluded?\n"
        "Yes. The exclusion keeps you from paying tax, not from filing.\n"
    )
    return json.dumps(
        {
            "title": "FEIE Guide for Digital Nomads in 2025",
            "markdown": body,
            "word_count": len(body.split()),
            "used_facts": [
                "The Foreign Earned Income Exclusion (FEIE) allows qualifying expats to exclude "
                "up to $126,500 of foreign earnings from US federal income tax for the 2024 tax year."
            ],
        }
    )


def make_research():
    return ResearchResult(
        topic="FEIE Guide",
        facts=[
            Fact(claim="The Foreign Earned Income Exclusion (FEIE) allows qualifying expats to exclude up to $126,500 of foreign earnings from US federal income tax for the 2024 tax year.",
                 source_url="https://irs.gov/p746"),
            Fact(claim="To qualify for FEIE, digital nomads must meet either the Physical Presence Test or the Bona Fide Residence Test.",
                 source_url="https://irs.gov/feie"),
            Fact(claim="Using the FEIE may prevent a taxpayer from claiming the Foreign Tax Credit on the same income.",
                 source_url="https://example.com/ftc"),
        ],
    )


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


def test_extract_draft_parses_markdown_json():
    d = _extract_draft(sample_article_json())
    assert d.has_content
    assert d.markdown.startswith("# FEIE Guide")
    assert d.word_count > 90  # fixture body word count
    assert len(d.used_facts) == 1


def test_extract_draft_handles_fenced_output():
    d = _extract_draft("```json\n" + sample_article_json() + "\n```")
    assert d.has_content
    assert "Picture this" in d.markdown


def test_draft_article_with_mock_client():
    client = FakeClient([FakeResp(200, {"choices": [{"message": {"content": sample_article_json()}}]})])
    d = draft_article("FEIE", "FEIE", make_research(), http_client=client, model="google/gemma-4-26b-a4b-it:free")
    assert d.has_content
    assert d.markdown.startswith("# ")
    assert len(client.calls) == 1
    # auth header present
    assert client.calls[0][2]["Authorization"].startswith("Bearer ")


def test_draft_retries_on_429():
    client = FakeClient([
        FakeResp(429),
        FakeResp(200, {"choices": [{"message": {"content": sample_article_json()}}]}),
    ])
    d = draft_article("X", "", make_research(), http_client=client, model="m:free")
    assert d.has_content


def test_draft_falls_back_to_next_model():
    client = FakeClient([
        FakeResp(500, {"error": "boom"}),
        FakeResp(200, {"choices": [{"message": {"content": sample_article_json()}}]}),
    ])
    # config default fallback includes gemma-4-26b; model=None uses chain
    d = draft_article("X", "", make_research(), http_client=client, model=None, max_retries=0)
    assert d.has_content
    assert len(client.calls) == 2


def test_empty_draft_when_all_fail_raises():
    client = FakeClient([FakeResp(500, {"error": "boom"})])
    with pytest.raises(Exception):
        draft_article("X", "", make_research(), http_client=client, model="m:free", max_retries=0)


def test_ensure_research_cited_ok():
    d = _extract_draft(sample_article_json())
    ok, cited = ensure_research_cited(d, make_research(), min_cited=1)
    assert ok is True
    assert len(cited) >= 1


def test_ensure_research_cited_fail_when_none():
    d = ArticleDraft(markdown="# X\n\nNothing about FEIE at all here.", word_count=10)
    ok, cited = ensure_research_cited(d, make_research(), min_cited=1)
    assert ok is False
