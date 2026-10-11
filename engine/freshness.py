"""Fact-freshness gate for the confidence heuristic (card t_00bfe56f).

Root cause (ARES t_1c017073, 2026-09-26): the article confidence score is a
weighted fusion of research/SEO/voice/factual-structure heuristics and never
checked whether a figure is still current. Portugal D8 and Spain DNV articles
scored 89/90 while asserting income thresholds 1-2 years out of date, with
0 body citations carrying 2026-linked numbers. The write gate
(`invariants.py::article_invariant_errors`) only checks excerpt/meta/slug/
citations.

This module is a named, deterministic, network-free freshness check that runs
next to the scoring/write path. It records the as-of date of every figure the
article asserts (AC1) and reports two failure classes (AC2):

  - no_dated_source : a rule-anchored money figure has no dated source in its
    citation context -- the number arrived without provenance (the exact
    failure mode observed: 0 body citations carried 2026-linked numbers).
  - stale           : the figure's as-of year predates the newest
    re-verification year supplied by the caller (newest_year, AC3).

Design rules so AC4 holds (articles whose figures carry a dated citation keep
their score -- no re-scoring regression):

  * Claims are rule-anchored money figures (currency amounts) inside a
    paragraph that reads as an income/fee/threshold/coverage context, plus
    permit durations recorded for completeness. Casual money mentions and bare
    percentages are not claims, so non-YMYL prose is untouched.
  * A claim's as-of year is the latest 20xx found in its paragraph, its
    inline-citation link text, or an immediately adjacent paragraph -- a
    figure and its anchor ("...which is 4x the minimum wage that rose on
    1 January 2026 ([DL 139/2025])") routinely sit in neighbouring
    paragraphs, and a table's "2026 figures:" caption sits right below it.
  * The score penalty is document-level and fires only for the zero-provenance
    class: the body has rule-anchored money claims and NONE of them carries a
    dated source. Any article with at least one dated figure keeps its score;
    undated figures still surface as per-figure warnings.
  * Duration claims are recorded but never penalised: statute-fixed permit
    terms are not re-issued annually, so an old instrument year (Lei 23/2007)
    is not a staleness signal for them.
  * newest_year is opt-in. The auto-scoring path does not pass it, so it is
    immune to the "Q3 2025 dataset vs calendar 2026" class of false stale
    flags; review-time callers (re-validation, release lanes) pass it
    explicitly.

Scope: this module only reads text; it never publishes, never opens a network
connection, and never reads secrets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from invariants import body_citation_urls

_YEAR = re.compile(r"20\d{2}")
_RULE_ANCHORS = (
    "threshold", "income", "salary", "wage", "smi", "rmmg", "monthly",
    "per month", "a month", "/month", "annual", "per year", "a year",
    "/year", "fee", "fees", "cost", "costs", "pricing", "price", "rates",
    "charge", "charges", "permit", "visa", "renew", "coverage", "premium",
    "deposit", "minimum", "requirement", "tax", "fine", "penalty", "deductible",
)
_DURATION_ANCHORS = ("permit", "visa", "renew", "stay", "valid for", "validity")
_DURATION = re.compile(
    r"(\d[\d,]*)\s*(?:-|\u2013|\u2014)?\s*years?\b"
    r"|\b(\d[\d,]*)\s*months?\b"
    r"|\b(?:one|two|three|four|five)\s*-?\s*years?\b",
    re.I,
)

_NUM = r"\d(?:\d|,(?=\d))*(?:\.\d+)?"
_CURRENCY = re.compile(
    rf"(?:[€$£]\s?{_NUM}(?:[+\-–—]?\s*[€$£]?\s?{_NUM})?)"
    rf"|\b(?:EUR|USD|GBP|CHF|AUD|CAD|NZD)\s?{_NUM}"
    rf"|\b{_NUM}\s?(?:EUR|USD|GBP|CHF|euros?|dollars?|pounds?)\b",
    re.I,
)


@dataclass
class NumericClaim:
    """One figure the article asserts, with the as-of date it carries.

    kind is "currency" (a money figure, the penalisable class) or "duration"
    (a permit/stay term, recorded for completeness only).
    """

    kind: str
    figure: str
    as_of_year: int | None
    paragraph: str
    citations: list[str] = field(default_factory=list)


@dataclass
class FreshnessIssue:
    """A freshness warning for one figure.

    kind is "no_dated_source" (figure has no dated source in its citation
    context) or "stale" (figure's as-of year < newest_year).
    """

    kind: str
    figure: str
    as_of_year: int | None
    paragraph: str


@dataclass
class FreshnessReport:
    """Full freshness record for one body: claims + warnings + score penalty."""

    claims: list[NumericClaim] = field(default_factory=list)
    issues: list[FreshnessIssue] = field(default_factory=list)
    penalty: int = 0


def _blocks(body: str) -> list[str]:
    """Split markdown body into blocks (blank-line separated)."""
    return [b.strip() for b in (body or "").split("\n\n") if b.strip()]


def _block_year(text: str) -> int | None:
    """Latest 20xx in a raw markdown block (text, link text and URLs)."""
    years = [int(y) for y in _YEAR.findall(text)]
    return max(years) if years else None


def _is_rule_anchored(block: str) -> bool:
    low = block.lower()
    return any(a in low for a in _RULE_ANCHORS)


def _is_duration_anchored(block: str) -> bool:
    low = block.lower()
    return any(a in low for a in _DURATION_ANCHORS)


def _window_years(blocks: list[str], idx: int) -> int | None:
    """Latest year within the claim block and its immediate neighbours.

    A figure's dated anchor routinely lives in the neighbouring paragraph
    ("That number isn't arbitrary: ... rose on 1 January 2026 ([DL 139/2025])")
    or the caption directly under a comparison table ("2026 figures: ..."), so
    the window is the claim block plus one block on each side. A claim two
    blocks away from any year-bearing paragraph has no dated source.
    """
    lo, hi = max(0, idx - 1), min(len(blocks), idx + 2)
    return _block_year(" ".join(blocks[lo:hi]))


def _extract_claims(body: str) -> list[NumericClaim]:
    """Rule-anchored currency figures + permit durations, with as-of years."""
    blocks = _blocks(body)
    claims: list[NumericClaim] = []
    for i, block in enumerate(blocks):
        cites = body_citation_urls(block)
        as_of = _window_years(blocks, i)
        for match in _CURRENCY.finditer(block):
            if not _is_rule_anchored(block):
                continue
            claims.append(
                NumericClaim(
                    kind="currency",
                    figure=match.group(0).strip(),
                    as_of_year=as_of,
                    paragraph=block[:220],
                    citations=cites,
                )
            )
        if _is_duration_anchored(block):
            m = _DURATION.search(block)
            if m:
                claims.append(
                    NumericClaim(
                        kind="duration",
                        figure=m.group(0).strip(),
                        as_of_year=as_of,
                        paragraph=block[:220],
                        citations=cites,
                    )
                )
    return claims


def freshness_report(body: str, newest_year: int | None = None) -> FreshnessReport:
    """Record every rule-anchored figure and its as-of date; report issues.

    newest_year is the newest re-verification year (AC3): a currency figure
    whose as-of year is older than it is flagged "stale". Omitted (or None)
    on the auto-scoring path so stale-checking is opt-in.
    """
    claims = _extract_claims(body)
    currency = [c for c in claims if c.kind == "currency"]
    issues: list[FreshnessIssue] = []
    for c in currency:
        if c.as_of_year is None:
            issues.append(
                FreshnessIssue("no_dated_source", c.figure, None, c.paragraph)
            )
        elif newest_year is not None and c.as_of_year < newest_year:
            issues.append(
                FreshnessIssue("stale", c.figure, c.as_of_year, c.paragraph)
            )

    penalty = 0
    if currency:
        dated = [c for c in currency if c.as_of_year is not None]
        if not dated:
            # Zero-provenance class: every money figure arrived without a
            # dated source -- the quarantine-lane root cause. Drop the
            # factual component (weight 0.20) by 40 -> ~8 confidence points.
            penalty = 40
        elif newest_year is not None and all(
            c.as_of_year is not None and c.as_of_year < newest_year
            for c in dated
        ):
            # Every dated money figure predates the re-verification year.
            penalty = 40
    return FreshnessReport(claims=claims, issues=issues, penalty=penalty)
