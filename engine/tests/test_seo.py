"""Tests for the deterministic SEO + confidence scorer."""
import sys, json

from research.research import Fact, ResearchResult
from writer.writer import ArticleDraft
from seo.analyze import analyze_seo


def make_good_draft():
    body = (
        "# Best eSIM Travel Plans for Budget-Conscious Digital Nomads in 2025\n\n"
        "Picture this: you've just landed in Tokyo. You're ready to find "
        "ramen and eSIM travel plans cost too much. Here's the thing — the "
        "best eSIM travel for nomads saves you $100 per border crossing.\n\n"
        "## Top 5 eSIM Plans for Every Nomad Profile\n"
        "## Airalo\n"
        "Airalo offers coverage in 200+ countries and data plans from $15.\n"
        "## Holafly\n"
        "Holafly offers unlimited data for digital nomads.\n"
        "## Nomad\n"
        "Nomad offers regional packages across Europe and Asia.\n"
        "## Saily\n"
        "Saily is the newest budget option on the market.\n"
        "## Conclusion\n"
        "The right plan depends on your needs.\n\n"
        "## FAQ\n"
        "### Is an eSIM better than roaming?\n"
        "Yes, eSIM travel is cheaper.\n"
        "### Can I keep my number with an eSIM?\n"
        "Yes.\n"
        "### How much does an eSIM cost?\n"
        "About $15.\n"
    )
    d = ArticleDraft(markdown=body, word_count=len(body.split()))
    d.used_facts = [f.claim for f in make_research().facts]
    return d


def make_hard_draft():
    return ArticleDraft(
        markdown="# Generic Title\n\nThis article explores travel options.",
        word_count=10,
    )


def make_research():
    return ResearchResult(
        topic="eSIM",
        facts=[
            Fact(claim="eSIM allows travelers to bypass expensive roaming fees.",
                 source_url="https://example.com/a"),
            Fact(claim="Airalo offers coverage in 200+ countries.",
                 source_url="https://example.com/b"),
            Fact(claim="Holafly specializes in unlimited data plans.",
                 source_url="https://example.com/c"),
            Fact(claim="Nomad offers competitive regional packages.",
                 source_url="https://example.com/d"),
        ],
    )


def test_good_draft_high_seo():
    report = analyze_seo(make_good_draft(), "eSIM travel",
                         secondary_keywords=["digital nomads", "eSIM"], research=make_research())
    assert report.seo_score >= 70
    assert report.confidence >= 70


def test_good_draft_has_meta_and_excerpt():
    report = analyze_seo(make_good_draft(), "eSIM travel", research=make_research())
    assert report.meta_title
    assert report.meta_description
    assert report.excerpt


def test_poor_draft_flagged_with_fixes():
    report = analyze_seo(make_hard_draft(), "eSIM travel", research=make_research())
    assert report.seo_score < 70
    assert len(report.fixes) > 0


def test_confidence_weighted_fusion():
    good = analyze_seo(make_good_draft(), "eSIM travel", research=make_research())
    bad = analyze_seo(make_hard_draft(), "eSIM travel", research=make_research())
    assert good.confidence > bad.confidence


def test_breakdown_fields_present():
    report = analyze_seo(make_good_draft(), "eSIM travel", research=make_research())
    assert "n_h2" in report.breakdown
    assert "n_faq" in report.breakdown
    assert "words" in report.breakdown
    assert "density" in report.breakdown
    assert "structure" in report.breakdown


def test_rich_structure_scores_higher_than_prose_wall():
    rich = (
        "# Best eSIM Plans for Digital Nomads in 2026\n\n"
        "Picture this: you land in Bangkok and roaming just billed you $50. "
        "An eSIM cuts that to $15.\n\n"
        "## Airalo\n"
        "- 200+ countries\n"
        "- Plans from $15\n"
        "- Instant QR activation\n\n"
        "## Holafly\n"
        "- Unlimited data\n"
        "- 100+ countries\n"
        "- No speed caps\n\n"
        "### Pros\n- Cheap\n- Easy\n\n"
        "### Cons\n- No phone number\n\n"
        "## Comparison\n"
        "| Provider | Countries | Price |\n"
        "| --- | --- | --- |\n"
        "| Airalo | 200+ | $15 |\n"
        "| Holafly | 100+ | $19 |\n\n"
        "## FAQ\n"
        "### Is eSIM better than roaming?\nYes.\n"
        "### Can I keep my number?\nYes.\n"
        "### How much does it cost?\nAbout $15.\n"
    )
    rich_draft = ArticleDraft(markdown=rich, word_count=len(rich.split()))
    rich_draft.used_facts = [f.claim for f in make_research().facts]
    report = analyze_seo(rich_draft, "eSIM travel", research=make_research())
    assert report.structure_score >= 50
    # wall of prose has near-zero structure
    poor = analyze_seo(make_hard_draft(), "eSIM travel", research=make_research())
    assert rich_draft and report.structure_score > poor.structure_score
