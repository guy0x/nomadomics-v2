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


def test_long_opener_draft_uses_complete_excerpt_and_meta():
    """A long house-voice opener must not become a clipped card excerpt."""
    opener = (
        "Picture this: it is a Tuesday morning in Lisbon, the coworking space is "
        "still empty, and you have just opened a letter from the tax office that "
        "says you owe money in two countries at once, which is exactly the moment "
        "most digital nomads start looking for help."
    )
    assert len(opener) > 160
    body = (
        "# Best eSIM Travel Plans for Budget Nomads in 2026\n\n"
        f"{opener}\n\n"
        "An eSIM fixes the cost side of that problem.\n\n"
        "## Airalo\nAiralo covers 200+ countries.\n"
    )
    draft = ArticleDraft(markdown=body, word_count=len(body.split()))
    draft.used_facts = [f.claim for f in make_research().facts]

    report = analyze_seo(draft, "eSIM travel", research=make_research())
    assert report.excerpt == "An eSIM fixes the cost side of that problem."
    assert len(report.excerpt) <= 160
    assert report.excerpt.endswith((".", "!", "?", ")"))
    assert not report.excerpt.endswith(("...", "\u2026"))
    assert report.meta_description.endswith(".")
    assert not report.meta_description.endswith(("\u2026", "..."))
    assert report.meta_description != report.excerpt


def _pad_sentence(target: int) -> str:
    """A single sentence padded with words to ~`target` chars, on a word
    boundary, ending in a full stop — so tests can hit the four opener-length
    branches of the old `_make_meta_desc` (~60c / 140c / 152c / 200c)."""
    s = "Budget travel in Lisbon is cheaper than most nomads expect"
    while len(s) < target:
        s += " and worth planning for"
    if len(s) > target:
        s = s[:target].rsplit(" ", 1)[0]
    return s.rstrip() + "."


def test_meta_desc_does_not_word_cut_a_long_opening_sentence():
    from seo.analyze import _make_meta_desc

    body = (
        "# Satellite Internet for Nomads\n\n"
        "Traditional cellular hotspots and local SIM cards are brilliant until you leave the asphalt behind. "
        "If you are serious about working from unconventional coordinates without sacrificing your income, you need "
        "to understand how satellite internet performs in the wild.\n\n"
        "## Plans\nCompare the available options.\n"
    )
    md = _make_meta_desc(body, "satellite internet digital nomads")
    assert 120 <= len(md) <= 160
    assert md.endswith(".")
    assert "unconventional." not in md
    assert "unconventional coordinates" not in md


def test_meta_desc_four_branches_never_echoes_the_excerpt():
    """t_7197386f AC1: `_make_meta_desc` must never return the excerpt verbatim,
    never contain the migration template tail, never end in a literal ellipsis,
    and must stay within 120-160c — for every opener-length branch the old
    generator had (opener ~60c -> template tail, 140c/152c -> md == excerpt,
    200c -> s[:157] + '...')."""
    from seo.analyze import _first_sentence, _make_meta_desc

    for target in (60, 140, 152, 200):
        body = (
            "# Budget Travel Guide 2026\n\n"
            f"{_pad_sentence(target)}\n\n"
            "Most nomads blow their budget in the first week on flights, "
            "cafes and unprepared SIM plans. A few simple switches keep "
            "monthly costs under control without sacrificing the lifestyle.\n\n"
            "## Costs to watch\nFlights, accommodation and data.\n"
        )
        excerpt = _first_sentence(body)
        md = _make_meta_desc(body, "budget travel")
        assert md != excerpt, f"{target}c opener: md echoes the excerpt verbatim"
        assert "Learn how to save money on" not in md
        assert not md.endswith(("...", "\u2026")), f"{target}c opener: ellipsis cut"
        assert 120 <= len(md) <= 160, (
            f"{target}c opener: description {len(md)}c outside 120-160"
        )
        assert md.endswith((".", "!", "?", ")"))

def test_meta_title_value_leaves_room_for_the_brand():
    """t_7197386f: the served title is value + ' · Nomadomics' (13c) and must fit
    the 60c SERP budget (frontend/src/lib/seo.ts::TITLE_BUDGET); the generator
    must never emit the old base[:57] + '...' 60c ellipsis title."""
    from seo.analyze import _make_meta_title

    t = _make_meta_title("kw", "# Best eSIM Travel Plans for Budget-Conscious Digital Nomads in 2025")
    assert t == "Best eSIM Travel Plans for Budget-Conscious"
    assert not t.endswith("...") and "\u2026" not in t
    assert len(t) + 13 <= 60, f"branded title would exceed the budget: {t!r}"


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
