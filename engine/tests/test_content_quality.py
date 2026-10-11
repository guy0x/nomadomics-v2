"""Canonical content-quality gates derived from the slide-6 audit findings."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from invariants import (  # noqa: E402
    article_invariant_errors,
    ensure_body_citations,
    link_hygiene_issues,
    opening_pattern_issues,
    source_section_issues,
)

META_DESCRIPTION = (
    "Living costs, visa rules and internet speeds differ in every hub. "
    "This guide compares the practical numbers so you can pick a base "
    "before you book a flight."
)
FACTS = [
    {"source_url": "https://irs.gov/a", "source_title": "IRS A"},
    {"source_url": "https://travel.state.gov/b", "source_title": "State B"},
]


def article(body: str) -> dict:
    return {
        "excerpt": "A real excerpt sentence.",
        "metaTitle": "A title",
        "metaDescription": META_DESCRIPTION,
        "slug": "yearless-slug",
        "bodyMarkdown": body,
    }


def clean_sources() -> str:
    return (
        "# A guide\n\n"
        "The fee is $10 and the threshold is $20.\n\n"
        "## Sources\n\n"
        "- [IRS A](https://irs.gov/a)\n"
        "- [State B](https://travel.state.gov/b)\n"
    )


def test_retired_generic_openers_are_blocked():
    assert opening_pattern_issues("# Title\n\nPicture this: a generic scene.")
    assert opening_pattern_issues("# Title\n\nImagine this: another generic scene.")


def test_topic_specific_opening_is_allowed():
    assert opening_pattern_issues(
        "# Title\n\nA $20 fee can erase a week's savings if you choose the wrong rail."
    ) == []


def test_sources_section_requires_two_real_visible_links():
    body = (
        "# Guide\n\nSee [A](https://irs.gov/a) and [B](https://travel.state.gov/b).\n"
    )
    assert source_section_issues(body) == ["missing visible Sources section"]
    assert source_section_issues(clean_sources()) == []


def test_backstop_adds_visible_sources_even_when_inline_citations_exist():
    body = (
        "# Guide\n\nSee [A](https://irs.gov/a) and [B](https://travel.state.gov/b).\n"
    )
    out = ensure_body_citations(body, FACTS)
    assert "## Sources" in out
    assert out.count("https://irs.gov/a") == 2
    assert out.count("https://travel.state.gov/b") == 2
    assert link_hygiene_issues(out) == []
    assert ensure_body_citations(out, FACTS) == out


def test_shared_article_gate_wires_opening_sources_and_link_hygiene():
    errors = article_invariant_errors(article(clean_sources()))
    assert errors == []

    generic = clean_sources().replace("The fee is $10", "Picture this: the fee is $10")
    assert "generic opening template is not allowed" in article_invariant_errors(article(generic))

    missing_sources = clean_sources().replace("## Sources", "## Related reading")
    assert "missing visible Sources section" in article_invariant_errors(article(missing_sources))
