"""Title-cap guard for the draft lane (t_22a3bbdc).

Bug found live: topic `get-paid-freelancer-abroad` drafted fine (1958 words,
edit ok) and then died at the write — `Strapi POST /api/articles -> 400: title
must be at most 70 characters` (the seed title is 71 chars). The article's title
IS the seed topic title, and while `article.title` is capped at 70 by the Strapi
schema the `topics` table has no limit at all, so nothing in the engine ever
checked it. Worse, the failed write stranded the topic in `failed`, which
`list_pending_topics` (status=pending) can never pick up again.

These tests pin:
  1. `_fit_title` — word-boundary truncation, parenthetical drop first, never
     empty for non-empty input;
  2. the constant against the real Strapi schema, so a schema move cannot drift;
  3. `draft_one` end-to-end: a 71-char seed title produces an article whose
     title fits the cap (and the topic still reaches a terminal status).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline_cli import TITLE_MAX_CHARS, _fit_title, draft_one  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARTICLE_SCHEMA = REPO_ROOT / "src" / "api" / "article" / "content-types" / "article" / "schema.json"

# The seed title that 400'd the 09-22 batch, verbatim (71 chars).
LONG_SEED_TITLE = "How to Get Paid as a Freelancer While Abroad (Invoices + Payment Rails)"


# --- 1. the helper ------------------------------------------------------------


def test_long_seed_title_fits_by_dropping_the_parenthetical():
    assert len(LONG_SEED_TITLE) == 71, "the regression fixture must exceed the cap"
    fitted = _fit_title(LONG_SEED_TITLE)
    assert fitted == "How to Get Paid as a Freelancer While Abroad"
    assert len(fitted) <= TITLE_MAX_CHARS


def test_short_title_is_untouched():
    assert _fit_title("Best Virtual Mailbox for Nomads") == "Best Virtual Mailbox for Nomads"


def test_exactly_at_the_cap_is_untouched():
    title = "x" * TITLE_MAX_CHARS
    assert _fit_title(title) == title


def test_over_cap_without_parentheticals_truncates_on_a_word_boundary():
    title = "Cheap International Money Transfers for Freelancers Living Abroad Guide"
    fitted = _fit_title(title)
    assert len(fitted) <= TITLE_MAX_CHARS
    assert title.startswith(fitted)
    assert not fitted.endswith(" ")
    # no half-word: the next character in the source is a space or nothing
    assert title[len(fitted)] == " "


def test_trailing_separator_is_not_left_dangling():
    fitted = _fit_title("Nomad Tax Guide: " + "y" * (TITLE_MAX_CHARS - 17) + " tail words here")
    assert len(fitted) <= TITLE_MAX_CHARS
    assert fitted[-1] not in " -–—:;,."


def test_single_long_word_still_fits_the_cap():
    """No space to break on — hard-cut rather than return something over the cap."""
    assert len(_fit_title("z" * 120)) <= TITLE_MAX_CHARS


def test_whitespace_is_collapsed_and_empty_input_is_safe():
    assert _fit_title("  Spaced   Out   Title ") == "Spaced Out Title"
    assert _fit_title("") == ""
    assert _fit_title(None) == ""


def test_every_produced_title_respects_an_explicit_limit():
    for title in (LONG_SEED_TITLE, "a b c d e f g h i j k l m n o p q r s t u v w x y z"):
        assert len(_fit_title(title, limit=20)) <= 20


# --- 2. the constant matches the CMS schema -----------------------------------


def test_title_max_chars_matches_the_strapi_schema():
    """Strapi validates `title` against this number; if the schema moves, the
    guard above must move with it (or the 400 comes straight back)."""
    schema = json.loads(ARTICLE_SCHEMA.read_text())
    assert schema["attributes"]["title"]["maxLength"] == TITLE_MAX_CHARS


def test_meta_fields_are_fitted_without_pinning_the_bug():
    """The other maxLength'd fields on the article must already be bounded where
    they are produced (seo.analyze), so `title` was the only unguarded write.

    This replaces the old pair of assertions that pinned the generator bug
    (t_7197386f): `test_seo.py:106` checked the ONE-CHAR ellipsis only, and this
    file's `len(_make_meta_desc('word ' * 200, 'kw')) <= maxLength` CERTIFIED the
    s[:157] + '...' hard cut as 'fitted' because it lands on exactly 160. The real
    negative cases are: no literal ellipsis anywhere, the metaTitle value leaving
    room for the 13c ' · Nomadomics' brand within the 60c budget, and the
    description being 120-160c of copy distinct from the excerpt.
    """
    from seo.analyze import _first_sentence, _make_meta_desc, _make_meta_title

    schema = json.loads(ARTICLE_SCHEMA.read_text())["attributes"]

    # metaTitle: 47c value max so value + " · Nomadomics" (13c) fits TITLE_BUDGET.
    t = _make_meta_title("kw", "# " + "t" * 300)
    assert len(t) <= schema["metaTitle"]["maxLength"]
    assert not t.endswith("...") and "\u2026" not in t
    assert len(t) + 13 <= 60, t

    # metaDescription: a 200c word-run opener must produce a fitted, distinct,
    # sentence-shaped description — never the certified 'word...' hard cut.
    body = "# T\n\n" + "word " * 200 + "\n\nMore words and context.\n"
    md = _make_meta_desc(body, "kw")
    excerpt = _first_sentence(body)
    assert md != excerpt
    assert "..." not in md and "\u2026" not in md
    assert 120 <= len(md) <= schema["metaDescription"]["maxLength"]
    assert md.endswith((".", "!", "?"))


def test_seo_mock_cap_guard_is_now_redundant():
    """The write-time invariant (engine/invariants.py::check_write_invariants)
    now refuses excerpt-duplicate, template-tail and ellipsis-cut meta shapes —
    the shapes this schema test used to stand in for."""
    from invariants import meta_description_issues, meta_title_issues

    assert any("duplicates the excerpt" in e for e in meta_description_issues("Same exact copy.", "Same exact copy."))
    assert any("template tail" in e for e in meta_description_issues("Fine copy. Learn how to save money on vpn.", "Different."))
    assert any("ellipsis cut" in e for e in meta_description_issues("Fine copy that ends...", "Different."))
    assert any("ellipsis cut" in e for e in meta_title_issues("Best VPNs for Travelers..."))


# --- 3. draft_one end-to-end with an over-cap seed -----------------------------


class FakeStrapi:
    """Duck-typed StrapiClient (same shape as tests/test_pipeline.FakeStrapi)."""

    def __init__(self, title: str):
        self.topic = {
            "slug": "get-paid-freelancer-abroad",
            "title": title,
            "primaryKeyword": "get paid as a freelancer abroad",
            "targetKeywords": ["freelancer payments", "payment rails"],
            "category": "digital-nomad",
            "targetWordCount": 1800,
            "documentId": "topic-freelance",
        }
        self.topic_updates = []
        self.articles = []
        self.article_updates = []

    def get_topic_by_slug(self, slug):
        return dict(self.topic) if slug == self.topic["slug"] else None

    def update_topic(self, doc_id, fields):
        self.topic_updates.append((doc_id, fields))

    def list_authors(self):
        raise AttributeError("no authors content type in this fake")

    def count_published(self):
        return 0

    def create_article(self, fields):
        # Strapi's own validation, mimicked: >maxLength is a 400, not a warning.
        if len(fields.get("title", "")) > TITLE_MAX_CHARS:
            raise AssertionError(
                f"Strapi would 400 this title ({len(fields['title'])} chars): {fields['title']!r}"
            )
        doc = {"documentId": "article-freelance", "attributes": dict(fields)}
        self.articles.append(doc)
        return {"data": doc}

    def update_article(self, doc_id, fields, *, status="draft"):
        self.article_updates.append((doc_id, fields))

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    import pipeline_cli

    monkeypatch.setattr(pipeline_cli, "STATE_FILE", tmp_path / "pipeline.jsonl")


def _patch_stages(monkeypatch):
    """Patch the LLM stages as imported into pipeline_cli — no HTTP, no spend."""
    import pipeline_cli
    from editor.editor import EditedDraft
    from research.research import Fact, ResearchResult
    from writer.writer import ArticleDraft

    monkeypatch.setattr(
        pipeline_cli,
        "research_topic",
        lambda topic, kw, config=None, **k: ResearchResult(
            topic=topic,
            facts=[
                Fact(claim="Wise charges ~0.4% on transfers.", source_url="https://wise.com/a"),
                Fact(claim="Payoneer supports USD receiving accounts.", source_url="https://payoneer.com/b"),
                Fact(claim="Freelancers abroad file W-8BEN.", source_url="https://irs.gov/c"),
            ],
        ),
    )
    monkeypatch.setattr(pipeline_cli, "validate_research", lambda r, min_facts=3: (True, [], []))
    body = (
        "# How to Get Paid as a Freelancer While Abroad\n\n"
        "Picture this: your client wires money and 6% evaporates in fees.\n\n"
        "## Payment Rails Compared\n"
        "- Wise: ~0.4% mid-market\n"
        "- Payoneer: USD accounts\n\n"
        "## Paperwork\n"
        "Freelancers abroad file W-8BEN.\n\n"
        "## Bottom Line\n"
        "- Pick a rail\n\n"
        "## FAQ\n"
        "### Is Wise cheap?\n"
        "Usually.\n"
        "### Do I need a W-8BEN?\n"
        "Yes.\n"
        "### Can I keep USD?\n"
        "Yes.\n"
    )
    monkeypatch.setattr(
        pipeline_cli,
        "draft_article",
        lambda *a, **k: ArticleDraft(
            markdown=body, word_count=1200, used_facts=["Wise charges ~0.4% on transfers."]
        ),
    )
    monkeypatch.setattr(
        pipeline_cli,
        "edit_draft",
        lambda draft, topic, kw, research, config=None, **k: EditedDraft(
            markdown=draft.markdown,
            word_count=draft.word_count,
            used_facts=list(draft.used_facts),
            edit_report="test pass-through",
        ),
    )


def _cfg():
    from config import Config

    return Config(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="key",
    )


def test_draft_one_writes_a_fitting_title_for_an_over_cap_seed(monkeypatch):
    client = FakeStrapi(LONG_SEED_TITLE)
    _patch_stages(monkeypatch)

    result = draft_one(client, _cfg(), "get-paid-freelancer-abroad")

    assert len(client.articles) == 1, "the article must be created, not 400'd"
    written = client.articles[0]["attributes"]["title"]
    assert len(written) <= TITLE_MAX_CHARS
    assert written == "How to Get Paid as a Freelancer While Abroad"
    assert result["title"] == written
    # The run reached a terminal topic status instead of stranding the item.
    statuses = [u[1].get("status") for u in client.topic_updates]
    assert "researching" in statuses and "drafting" in statuses
    assert statuses[-1] in ("in_review", "published", "failed")


def test_draft_one_leaves_a_fitting_seed_title_alone(monkeypatch):
    client = FakeStrapi("How to Get Paid as a Freelancer Abroad")
    _patch_stages(monkeypatch)

    draft_one(client, _cfg(), "get-paid-freelancer-abroad")

    assert client.articles[0]["attributes"]["title"] == "How to Get Paid as a Freelancer Abroad"