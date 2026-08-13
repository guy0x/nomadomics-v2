"""Tests for the publish policy (confidence gate)."""
import pytest

from policy.publish import Decision, apply_policy, is_sensitive


def test_high_confidence_autopublishes_after_first_n():
    d = apply_policy(88, articles_reviewed=5, first_n_human_review=3)
    assert d.decision == Decision.AUTO_PUBLISH


def test_high_confidence_but_inside_first_n_requires_human():
    d = apply_policy(95, articles_reviewed=1, first_n_human_review=3)
    assert d.decision == Decision.NEEDS_REVIEW


def test_high_confidence_nonsensitive_autopub_with_zero_reviewed_if_n_zero():
    d = apply_policy(90, articles_reviewed=0, first_n_human_review=0)
    assert d.decision == Decision.AUTO_PUBLISH


def test_moderate_confidence_needs_review():
    d = apply_policy(70, articles_reviewed=5)
    assert d.decision == Decision.NEEDS_REVIEW


def test_low_confidence_rejected():
    d = apply_policy(45, articles_reviewed=5)
    assert d.decision == Decision.REJECT


def test_sensitive_topic_always_quarantines_even_high_confidence():
    d = apply_policy(95, sensitive=True, articles_reviewed=99)
    assert d.decision == Decision.QUARANTINE


def test_manual_override_force_review_even_high_confidence():
    d = apply_policy(99, manual_override=True, articles_reviewed=99)
    assert d.decision == Decision.NEEDS_REVIEW


def test_ladder_zero_always_review():
    d = apply_policy(99, ladder_level=0, articles_reviewed=99)
    assert d.decision == Decision.NEEDS_REVIEW


def test_confidence_out_of_range_raises():
    with pytest.raises(ValueError):
        apply_policy(101)
    with pytest.raises(ValueError):
        apply_policy(-1)


def test_is_sensitive_detects_categories():
    assert is_sensitive("taxes") is True
    assert is_sensitive("tax") is True
    assert is_sensitive("visas") is True
    assert is_sensitive("banking") is True
    assert is_sensitive("digital-nomad") is False
    assert is_sensitive("gear") is False
    assert is_sensitive(None) is False


def test_boundary_scores():
    # Exactly at auto-publish threshold, past first-N, non-sensitive
    d = apply_policy(80, articles_reviewed=5)
    assert d.decision == Decision.AUTO_PUBLISH
    # 79 is below threshold -> needs_review
    d2 = apply_policy(79, articles_reviewed=5)
    assert d2.decision == Decision.NEEDS_REVIEW
    # At reject floor
    d3 = apply_policy(60, articles_reviewed=5)
    assert d3.decision == Decision.NEEDS_REVIEW
