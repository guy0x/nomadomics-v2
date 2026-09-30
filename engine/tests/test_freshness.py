"""Fact-freshness gate tests (kanban t_00bfe56f).

The article confidence score used to never check whether a figure was current:
Portugal D8 and Spain DNV articles scored 89/90 with income thresholds 1-2
years out of date and 0 body citations carrying 2026-linked numbers (ARES
t_1c017073). These tests pin the freshness gate's three required behaviours:

  - figure with dated source          -> clean (AC3 case 1)
  - figure with no dated source       -> flagged (AC3 case 2 / AC2)
  - figure as-of year older than the
    newest re-verification year       -> flagged (AC3 case 3)

and the no-regression rule (AC4): a body whose money figures carry a dated
citation keeps penalty 0, so rework cards land without re-scoring regressions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from freshness import freshness_report  # noqa: E402
from research.research import Fact, ResearchResult  # noqa: E402
from writer.writer import ArticleDraft  # noqa: E402
from seo.analyze import analyze_seo  # noqa: E402


# --- AC3 case 1: figure with a dated source is clean --------------------------

def test_figure_with_dated_source_is_clean():
    body = (
        "# Portugal D8 Visa\n\n"
        "Applicants must prove monthly income of at least \u20ac3,680, which is four "
        "times the minimum wage that rose to \u20ac920 on 1 January 2026 "
        "([Decreto-Lei 139/2025](https://diariodarepublica.pt/dl-139-2025))."
    )
    report = freshness_report(body)
    assert report.penalty == 0
    assert report.issues == []

    # The claim is recorded WITH its as-of date (AC1): the article records the
    # as-of date of the figure it asserts.
    claimed = [c for c in report.claims if c.kind == "currency" and c.figure == "\u20ac3,680"]
    assert claimed and claimed[0].as_of_year == 2026


def test_figure_with_dated_source_in_neighbour_paragraph_is_clean():
    # The figure and its anchor routinely live in separate paragraphs
    # ("That number isn't arbitrary: ... rose on 1 January 2026").
    body = (
        "# Portugal D8 Visa\n\n"
        "Applicants must prove monthly income of at least \u20ac3,680.\n\n"
        "That number is four times the minimum wage, which rose to \u20ac920 on "
        "1 January 2026 ([Decreto-Lei 139/2025](https://diariodarepublica.pt/139-2025))."
    )
    report = freshness_report(body)
    assert report.penalty == 0
    assert report.issues == []


# --- AC3 case 2: figure with no dated source is flagged ------------------------

def test_figure_with_no_dated_source_is_flagged():
    body = (
        "# Portugal D8 Visa\n\n"
        "Applicants must prove monthly income of at least \u20ac3,040."
    )
    report = freshness_report(body)
    assert report.penalty == 40
    kinds = [i.kind for i in report.issues]
    assert kinds == ["no_dated_source"]
    assert report.issues[0].figure == "\u20ac3,040"
    assert report.issues[0].as_of_year is None
    # AC1: even the unsourced figure is recorded, with no as-of year.
    claimed = [c for c in report.claims if c.kind == "currency"]
    assert claimed and all(c.as_of_year is None for c in claimed)


def test_zero_provenance_class_is_the_penalty_class():
    # The quarantine root cause: EVERY money figure arrived without provenance
    # (0 body citations carried 2026-linked numbers). Mixed documents keep
    # their score (AC4) but the undated figures are still warned.
    bad = (
        "Applicants must show income of \u20ac3,040 a month.\n\n"
        "The consular fee is \u20ac173 in total."
    )
    assert freshness_report(bad).penalty == 40

    # A claim one block below a dated paragraph inherits the section's year
    # (neighbour-window rule); an isolated undated claim is warned, not
    # penalised, because the document carries at least one dated figure.
    mixed = (
        "The 2026 fee schedule charges \u20ac110 for the visa.\n\n"
        "## Logistics\n\n"
        "Budget \u20ac200 for courier costs.\n\n"
        "Ship the dossier on time."
    )
    report = freshness_report(mixed)
    assert report.penalty == 0
    assert [i.figure for i in report.issues] == ["\u20ac200"]


# --- AC3 case 3: as-of year older than the newest re-verification --------------

def test_figure_older_than_newest_reverification_is_flagged():
    body = (
        "Applicants must prove monthly income of at least \u20ac3,040, "
        "set by the 2024 decree."
    )
    report = freshness_report(body, newest_year=2026)
    assert [i.kind for i in report.issues] == ["stale"]
    assert report.issues[0].as_of_year == 2024
    # The whole dated set predates the re-verification year -> document penalty.
    assert report.penalty == 40

    # Same figure, re-verification year equal to its as-of year -> clean.
    report = freshness_report(body, newest_year=2024)
    assert report.issues == []
    assert report.penalty == 0


def test_stale_is_opt_in_for_the_scoring_path():
    body = (
        "# Money Transfers\n\n"
        "Banks average a 14.99% fee on a $200 transfer in Q3 2025 "
        "([World Bank](https://worldbank.org/rpw-q3-2025))."
    )
    # Auto-scoring never passes newest_year: the Q3-2025 dataset is not a stale
    # signal against calendar 2026, so no penalty and no stale issue.
    report = freshness_report(body)
    assert report.penalty == 0
    assert report.issues == []
    # A review-time caller who opts in sees the year-granularity signal.
    assert [i.kind for i in freshness_report(body, newest_year=2026).issues] == ["stale"]


# --- scope guards --------------------------------------------------------------

def test_non_rule_money_mentions_are_not_claims():
    # Casual money mentions outside an income/fee/threshold context are not
    # rule-anchored claims: non-YMYL prose is untouched.
    body = (
        "# Best eSIM Plans\n\n"
        "Picture this: you land in Bangkok and roaming just billed you $50. "
        "An eSIM cuts that to $15, so you save on the trip."
    )
    report = freshness_report(body)
    assert report.penalty == 0
    assert report.issues == []
    assert report.claims == []


def test_permit_duration_is_recorded_but_never_penalised():
    # Statute-fixed permit terms are not re-issued annually: an old instrument
    # year (Lei 23/2007 in force for 2026 permits) is not a staleness signal.
    body = (
        "The residence permit runs for two years and is renewable in "
        "three-year periods ([Lei 23/2007](https://diariodarepublica.pt/lei-23-2007))."
    )
    report = freshness_report(body, newest_year=2026)
    assert report.penalty == 0
    assert report.issues == []
    durations = [c for c in report.claims if c.kind == "duration"]
    assert durations and any("years" in c.figure for c in durations)


# --- AC4: dated-citation rework bodies keep their score ------------------------

def test_rework_shaped_body_keeps_score():
    # Mirrors the Spain DNV rework (t_10af1394): threshold carries a dated
    # citation inline; the coverage figure below it is a warning, not a penalty.
    body = (
        "# Spain Digital Nomad Visa: The 2026 Applicant's Checklist\n\n"
        "## Monthly Income Requirement\n"
        "The 2026 bar is 200% of Spain's minimum wage: [Real Decreto 126/2026]"
        "(https://www.boe.es/BOE-A-2026-3815) set the SMI at \u20ac1,221 a month, so "
        "the statutory threshold is \u20ac2,442 a month.\n\n"
        "## Documents\n"
        "Bring your passport and a clean criminal record.\n\n"
        "## Private Health Insurance\n"
        "Coverage must meet the minimum (usually \u20ac30,000 for emergencies)."
    )
    report = freshness_report(body, newest_year=2026)
    assert report.penalty == 0
    undated = [i.figure for i in report.issues if i.kind == "no_dated_source"]
    assert undated == ["\u20ac30,000"]
    assert not [i for i in report.issues if i.kind == "stale"]


# --- integration: the confidence scorer applies the penalty --------------------

def _draft(body):
    d = ArticleDraft(markdown=body, word_count=len(body.split()))
    d.used_facts = [f.claim for f in _research().facts]
    return d


def _research():
    return ResearchResult(
        topic="visa",
        facts=[
            Fact(claim="Applicants must prove monthly income.", source_url="https://example.com/a"),
            Fact(claim="The consular fee is charged at application.", source_url="https://example.com/b"),
            Fact(claim="The permit is renewable.", source_url="https://example.com/c"),
            Fact(claim="Coverage must be valid in-country.", source_url="https://example.com/d"),
        ],
    )


def test_analyze_seo_applies_the_freshness_penalty_to_factual():
    undated = _draft(
        "# Portugal D8 Visa\n\n"
        "Applicants must prove monthly income of at least \u20ac3,040.\n\n"
        "## Fees\nThe consular fee is \u20ac173."
    )
    r1 = analyze_seo(undated, "Portugal D8 visa", research=_research())
    assert r1.freshness_penalty == 40
    assert r1.factual_score == 60  # 100 - 40; factual weight 0.20 -> -8 confidence

    dated = _draft(
        "# Portugal D8 Visa\n\n"
        "Applicants must prove monthly income of at least \u20ac3,680, the 2026 "
        "threshold.\n\n"
        "## Fees\nThe consular fee is \u20ac110 per the 2026 fee table."
    )
    r2 = analyze_seo(dated, "Portugal D8 visa", research=_research())
    assert r2.freshness_penalty == 0
    assert r2.factual_score == 100
    # AC4: dated figures keep the score — the unprovenanced variant is at
    # least 8 confidence points lower (0.20 x 40), and any extra gap comes
    # from the fixtures' differing length, not from freshness.
    assert r2.confidence - r1.confidence >= 8
    assert r1.breakdown["freshness_undated"] > 0
    assert r2.breakdown["freshness_undated"] == 0
