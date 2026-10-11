"""Publish-lane internal-link backstop (kanban t_49aba8a9, 2026-10-11).

Live proof 2026-10-11: `how-to-live-in-thailand-as-a-digital-nomad` shipped from
the 13:00 publisher with three links shaped `[slug](slug)` — bare-slug hrefs,
no leading slash. Browsers resolve them under the article path (broken), and
the corpus monitor counts zero, so coverage read 48/49. Two gates were missing:

  * the draft lane has run `ensure_internal_links` since 2026-10-04, but the
    13:00 publisher did not — the polish pass was the only link source;
  * `article_invariant_errors` (incl. link hygiene) runs at candidate selection
    on the PRE-polish body; nothing checked the FINAL body that is actually
    published.

publish.py now runs the backstop + `link_hygiene_issues` on the final body and
refuses the publish when hygiene fails (event `publish_refused_link_hygiene`).
These tests pin the contract of that pair on exactly the shapes seen live.

Run:  cd ~/nomadomics-v2 && env -u PYTHONPATH ../.venv/bin/python -m pytest \
          engine/tests/test_publish_link_backstop.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from invariants import ensure_internal_links, link_hygiene_issues  # noqa: E402

CORPUS = [
    {"slug": "budgeting-apps-for-digital-nomads", "title": "Best Budgeting Apps For Digital Nomads"},
    {"slug": "cost-of-living-mexico-city", "title": "Cost Of Living Mexico City"},
    {"slug": "cost-of-living-ho-chi-minh-city-nomads", "title": "Cost Of Living In Ho Chi Minh City"},
]

# The shape the polish model shipped on 2026-10-11: prose links whose href is a
# bare slug (no leading slash) and whose anchor is the raw slug itself.
THAILAND_BROKEN = (
    "Chiang Mai keeps costs low. Track expenses with "
    "[budgeting-apps-for-digital-nomads](budgeting-apps-for-digital-nomads) "
    "before you compare them to "
    "[cost-of-living-mexico-city](cost-of-living-mexico-city).\n"
)


def test_backstop_adds_links_when_polish_drops_them():
    """A polish output with zero countable links gets >= 2 proper /slug links."""
    fixed = ensure_internal_links("A body with no links at all.", CORPUS, own_slug="x")
    assert len([h for h in fixed.split("](") if h.startswith("/")]) >= 2 or "/cost-of-living" in fixed
    # the backstop's own output must be hygiene-clean — it may not fail the gate
    # it feeds
    assert link_hygiene_issues(fixed) == []


def test_bare_slug_polish_output_counts_as_zero_and_is_refused():
    """`[slug](slug)` counts as ZERO targets, and the backstop cannot rescue it.

    The backstop tops the body up to the floor with proper links, but the
    malformed slug-anchor links remain — `link_hygiene_issues` must flag them so
    the publisher refuses instead of shipping the 2026-10-11 defect again.
    """
    from invariants import body_internal_link_targets

    assert len(body_internal_link_targets(THAILAND_BROKEN)) == 0
    topped_up = ensure_internal_links(THAILAND_BROKEN, CORPUS, own_slug="own")
    issues = link_hygiene_issues(topped_up)
    assert issues, "bare-slug hrefs must trip the hygiene gate"
    assert any("slug-anchor" in i for i in issues)


def test_proper_polish_output_passes_untouched():
    """A compliant polish output is idempotent — no links added, no refusal."""
    good = (
        "Track spending with the [best budgeting apps]"
        "(/budgeting-apps-for-digital-nomads), then compare life in "
        "[Mexico City](/cost-of-living-mexico-city).\n"
    )
    fixed = ensure_internal_links(good, CORPUS, own_slug="own")
    assert fixed == good
    assert link_hygiene_issues(fixed) == []


def test_polish_prompt_forbids_bare_slug_hrefs():
    """The prompt that taught the model the broken shape now forbids it."""
    import publish

    assert "leading slash" in publish.POLISH_SYSTEM
    assert "never a raw slug" in publish.POLISH_SYSTEM
