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


def test_is_sensitive_catches_medical_with_generic_category():
    # Classifier-gap regression (t_dfcdd95f): medical topics default to the
    # generic "digital-nomad" category and previously sailed through to
    # auto_publish. The title/slug must be scanned too.
    assert is_sensitive("digital-nomad",
                        title="Mental Health Support for Digital Nomads: Therapy, Coverage, and",
                        slug="mental-health-support-digital-nomads") is True
    assert is_sensitive("digital-nomad",
                        title="Preventive Health Abroad: Vaccines, Screening, and the Travel Clinic",
                        slug="preventive-health-abroad-travel-clinic") is True
    assert is_sensitive("digital-nomad",
                        title="Getting Prescriptions and Medication Abroad",
                        slug="medication-and-prescriptions-abroad") is True


def test_is_sensitive_catches_insurance():
    # Insurance was absent from the sensitive vocabulary entirely; the task
    # scope explicitly includes banking/insurance subjects.
    assert is_sensitive("digital-nomad",
                        title="Travel Insurance Declined Claims: The Six Exclusion Categories",
                        slug="travel-insurance-declined-claim-categories") is True
    assert is_sensitive("insurance") is True


def test_is_sensitive_keeps_nonsensitive_topics_clear():
    # Non-sensitive topics must not be quarantined by the broader scan.
    assert is_sensitive("digital-nomad",
                        title="Cost of Living in Bali for Digital Nomads",
                        slug="cost-of-living-in-bali-for-digital-nomads") is False
    assert is_sensitive("digital-nomad",
                        title="Best VPN for Digital Nomads",
                        slug="best-vpn-for-digital-nomads") is False
    assert is_sensitive("digital-nomad",
                        title="Tipping Customs Around the World: A Field Guide",
                        slug="tipping-customs-around-the-world") is False


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
