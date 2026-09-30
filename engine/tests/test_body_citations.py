"""The article body must carry the citations the publish gate counts.

Regression target (kanban t_8f1614e2): the draft lane validated the RESEARCH
FACTS' `source_url`s while `publish.article_invariant_errors()` counts https URLs
in the BODY — one gate, two different inputs. So an article could clear the write
check and still be permanently unpublishable: verified live 2026-09-25, every
non-quarantine `in_review` row (8 of them, conf 75-87) failed `fewer than 2 real
citations`, and a fresh 09-25 draft (`spain-digital-nomad-visa`, conf 90) was
written with `urls=0`. Now the body is topped up from the article's own research
facts and both lanes call the same implementation.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config  # noqa: E402
from invariants import article_invariant_errors, ensure_body_citations  # noqa: E402
from pipeline_cli import draft_one  # noqa: E402


def fact(url, title=""):
    return {"source_url": url, "source_title": title}


REAL_FACTS = [
    fact("https://www.irs.gov/feie", "IRS: Foreign Earned Income Exclusion"),
    fact("https://travel.state.gov/visas.html", "US State Dept: Visas"),
    fact("https://example.com/placeholder", "Placeholder host"),
]

CITATION_LESS_BODY = (
    "# FEIE Guide for Digital Nomads\n\n"
    "Picture this: the taxman, and you moving country to escape him.\n\n"
    "## The FEIE Basics\n"
    "The FEIE excludes foreign earned income.\n\n"
    "## Bottom Line\n"
    "Do the math.\n"
)


# --- the helper --------------------------------------------------------------

def test_body_without_citations_gains_a_sources_section():
    out = ensure_body_citations(CITATION_LESS_BODY, REAL_FACTS)

    assert "## Sources" in out
    assert "https://www.irs.gov/feie" in out
    assert "https://travel.state.gov/visas.html" in out
    assert out.startswith("# FEIE Guide")  # the article itself is untouched


def test_appended_citations_satisfy_the_publish_gate():
    out = ensure_body_citations(CITATION_LESS_BODY, REAL_FACTS)

    errors = article_invariant_errors({
        "excerpt": "An excerpt.",
        "metaTitle": "A meta title",
        "metaDescription": (
            "Living costs, visa rules and internet speeds differ in every hub. "
            "This guide compares the practical numbers so you can pick a base "
            "before you book a flight."
        ),
        "slug": "feie-guide",
        "bodyMarkdown": out,
    })

    assert errors == []


def test_without_the_backstop_the_same_body_fails_the_publish_gate():
    """Control: the two inputs really disagreed — the raw writer body fails."""
    errors = article_invariant_errors({
        "excerpt": "An excerpt.",
        "metaTitle": "A meta title",
        "metaDescription": (
            "Living costs, visa rules and internet speeds differ in every hub. "
            "This guide compares the practical numbers so you can pick a base "
            "before you book a flight."
        ),
        "slug": "feie-guide",
        "bodyMarkdown": CITATION_LESS_BODY,
    })

    assert errors == ["fewer than 2 real citations"]


def test_a_body_that_already_cites_two_real_sources_is_untouched():
    body = CITATION_LESS_BODY + "\nhttps://www.irs.gov/a\nhttps://www.irs.gov/b\n"

    assert ensure_body_citations(body, REAL_FACTS) == body


def test_placeholder_and_non_https_facts_are_never_cited():
    out = ensure_body_citations(
        CITATION_LESS_BODY,
        [
            fact("https://example.net/placeholder"),
            fact("http://insecure.example/thing"),
            fact("https://localhost/self"),
        ],
    )

    assert "example.com" not in out
    assert "## Sources" not in out  # nothing real to cite -> nothing appended


def test_only_the_missing_real_facts_are_appended():
    body = CITATION_LESS_BODY + "\nhttps://www.irs.gov/feie\n"

    out = ensure_body_citations(body, REAL_FACTS)

    assert out.count("https://www.irs.gov/feie") == 1
    assert "https://travel.state.gov/visas.html" in out


def test_duplicate_fact_urls_are_cited_once():
    out = ensure_body_citations(
        CITATION_LESS_BODY,
        [fact("https://www.irs.gov/feie"), fact("https://www.irs.gov/feie")],
    )

    assert out.count("https://www.irs.gov/feie") == 1


def test_it_is_idempotent():
    once = ensure_body_citations(CITATION_LESS_BODY, REAL_FACTS)

    assert ensure_body_citations(once, REAL_FACTS) == once


def test_dataclass_facts_are_supported():
    from research.research import Fact

    out = ensure_body_citations(
        CITATION_LESS_BODY,
        [Fact(claim="a", source_url="https://www.irs.gov/feie", source_title="IRS"),
         Fact(claim="b", source_url="https://travel.state.gov/visas.html")],
    )

    assert "- [IRS](https://www.irs.gov/feie)" in out


# --- the pipeline wiring -----------------------------------------------------

class FakeStrapi:
    """Duck-typed stand-in for StrapiClient (same shape as test_pipeline.py)."""

    def __init__(self, category="travel", slug="feie-guide"):
        self.topic = {
            "documentId": "topic-1",
            "slug": slug,
            "title": "FEIE Guide for Digital Nomads",
            "primaryKeyword": "FEIE",
            "targetKeywords": ["FEIE"],
            "category": category,
            "targetWordCount": 1800,
        }
        self.topic_updates = []
        self.articles = []
        self.writes = []

    def get_topic_by_slug(self, slug):
        return dict(self.topic) if slug == self.topic["slug"] else None

    def update_topic(self, doc_id, fields):
        self.topic_updates.append((doc_id, fields))

    def create_article(self, fields):
        doc = {"documentId": "article-1", "attributes": dict(fields)}
        self.articles.append(doc)
        return {"data": doc}

    def update_article(self, doc_id, fields, *, status="draft"):
        self.writes.append((doc_id, fields, status))

    def count_published(self):
        return 0

    def close(self):
        pass


def _wire(monkeypatch, client, tmp_path, *, body=CITATION_LESS_BODY, excerpt="An excerpt."):
    import pipeline_cli
    from research.research import Fact, ResearchResult
    from writer.writer import ArticleDraft
    from editor.editor import EditedDraft
    from seo.analyze import SEOReport

    monkeypatch.setattr(pipeline_cli, "STATE_FILE", tmp_path / "pipeline.jsonl")
    monkeypatch.setattr(pipeline_cli, "PUBLISH_LEDGER", tmp_path / "publish-ledger.jsonl")
    monkeypatch.setattr(pipeline_cli, "_ship_cover_art", lambda *a, **k: "generated")
    monkeypatch.setattr(
        pipeline_cli, "research_topic",
        lambda topic, kw, config=None, **k: ResearchResult(
            topic=topic,
            facts=[
                Fact(claim="The FEIE excludes foreign earned income.",
                     source_url="https://www.irs.gov/feie", source_title="IRS"),
                Fact(claim="Visas are issued per country.",
                     source_url="https://travel.state.gov/visas.html"),
                Fact(claim="A placeholder fact.", source_url="https://example.com/p"),
            ],
        ),
    )
    monkeypatch.setattr(pipeline_cli, "validate_research", lambda r, min_facts=3: (True, [], []))
    monkeypatch.setattr(
        pipeline_cli, "draft_article",
        lambda *a, **k: ArticleDraft(markdown=body, word_count=len(body.split()),
                                     used_facts=["The FEIE excludes foreign earned income."]),
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
            seo_score=85, confidence=90, meta_title="A meta title",
            meta_description=(
                "Living costs, visa rules and internet speeds differ in every hub. "
                "This guide compares the practical numbers so you can pick a base "
                "before you book a flight."
            ),
            excerpt=excerpt,
        ),
    )


def _cfg(**kw):
    return Config(
        strapi_url="http://localhost:1337", strapi_engine_token="tok",
        openrouter_api_key="key", first_n_human_review=3, **kw,
    )


def test_draft_one_writes_a_body_that_passes_the_publish_gate(monkeypatch, tmp_path):
    """A sensitive topic: quarantined, never published — but the row it leaves
    behind is now invariant-clean (proper excerpt AND two real citations)."""
    client = FakeStrapi(category="taxes", slug="feie-guide")
    _wire(monkeypatch, client, tmp_path)

    result = draft_one(client, _cfg(), "feie-guide")

    assert result["articleDocumentId"] == "article-1"
    assert result["decision"] == "quarantine"
    body = client.articles[0]["attributes"]["bodyMarkdown"]
    assert "## Sources" in body
    assert "https://example.com/p" not in body
    errors = article_invariant_errors({
        "excerpt": client.articles[0]["attributes"]["excerpt"],
        "metaTitle": client.articles[0]["attributes"]["metaTitle"],
        "metaDescription": client.articles[0]["attributes"]["metaDescription"],
        "slug": client.articles[0]["attributes"]["slug"],
        "bodyMarkdown": body,
    })
    assert errors == []
    # quarantined rows stay on the DRAFT layer
    assert {w[2] for w in client.writes} == {"draft"}


def test_draft_one_does_not_invent_citations_when_no_real_fact_exists(monkeypatch, tmp_path):
    """No real source -> no Sources section, and the write gate still rejects it
    (the pipeline must never fabricate a citation to satisfy its own gate)."""
    import pipeline_cli
    from research.research import Fact, ResearchResult

    client = FakeStrapi(category="travel", slug="feie-guide")
    _wire(monkeypatch, client, tmp_path)
    monkeypatch.setattr(
        pipeline_cli, "research_topic",
        lambda topic, kw, config=None, **k: ResearchResult(
            topic=topic, facts=[Fact(claim="x", source_url="https://example.com/p")],
        ),
    )

    result = draft_one(client, _cfg(), "feie-guide")

    assert result["articleDocumentId"] is None
    assert client.articles == []
    assert client.topic_updates[-1][1]["status"] == "failed"
    assert "fewer than 2 real citations" in client.topic_updates[-1][1]["lastError"]
