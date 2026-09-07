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


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    """Route _append_state to a tmp file so tests never pollute the real
    engine/state/pipeline.jsonl audit log."""
    import pipeline_cli

    monkeypatch.setattr(pipeline_cli, "STATE_FILE", tmp_path / "pipeline.jsonl")


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

    def count_published(self):
        return 0

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
    # Editor stage: pass-through (edited == drafted) so no HTTP is touched.
    from editor.editor import EditedDraft

    monkeypatch.setattr(
        pipeline_cli, "edit_draft",
        lambda draft, topic, kw, research, config=None, **k: EditedDraft(
            markdown=draft.markdown,
            word_count=draft.word_count,
            used_facts=list(draft.used_facts),
            edit_report="test pass-through",
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


def _make_high_conf_draft():
    body = (
        "# Best eSIM Travel Plans for Budget Digital Nomads in 2026\n\n"
        "Picture this: you land in Tokyo, and eSIM travel saves you $100 per border. "
        "Here's the thing — roaming is a scam you don't have to pay. eSIM travel for "
        "digital nomads cuts costs by 80%.\n\n"
        "## Top eSIM Plans\n"
        "Airalo covers 200+ countries from $15.\n"
        "## Holafly\n"
        "Holafly has unlimited data plans.\n"
        "## Nomad\n"
        "Nomad sells regional packages.\n"
        "## Saily\n"
        "Saily is the newest budget pick.\n\n"
        "## FAQ\n"
        "### Is eSIM better than roaming?\nYes, much cheaper.\n"
        "### Can I keep my number?\nYes.\n"
        "### How much does it cost?\nAbout $15.\n"
    )
    return body


def test_draft_one_autopublishes_when_flag_on_nonsensitive_high_conf(monkeypatch):
    client = FakeStrapi()
    client.topic["attributes"].update({"slug": "esim-plans", "category": "gear", "primaryKeyword": "eSIM travel"})
    cfg = make_cfg()
    cfg = Config(
        strapi_url=cfg.strapi_url, strapi_engine_token=cfg.strapi_engine_token,
        openrouter_api_key=cfg.openrouter_api_key,
        auto_publish_enabled=True, first_n_human_review=0,
    )

    import pipeline_cli
    from research.research import Fact, ResearchResult
    from writer.writer import ArticleDraft
    from editor.editor import EditedDraft
    from seo.analyze import SEOReport

    monkeypatch.setattr(
        pipeline_cli, "research_topic",
        lambda topic, kw, config=None, **k: ResearchResult(
            topic=topic,
            facts=[
                Fact(claim="Airalo covers 200+ countries.", source_url="https://airalo.com"),
                Fact(claim="Roaming costs $50+ per trip.", source_url="https://example.com/r"),
                Fact(claim="eSIM cuts roaming cost by 80%.", source_url="https://example.com/e"),
            ],
        ),
    )
    monkeypatch.setattr(pipeline_cli, "validate_research", lambda r, min_facts=3: (True, [], []))
    body = _make_high_conf_draft()
    monkeypatch.setattr(
        pipeline_cli, "draft_article",
        lambda *a, **k: ArticleDraft(markdown=body, word_count=len(body.split()),
                                     used_facts=["Airalo covers 200+ countries."]),
    )
    monkeypatch.setattr(
        pipeline_cli, "edit_draft",
        lambda draft, topic, kw, research, config=None, **k: EditedDraft(
            markdown=draft.markdown, word_count=draft.word_count,
            used_facts=list(draft.used_facts), edit_report="pass",
        ),
    )
    # Stub the deterministic scorer so we isolate the publish branch.
    monkeypatch.setattr(
        pipeline_cli, "analyze_seo",
        lambda draft, pk, secondary_keywords=None, research=None: SEOReport(
            seo_score=85, confidence=90, meta_title="X", meta_description="Y", excerpt="Z",
        ),
    )

    result = draft_one(client, cfg, "esim-plans")

    assert result["published"] is True
    article_statuses = [s[1].get("status") for s in client.published]
    assert "published" in article_statuses
    # topic marked published
    assert client.topic_updates[-1][1].get("status") == "published"


def test_draft_one_never_autopublishes_when_flag_off(monkeypatch):
    client = FakeStrapi()
    client.topic["attributes"].update({"slug": "esim-plans", "category": "gear", "primaryKeyword": "eSIM travel"})
    cfg = make_cfg()  # auto_publish_enabled defaults False

    import pipeline_cli
    from research.research import Fact, ResearchResult
    from writer.writer import ArticleDraft
    from editor.editor import EditedDraft
    from seo.analyze import SEOReport

    monkeypatch.setattr(
        pipeline_cli, "research_topic",
        lambda topic, kw, config=None, **k: ResearchResult(
            topic=topic,
            facts=[
                Fact(claim="Airalo covers 200+ countries.", source_url="https://airalo.com"),
                Fact(claim="Roaming costs $50+ per trip.", source_url="https://example.com/r"),
                Fact(claim="eSIM cuts roaming cost by 80%.", source_url="https://example.com/e"),
            ],
        ),
    )
    monkeypatch.setattr(pipeline_cli, "validate_research", lambda r, min_facts=3: (True, [], []))
    body = _make_high_conf_draft()
    monkeypatch.setattr(
        pipeline_cli, "draft_article",
        lambda *a, **k: ArticleDraft(markdown=body, word_count=len(body.split()),
                                     used_facts=["Airalo covers 200+ countries."]),
    )
    monkeypatch.setattr(
        pipeline_cli, "edit_draft",
        lambda draft, topic, kw, research, config=None, **k: EditedDraft(
            markdown=draft.markdown, word_count=draft.word_count,
            used_facts=list(draft.used_facts), edit_report="pass",
        ),
    )
    monkeypatch.setattr(
        pipeline_cli, "analyze_seo",
        lambda draft, pk, secondary_keywords=None, research=None: SEOReport(
            seo_score=85, confidence=90, meta_title="X", meta_description="Y", excerpt="Z",
        ),
    )

    result = draft_one(client, cfg, "esim-plans")

    assert result["published"] is False
    article_statuses = [s[1].get("status") for s in client.published]
    assert "published" not in article_statuses
    assert article_statuses[-1] == "in_review"
