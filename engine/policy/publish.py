"""Publish policy — the confidence gate that decides an article's fate.

This is the core of "minimal human review." Given a confidence score (0-100)
and the engine's trust-ladder level, it returns an execution decision.

Trust ladder (defaults, configurable in Config):
  L0  manual override         -> always needs_review (Guy signs off every draft)
  L1  auto-publish >=80, after first-N human reviews      [MVP launch default]
      60-79 -> needs_review, <60 -> reject
  Sensitive topics (tax/legal/medical) are ALWAYS quarantined to human review,
  regardless of score — per SOUL §8 trust (never auto-publish those).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

SENSITIVE_TOPICS = {"taxes", "legal", "medical", "visas", "banking"}


class Decision(str, Enum):
    AUTO_PUBLISH = "auto_publish"
    NEEDS_REVIEW = "needs_review"
    REJECT = "reject"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    confidence: int
    reason: str
    reviewed_by_human: bool = False


def apply_policy(
    confidence: int,
    *,
    auto_publish_threshold: int = 80,
    needs_review_min: int = 60,
    reject_below: int = 60,
    first_n_human_review: int = 3,
    articles_reviewed: int = 0,
    ladder_level: int = 1,
    sensitive: bool = False,
    manual_override: bool = False,
) -> PolicyDecision:
    """Decide an article's fate from confidence + ladder + topic sensitivity.

    - manual_override, or ladder 0, or sensitive topic -> needs_review/quarantine
    - ladder >=1 and confidence >= auto_publish_threshold and past first-N and
      not sensitive and not manual -> AUTO_PUBLISH
    - confidence in [needs_review_min, auto_publish_threshold) -> needs_review
    - confidence < reject_below -> reject
    """
    if confidence < 0 or confidence > 100:
        raise ValueError(f"confidence must be 0-100, got {confidence}")

    # Hard gates that always require a human.
    if manual_override or ladder_level <= 0:
        return PolicyDecision(Decision.NEEDS_REVIEW, confidence, "manual/ladder-0 override")
    if sensitive:
        return PolicyDecision(
            Decision.QUARANTINE, confidence, "sensitive topic — always human review"
        )

    # First-N calibration: require human sign-off until N articles are reviewed.
    if articles_reviewed < first_n_human_review:
        return PolicyDecision(
            Decision.NEEDS_REVIEW,
            confidence,
            f"first-{first_n_human_review} calibration (human sign-off)",
        )

    if confidence >= auto_publish_threshold:
        return PolicyDecision(Decision.AUTO_PUBLISH, confidence, "confidence>=threshold")
    if confidence >= needs_review_min:
        return PolicyDecision(Decision.NEEDS_REVIEW, confidence, "moderate confidence")
    return PolicyDecision(Decision.REJECT, confidence, "confidence below reject floor")


def is_sensitive(category: str | None) -> bool:
    if not category:
        return False
    cat = category.strip().lower().replace("-", "_")
    return cat in SENSITIVE_TOPICS or any(s in cat for s in ("tax", "legal", "medic", "visa", "bank"))