"""Regression tests for the excerpt gap that tripped the autopost content invariant.

2026-09-22: `best-virtual-mailbox-nomads` published with `excerpt=""`, so the
article card rendered with no description, the hero subtitle was absent and the
RSS <description> was empty. The trial monitor
(`~/.hermes/scripts/nomadomics_content_invariants.py`, rule at `check_article`)
failed cron 3a6eafe8906b with "no excerpt (card renders with no description)".

Cause (fixed in 759f570): `seo/analyze.py:_first_sentence()` broke out of its
accumulation loop before appending anything whenever the article's FIRST sentence
alone exceeded the 155c budget, returning "". The house-voice opener style runs
180c+, so the defect fired on every house-voice article; the older fixture in
`test_seo.py` opens with a 40c sentence, so the suite stayed green while the bug
was live in production.

These tests pin both halves of the contract:

  * the engine always returns a card-shaped excerpt for prose — over-budget
    openers are cut on a word boundary and closed with U+2026, while a genuinely
    prose-free body still returns "" so a real content gap stays visible;
  * the monitor's OWN rules accept the result. The monitor is imported by path
    and its `check_article` is called for real (network + artifacts stubbed), so
    the engine and the invariant cannot drift apart silently. Nothing here
    re-implements the rules.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.research import Fact, ResearchResult  # noqa: E402
from seo.analyze import _first_sentence, analyze_seo  # noqa: E402
from writer.writer import ArticleDraft  # noqa: E402

SLUG = "best-virtual-mailbox-nomads"
MONITOR_PATH = Path(os.environ.get(
    "NOMADOMICS_INVARIANT_MONITOR",
    Path.home() / ".hermes" / "scripts" / "nomadomics_content_invariants.py",
))

# The monitor's excerpt rule, asserted below against the real `check_article`:
# non-empty, <= 220c, closing on sentence punctuation.
EXCERPT_MAX = 220
EXCERPT_ENDINGS = (".", "!", "?", "\u2026")

# The exact shape that broke production: a house-voice scene-setter whose first
# sentence alone is 226c, i.e. past the 155c budget `_first_sentence` accumulates
# within. `test_the_fixture_actually_crosses_the_budget_boundary` keeps it honest.
HOUSE_VOICE_OPENER = (
    "Picture this: it is a Tuesday morning in Lisbon, the coworking space is still "
    "empty, and you have just opened a letter from the tax office that says you owe "
    "money in two countries at once, which is exactly the moment most digital nomads "
    "start looking for help."
)

BODY_MARKDOWN = "# Best eSIM Travel Plans for Budget Nomads in 2026\n\nSee [this guide](/best-esim-plans) for details.\n"

LIVE_HTML = (
    "<html><head><title>Best eSIM Travel Plans for Budget Nomads</title>"
    f'<link rel="canonical" href="https://nomadomics-v2.vercel.app/{SLUG}">'
    "</head><body><h1>Best eSIM Travel Plans for Budget Nomads</h1>"
    '<script type="application/ld+json">{"@type":"BlogPosting"}</script></body></html>'
)


def research_result():
    return ResearchResult(
        topic="eSIM",
        facts=[Fact(claim="An eSIM avoids roaming fees.", source_url="https://example.com/a")],
    )


def draft_for(body: str) -> ArticleDraft:
    d = ArticleDraft(markdown=body, word_count=len(body.split()))
    d.used_facts = [f.claim for f in research_result().facts]
    return d


def article_body(opener: str) -> str:
    """A minimal article whose FIRST prose sentence is `opener`."""
    return (
        "# Best eSIM Travel Plans for Budget Nomads in 2026\n\n"
        f"{opener}\n\n"
        "An eSIM fixes the cost side of that problem.\n\n"
        "## Airalo\nAiralo covers 200+ countries.\n\n"
        "## FAQ\n### Is an eSIM cheaper than roaming?\nYes.\n"
    )


def report_for(body: str):
    return analyze_seo(
        draft_for(body), "esim travel",
        secondary_keywords=["digital nomads"], research=research_result(),
    )


PROSE_CASES = [
    ("house-voice opener (the production failure)", HOUSE_VOICE_OPENER),
    ("two short sentences inside the budget", "You land in Tokyo. The roaming bill arrives the next morning."),
    ("single sentence one char over the budget", "x" * 155 + "."),
    ("300c with no space to cut on", "x" * 300),
    ("h1 plus an over-budget opener", "# Best eSIM Plans for Nomads\n\n" + HOUSE_VOICE_OPENER),
    ("em-dash scene setter", "You land in Bangkok \u2014 and the roaming bill lands with you, all of it."),
]

PROSE_FREE_CASES = [
    ("empty body", ""),
    ("whitespace only", "   \n\n  "),
    ("headings only, no prose", "# Title\n\n## Section\n\n### Sub\n"),
]


@pytest.fixture(scope="module")
def monitor():
    """The real invariant monitor, loaded by path (no network, no state writes)."""
    if not MONITOR_PATH.exists():
        pytest.skip(f"invariant monitor not found at {MONITOR_PATH} (set NOMADOMICS_INVARIANT_MONITOR)")
    spec = importlib.util.spec_from_file_location("nomadomics_content_invariants", MONITOR_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {MONITOR_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # module level only; the script's work is behind __main__
    return mod


@pytest.fixture
def stored_record(monitor, tmp_path, monkeypatch):
    """Build a Strapi-shaped record and take `check_article` offline.

    `check_article` reads the card/og files off disk and probes the live site, so
    both are stubbed: the artifact check gets real files in a tmp dir and every
    HTTP call returns a page that satisfies the structural rules. That leaves the
    metadata rules (excerpt / metaTitle / metaDescription) as the only verdict.
    """
    for kind in ("cards", "og"):
        d = tmp_path / kind
        d.mkdir()
        (d / f"{SLUG}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 6000)
    monkeypatch.setattr(monitor, "PUBLIC", tmp_path)
    monkeypatch.setattr(monitor, "http", lambda url, timeout=30: (200, LIVE_HTML))

    def build(*, excerpt: str, meta_description: str):
        return {
            "slug": SLUG,
            "title": "Best eSIM Travel Plans for Budget Nomads in 2026",
            "excerpt": excerpt,
            "metaTitle": "Best eSIM Travel Plans for Budget Nomads",
            "metaDescription": meta_description,
            "focusKeyword": f"esim travel {monitor.THIS_YEAR}",
            "publishedAt": "2026-09-22T05:52:20.795Z",
            "updatedAt": "2026-09-22T05:52:20.795Z",
            "bodyMarkdown": BODY_MARKDOWN,
        }

    return build


def test_the_fixture_actually_crosses_the_budget_boundary():
    """The opener must exceed 155c, or these tests stop covering the real bug."""
    assert len(HOUSE_VOICE_OPENER) > 155


@pytest.mark.parametrize("case,body", PROSE_CASES, ids=[c for c, _ in PROSE_CASES])
def test_prose_always_yields_a_card_shaped_excerpt(case, body):
    excerpt = _first_sentence(body)
    assert excerpt, f"{case}: empty excerpt is the production failure"
    assert len(excerpt) <= EXCERPT_MAX, f"{case}: {len(excerpt)}c is too long for a card"
    assert excerpt.endswith(EXCERPT_ENDINGS), f"{case}: truncated mid-sentence: {excerpt[-40:]!r}"


@pytest.mark.parametrize("case,body", PROSE_FREE_CASES, ids=[c for c, _ in PROSE_FREE_CASES])
def test_prose_free_bodies_still_return_nothing(case, body):
    """An empty article must stay empty — the fix must not invent copy."""
    assert _first_sentence(body) == "", f"{case}: nothing to quote"


def test_text_inside_the_budget_is_left_alone():
    body = "You land in Tokyo. The roaming bill arrives the next morning."
    assert _first_sentence(body) == body


def test_the_heading_is_not_counted_against_the_excerpt_budget():
    assert _first_sentence("# Best eSIM Plans for Nomads\n\nShort opener here.") == "Short opener here."


def test_over_budget_opener_is_cut_on_a_word_boundary():
    excerpt = _first_sentence(HOUSE_VOICE_OPENER)
    stem = excerpt[:-1].rstrip(" ,;:")
    assert excerpt.endswith("\u2026")
    assert not excerpt[:-1].endswith(" ")          # no dangling space before the ellipsis
    assert HOUSE_VOICE_OPENER.startswith(stem)     # a pure prefix cut, nothing reordered
    assert stem.split() == HOUSE_VOICE_OPENER.split()[: len(stem.split())]   # whole words only


# --------------------------------------------------------------------- invariant
def test_monitor_accepts_the_rebuilt_record_for_the_previously_failing_article(monitor, stored_record):
    """End-to-end: the engine's output for the broken article now passes the monitor."""
    report = report_for(article_body(HOUSE_VOICE_OPENER))
    record = stored_record(excerpt=report.excerpt, meta_description=report.meta_description)

    assert record["excerpt"], "the invariant rejects an empty excerpt"
    assert len(record["excerpt"]) <= EXCERPT_MAX
    assert record["excerpt"].endswith(EXCERPT_ENDINGS)
    assert not record["metaDescription"].endswith(("\u2026", "..."))
    assert monitor.check_article(record) == []


@pytest.mark.parametrize("case,body", PROSE_CASES, ids=[c for c, _ in PROSE_CASES])
def test_monitor_finds_no_excerpt_issue_for_any_prose_opener(monitor, stored_record, case, body):
    """The monitor's own excerpt rule, exercised for every opener shape."""
    report = report_for(article_body(body))
    record = stored_record(excerpt=report.excerpt, meta_description=report.meta_description)
    excerpt_issues = [i for i in monitor.check_article(record) if "excerpt" in i]
    assert excerpt_issues == [], f"{case}: {excerpt_issues}"


def test_monitor_still_flags_a_genuinely_empty_excerpt(monitor, stored_record):
    """Negative control: the invariant must keep biting when there is nothing to quote."""
    report = report_for("# Title\n\n## Section\n\n### Sub\n")
    assert report.excerpt == ""
    record = stored_record(excerpt=report.excerpt, meta_description=report.meta_description)
    issues = monitor.check_article(record)
    assert [i for i in issues if "excerpt" in i], f"empty excerpt went unflagged: {issues}"
