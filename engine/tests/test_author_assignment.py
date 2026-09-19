"""Tests for byline assignment at article-creation time (pipeline_cli._pick_author).

The byline must keep the four-author split even without manual assignment, and must
never break the pipeline: a Strapi without the authors content type (or with no
author rows) is a valid state that yields no author field rather than an exception.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline_cli  # noqa: E402
from strapi import StrapiError  # noqa: E402


class FakeAuthorClient:
    def __init__(self, authors=None, boom=False):
        self.authors = authors or []
        self.boom = boom
        self.params = None

    def list_authors(self):
        if self.boom:
            raise StrapiError("Strapi GET /api/authors -> 404: not found")
        return self.authors


def author(slug, count, doc=None):
    return {"documentId": doc or f"doc-{slug}", "name": slug, "slug": slug, "articles": count}


def test_picks_the_author_with_the_fewest_articles():
    client = FakeAuthorClient([
        author("thiago-sharpe", 11), author("guy-mandel", 9),
        author("vincent-chin", 12), author("katie-wulfson", 10),
    ])

    assert pipeline_cli._pick_author(client) == "doc-guy-mandel"


def test_ties_break_on_slug_so_the_choice_is_deterministic():
    client = FakeAuthorClient([
        author("vincent-chin", 4), author("guy-mandel", 4),
        author("katie-wulfson", 4), author("thiago-sharpe", 4),
    ])

    # guy-mandel sorts first by slug
    assert pipeline_cli._pick_author(client) == "doc-guy-mandel"
    assert pipeline_cli._pick_author(client) == "doc-guy-mandel"


def test_a_brand_new_roster_starts_with_the_first_slug():
    client = FakeAuthorClient([
        author("vincent-chin", 0), author("guy-mandel", 0),
        author("katie-wulfson", 0), author("thiago-sharpe", 0),
    ])

    assert pipeline_cli._pick_author(client) == "doc-guy-mandel"


def test_missing_authors_content_type_returns_none_instead_of_raising():
    """A Strapi without the authors type must not break drafting."""
    assert pipeline_cli._pick_author(FakeAuthorClient(boom=True)) is None


def test_client_without_author_support_returns_none():
    """Duck-typed clients predating the byline must keep working."""
    class LegacyClient:
        pass

    assert pipeline_cli._pick_author(LegacyClient()) is None


def test_empty_roster_returns_none():
    assert pipeline_cli._pick_author(FakeAuthorClient([])) is None


def test_rows_without_a_document_id_are_ignored():
    client = FakeAuthorClient([
        {"documentId": None, "slug": "ghost", "articles": 0},
        author("guy-mandel", 7),
    ])

    assert pipeline_cli._pick_author(client) == "doc-guy-mandel"
