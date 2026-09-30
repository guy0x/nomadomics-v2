"""Write-time invariants, citation reality, and the shared publish ledger."""
from __future__ import annotations

from invariants import article_invariant_errors, check_write_invariants, citation_is_real
from publish_ledger import published_slugs, record

# A fixture description that satisfies the meta-shape contract enforced by
# check_write_invariants (120-160c, distinct from the excerpt, terminal ".").
VALID_DESC = (
    "Living costs, visa rules and internet speeds differ in every hub. "
    "This guide compares the practical numbers so you can pick a base "
    "before you book a flight."
)


def _article(**over):
    base = {
        "excerpt": "A real excerpt sentence for the card.",
        "metaTitle": "Title",
        "metaDescription": VALID_DESC,
        "slug": "yearless-slug",
    }
    base.update(over)
    return base


def _two():
    return [{"url": "https://irs.gov/a"}, {"url": "https://irs.gov/b"}]


def test_empty_excerpt_and_year_slug_fail():
    errors = check_write_invariants(_article(excerpt="  "), _two())
    assert any("excerpt" in e for e in errors)
    errors = check_write_invariants(_article(slug="best-vpns-for-2026"), _two())
    assert any("yearless" in e for e in errors)
    errors = check_write_invariants(_article(metaTitle=""), _two())
    assert any("meta" in e for e in errors)
    assert check_write_invariants(_article(), _two()) == []


def test_meta_shapes_are_refused_by_name():
    """t_7197386f AC2: check_write_invariants returns a NAMED error for each of
    the three shapes the old generator could only produce — excerpt-duplicate,
    the migration template tail, and the literal ellipsis cut — plus the
    metaTitle sibling shapes and the length/terminal-punctuation contract."""
    base = _article()

    # excerpt-duplicate
    errors = check_write_invariants({**base, "metaDescription": base["excerpt"]}, _two())
    assert any("duplicates the excerpt" in e for e in errors)

    # migration template tail
    errors = check_write_invariants(
        {**base, "metaDescription": VALID_DESC + " Learn how to save money on travel."},
        _two(),
    )
    assert any("migration template tail" in e for e in errors)

    # ellipsis cut — three-dot AND unicode
    errors = check_write_invariants({**base, "metaDescription": VALID_DESC + "..."}, _two())
    assert any("ellipsis cut" in e for e in errors)
    errors = check_write_invariants({**base, "metaDescription": VALID_DESC + "\u2026"}, _two())
    assert any("ellipsis cut" in e for e in errors)

    # metaTitle sibling shapes
    errors = check_write_invariants({**base, "metaTitle": "Budget Travel Guide..."}, _two())
    assert any("metaTitle ends in an ellipsis cut" in e for e in errors)
    errors = check_write_invariants({**base, "metaTitle": "x" * 61}, _two())
    assert any("SERP budget" in e for e in errors)

    # length + terminal punctuation contract
    errors = check_write_invariants({**base, "metaDescription": "Too short."}, _two())
    assert any("120-160" in e for e in errors)
    mid = VALID_DESC.rsplit(".", 1)[0]  # drop the final full stop
    errors = check_write_invariants({**base, "metaDescription": mid}, _two())
    assert any("terminal punctuation" in e for e in errors)

    # the clean fixture is untouched by all the above rules
    assert check_write_invariants(base, _two()) == []


def test_unreachable_or_mismatched_citation_is_not_real():
    def fetch(url):
        if "missing" in url:
            raise OSError("unreachable")
        if "moved" in url:
            return 200, "a real page", "https://other.example/landed"
        return 200, "a real page", url

    assert citation_is_real("https://irs.gov/missing", fetch) is False
    assert citation_is_real("https://irs.gov/moved", fetch) is False
    assert citation_is_real("https://irs.gov/real", fetch) is True
    article = {
        "excerpt": "Excerpt",
        "metaTitle": "T",
        "metaDescription": "D",
        "slug": "clean-slug",
        "bodyMarkdown": "See https://irs.gov/missing and https://irs.gov/real",
    }
    assert article_invariant_errors(article, fetch=fetch)


def test_both_lanes_share_one_ledger(tmp_path):
    path = tmp_path / "publish-ledger.jsonl"
    record({"event": "published", "slug": "from-draft", "ts": "2026-09-23T00:00:00+00:00"}, path)
    other = tmp_path / "publish-pipeline.jsonl"
    other.write_text('{"event":"published","slug":"from-daily","ts":"2026-09-23T01:00:00+00:00"}\n')
    slugs = published_slugs([path, other])
    assert slugs == {"from-draft", "from-daily"}
