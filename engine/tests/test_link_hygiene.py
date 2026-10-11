"""Link-hygiene QA for article bodies (Guy, 2026-10-05).

Internal & external links must be proper `[anchor](url)` hyperlinks woven
into natural prose — not bare URLs dropped into the text, not plain URLs
in parens, not hyphenated-slug anchors. This pins `invariants.link_hygiene_issues`
so the corpus cannot regress again (live proof 2026-10-05: 20 raw prose URLs,
9 slug anchors incl. one wrong-domain link, across 6 published articles).

Run:  cd ~/nomadomics-v2 && env -u PYTHONPATH ../.venv/bin/python -m pytest \
          engine/tests/test_link_hygiene.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from invariants import link_hygiene_issues  # noqa: E402


def issues(body: str) -> list[str]:
    return link_hygiene_issues(body)


def test_clean_body_has_no_issues():
    body = (
        "## The Bottom Line\n\n"
        "Compare [Wise vs Revolut vs Payoneer](https://wise.com/) before you "
        "pick, and see our [multi-currency account](/) breakdown.\n\n"
        "- [IRS: FEIE](https://www.irs.gov/feie)\n"
        "- [Gov.uk: statutory residence](https://www.gov.uk/residence)"
    )
    assert issues(body) == []


def test_bare_url_in_prose_is_flagged():
    body = "Tax escheatment? (source: https://www.irs.gov/feie) see below."
    res = issues(body)
    assert any(x.startswith("raw-url") for x in res) or any(
        x.startswith("paren-url") for x in res
    )


def test_slug_anchor_is_flagged():
    body = "See [best-esim-plans-for-digital-nomads](/best-esim-plans-for-digital-nomads)."
    res = issues(body)
    assert any("slug-anchor" in x for x in res)


def test_slug_anchor_to_wrong_domain_is_flagged():
    body = "See [slow-travel-budget-digital-nomad](https://nomadlist.com)."
    res = issues(body)
    assert any("wrong-domain" in x for x in res)


def test_proper_external_links_not_flagged():
    body = "Deals on [Numbeo](https://www.numbeo.com/cost-of-living)."
    assert issues(body) == []