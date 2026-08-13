"""Tests for the pipeline orchestrator (mock Strapi client + patched stages)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from pipeline_cli import draft_one  # noqa: E402


def make_cfg():
    return Config(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="key",
        first_n_human_review=3,
    )


class FakeStrapi:
    """Duck-typed stand-in for StrapiClient."""

    def __init__(self):
        self.topic = {
            "documentId": "topic-1",
            "attributes": {
                "slug": "feie-guide",
                "title": "FEIE Guide for Digital Nomads",
                "primaryKeyword": "FEIE",
                "targetKeywords": ["FEIE", "expat taxes"],
                "category": "taxes",
                "targetWordCount": 1800,
            },
        }
        self.topic_updates = []
        self.articles = []
        self.published = []

    def get_topic_by_slug(self, slug):
        return self.topic if self.topic["attributes"]["slug"] == slug else None

    def update_topic(self, doc_id, fields):
        self.topic_updates.append((doc_id, fields))

    def create_article(self, fields):
        doc = {"documentId": "article-1", "attributes": dict(fields)}
        self.articles.append(doc)
        return {"data": doc}

    def update_article(self, doc_id, fields):
        self.published.append((doc_id, fields))

    def close(self):
        pass


def test_draft_one_chains_stages_and_writes_article(monkeypatch):
    client = FakeStrapi()
    cfg = make_cfg()

    # Patch the names as imported INTO pipeline_cli (it does `from x import y`),
    # and patch analyze_seo too so no real voice/API is touched.
    import pipeline_cli
    from research.research import Fact, ResearchResult, validate_research
    from writer.writer import ArticleDraft

    monkeypatch.setattr(
        pipeline_cli, "research_topic",
        lambda topic, kw, config=None, **kw2: ResearchResult(
            topic=topic,
            facts=[
                Fact(claim="The FEIE allows expats to exclude up to $126,500.",
                     source_url="https://irs.gov/feie"),
                Fact(claim="Nomads must meet the Physical Presence Test.",
                     source_url="https://irs.gov/pp"),
                Fact(claim="FEIE may preclude the Foreign Tax Credit.",
                     source_url="https://example.com/ftc"),
            ],
        ),
    )
    monkeypatch.setattr(pipeline_cli, "validate_research", lambda r, min_facts=3: (True, [], []))
    monkeypatch.setattr(
        pipeline_cli, "draft_article",
        lambda *a, **k: ArticleDraft(
            markdown=(
                "# FEIE Guide for Digital Nomads in 2025\n\n"
                "Picture this: the taxman.\n\n"
                "## The FEIE Basics\n"
                "The FEIE allows expats to exclude up to $126,500.\n"
                "## Physical Presence Test\n"
                "Nomads must meet the Physical Presence Test.\n"
                "## Foreign Tax Credit\n"
                "FEIE may preclude the Foreign Tax Credit.\n"
                "## Bottom Line\n"
                "Do the math.\n\n"
                "## FAQ\n"
                "### Is FEIE automatic?\n"
                "No.\n"
                "### Can I combine FEIE and FTC?\n"
                "Usually not.\n"
                "### Do I still file?\n"
                "Yes.\n"
            ),
            word_count=120,
            used_facts=["The FEIE allows expats to exclude up to $126,500."],
        ),
    )

    result = draft_one(client, cfg, "feie-guide")

    assert result["slug"] == "feie-guide"
    assert result["articleDocumentId"] == "article-1"
    assert result["confidence"] > 0
    assert result["decision"] in ("auto_publish", "needs_review", "reject", "quarantine")
    # Article was written to Strapi
    assert len(client.articles) == 1
    assert client.articles[0]["attributes"]["bodyMarkdown"].startswith("# FEIE")
    # Topic was marked researching -> drafting -> final
    statuses = [upd[1].get("status") for upd in client.topic_updates]
    assert "researching" in statuses
    assert "drafting" in statuses
    # Sensitive topic (taxes) must be quarantined -> NOT auto-published
    final = statuses[-1]
    assert final in ("in_review", "failed")
    # Article status updates exist, but never a `published` status (quarantine)
    article_statuses = [s[1].get("status") for s in client.published]
    assert "published" not in article_statuses
    assert article_statuses  # an in_review/rejected status was set
