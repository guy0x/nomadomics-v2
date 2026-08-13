"""Tests for the research module (mocked OpenRouter client)."""
import pytest

from research.research import (
    Fact,
    ResearchResult,
    _parse_json_response,
    research_topic,
    validate_research,
)


class FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("httpx").HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self
            )

    def json(self):
        return self._json


class FakeClient:
    """Minimal httpx-like client for tests. Returns canned responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        if isinstance(self.responses[0], Exception):
            raise self.responses.pop(0)
        return self.responses.pop(0)


def sample_content():
    return """{
      "topic": "Digital Nomad Taxes",
      "facts": [
        {"claim": "FEIE excludes up to ~$120k of foreign earned income.",
         "why_it_matters": "Directly reduces taxable income for nomads.",
         "source_title": "IRS", "source_url": "https://irs.gov/feie",
         "published_date": "2025-01-01", "confidence": "high"},
        {"claim": "Nomad visas are offered by 50+ countries.",
         "why_it_matters": "Expands where nomads can legally stay long-term.",
         "source_title": "Nomad List", "source_url": "https://nomadlist.com/visas",
         "published_date": "2025-06-01", "confidence": "medium"},
        {"claim": "Bali coworking costs ~$150/mo.",
         "why_it_matters": "Budget planning for remote workers.",
         "source_title": "Sample Blog", "source_url": "https://example.com/bali",
         "published_date": "2024-09-01", "confidence": "medium"}
      ],
      "keywords": ["nomad taxes", "FEIE", "visas", "cost of living"]
    }"""


def make_result():
    parsed = _parse_json_response(sample_content())
    from research.research import _parse_facts

    return ResearchResult(
        topic=parsed["topic"], facts=_parse_facts(parsed), keywords=parsed["keywords"]
    )


def test_parse_json_response_handles_fenced_output():
    raw = "```json\n" + sample_content() + "\n```"
    parsed = _parse_json_response(raw)
    assert len(parsed["facts"]) == 3
    assert parsed["facts"][0]["source_url"].startswith("https://")


def test_parse_json_response_handles_plain_output():
    parsed = _parse_json_response(sample_content())
    assert parsed["topic"] == "Digital Nomad Taxes"


def test_research_topic_returns_facts_with_mock_client():
    cfg = None
    content = sample_content()
    client = FakeClient(
        [
            FakeResp(200, {"choices": [{"message": {"content": content}}]}),
        ]
    )
    result = research_topic("Digital Nomad Taxes", "FEIE", http_client=client, model="qwen/qwen3-32b:free")
    assert len(result.facts) == 3
    assert all(f.source_url for f in result.facts)
    assert result.has_valid_research is True
    assert client.calls[0][2]["Authorization"].startswith("Bearer ")


def test_research_topic_retries_on_429_then_succeeds():
    content = sample_content()
    client = FakeClient(
        [
            FakeResp(429),
            FakeResp(200, {"choices": [{"message": {"content": content}}]}),
        ]
    )
    result = research_topic("X", "", http_client=client, model="m:free")
    assert len(result.facts) == 3


def test_research_topic_raises_after_all_retries_and_models_fail():
    client = FakeClient([FakeResp(500, {"error": "boom"})])
    with pytest.raises(Exception):
        research_topic("X", "", http_client=client, model="m:free", max_retries=0)


def test_validate_research_ok():
    ok, errors, warnings = validate_research(make_result())
    assert ok is True
    assert errors == []


def test_validate_research_too_few_facts():
    result = make_result()
    result.facts = result.facts[:1]
    ok, errors, warnings = validate_research(result, min_facts=3)
    assert ok is False
    assert any("need >= 3" in e for e in errors)


def test_validate_research_missing_url():
    result = make_result()
    result.facts[0].source_url = ""
    ok, errors, warnings = validate_research(result)
    assert ok is False
    assert any("missing source_url" in e for e in errors)


def test_validate_research_warns_on_stale():
    result = make_result()
    result.facts[1].published_date = "2019-01-01"
    ok, errors, warnings = validate_research(result)
    assert ok is True  # stale is a warning, not a rejection
    assert any("stale source" in w for w in warnings)
