"""Tests for the deterministic slop finder in slop_rules.py."""

import pytest

from editor.slop_rules import check_text


# ── Clean prose (no findings) ───────────────────────────────────────────────

def test_clean_prose_returns_no_findings():
    text = (
        "You can save $200 a year by switching to a travel eSIM before your next "
        "flight. Airalo covers 200+ countries from $15 per plan. The math is "
        "simple: five countries at $10 saved each is $50 back in your pocket.\n\n"
        "## Bottom Line\nPick the plan that fits your route, not your ego.\n\n"
        "## FAQ\n### Is eSIM better than roaming?\nYes, dramatically cheaper."
    )
    findings = check_text(text)
    assert findings == [], f"Expected no findings, got {findings}"


# ── Generic intros ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("intro", [
    "In today's fast-paced world, staying connected is essential.",
    "In this article, we will explore the best eSIM options.",
    "Let's explore the world of travel eSIMs together.",
    "Welcome to the future of travel connectivity.",
])
def test_detects_generic_intro(intro):
    text = f"{intro}\n\nAiralo covers 200+ countries from $15 per plan."
    findings = check_text(text)
    assert any(f["rule_id"] == "generic_intro" for f in findings), \
        f"Expected generic_intro finding for: {intro}"


# ── Empty conclusions ──────────────────────────────────────────────────────

def test_detects_empty_conclusion():
    text = (
        "Airalo covers 200+ countries from $15 per plan.\n\n"
        "In conclusion, travel eSIMs are a great choice for nomads."
    )
    findings = check_text(text)
    assert any(f["rule_id"] == "empty_conclusion" for f in findings)


# ── Meta claims ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("claim", [
    "This comprehensive guide will teach you everything about eSIMs.",
    "This ultimate guide covers all you need to know.",
    "This article will show you the best eSIM options.",
])
def test_detects_meta_claims(claim):
    text = f"{claim}\n\nAiralo costs $15 per plan."
    findings = check_text(text)
    assert any(f["rule_id"] == "meta_claims" for f in findings), \
        f"Expected meta_claims finding for: {claim}"


# ── Hedge words ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("hedge", [
    "This could possibly be the best option for travelers.",
    "Airalo is arguably the most popular eSIM provider.",
    "Somewhat surprisingly, eSIMs cost less than roaming.",
])
def test_detects_hedge_words(hedge):
    text = f"Airalo covers 200+ countries. {hedge}"
    findings = check_text(text)
    assert any(f["rule_id"] == "hedge_words" for f in findings), \
        f"Expected hedge_words finding for: {hedge}"


# ── Repeated openings ──────────────────────────────────────────────────────

def test_detects_repeated_openings():
    text = (
        "The first thing to consider is coverage. "
        "The first thing to check is price. "
        "The first thing to know is that eSIMs are cheap."
    )
    findings = check_text(text)
    assert any(f["rule_id"] == "repeated_openings" for f in findings)


# ── Structure ──────────────────────────────────────────────────────────────

def test_returns_structured_findings():
    text = "In today's fast-paced world, In conclusion, eSIMs are great."
    findings = check_text(text)
    assert isinstance(findings, list)
    for f in findings:
        assert isinstance(f, dict)
        assert "rule_id" in f
        assert "severity" in f
        assert "span" in f
        assert "message" in f
        assert f["severity"] == "warning"


def test_span_tracks_correct_positions():
    text = "In today's fast-paced world, connectivity matters."
    findings = check_text(text)
    intro_findings = [f for f in findings if f["rule_id"] == "generic_intro"]
    assert len(intro_findings) >= 1
    f = intro_findings[0]
    # span should point to the matched text region
    start, end = f["span"]
    assert start >= 0 and end > start
    assert end <= len(text)