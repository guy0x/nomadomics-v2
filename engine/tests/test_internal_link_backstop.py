#!/usr/bin/env python3
"""Internal-link backstop for the WRITE path.

Covers ~/nomadomics-v2/engine/invariants.py :: ensure_internal_links
(plan 2026-10-04_133958-nomadomics-queue-health.md, follow-on).

Why this exists
---------------
`ensure_body_citations` is the deterministic backstop for citations: the writer
is *asked* to cite inline, and when it doesn't, a `## Sources` section is
appended. There was no equivalent for internal links. The writer prompt never
asks for them and nothing post-processes the body, so every newly published
article shipped with whatever links the model happened to emit — usually none.
Live proof 2026-10-04: `budgeting-apps-for-digital-nomads` published with 0
internal links while corpus coverage sat at 41/42. The 09-23..10-01 cohort was
repaired by a one-off data pass, which fixed history but left the publish path
untouched, so the regression recurred on the very next article.

Contract pinned here
--------------------
  * Counts BOTH link forms: relative `/slug` and absolute
    `https://nomadomics.(com|blog)/slug` (absolute-only counting is the bug
    that made an earlier scan report 8 unlinked articles when there were 9).
  * Idempotent: a body already carrying >= min_links distinct internal links is
    returned byte-for-byte unchanged.
  * Never self-links: `own_slug` is excluded from the corpus.
  * Prefers CONTEXTUAL links (wraps the first in-body mention of the target's
    title/keyword) over a bare "related" list; the list is only a top-up so the
    count still reaches the floor.
  * Idempotent on the top-up too: a second call adds nothing.

Run:  cd ~/nomadomics-v2 && env -u PYTHONPATH ../.venv/bin/python -m pytest \
          engine/tests/test_internal_link_backstop.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from invariants import MIN_INTERNAL_LINKS, ensure_internal_links  # noqa: E402

CORPUS = [
    {"slug": "travel-insurance-exclusions", "title": "Travel Insurance Exclusions"},
    {"slug": "digital-nomad-communities-every-major-hub", "title": "Digital Nomad Communities In Every Major Hub"},
    {"slug": "portable-wifi-vs-esim-vs-local-sim", "title": "Portable Wifi vs eSIM vs Local SIM"},
    {"slug": "slow-travel-budget-digital-nomad", "title": "Slow Travel Budget For Digital Nomads"},
]


def _count_internal(body: str) -> int:
    import re
    hits = set()
    for m in re.finditer(r"\]\(([^)]+)\)", body):
        u = m.group(1).split("#")[0].strip()
        if u.startswith("/"):
            hits.add(u)
        elif u.startswith("http") and re.match(r"https?://(www\.)?nomadomics\.(com|blog)/", u):
            hits.add(u)
    return len(hits)


def test_already_linked_body_unchanged():
    body = ("Intro text.\n\nSee [Exclusions](/travel-insurance-exclusions) and "
            "[Communities](https://nomadomics.com/digital-nomad-communities-every-major-hub).\n")
    out = ensure_internal_links(body, CORPUS, own_slug="some-other-article")
    assert out == body, "a compliant body must be returned byte-for-byte unchanged"


def test_counts_absolute_links_as_internal():
    """The regression detector and the fixer must agree on what counts."""
    body = ("Text [a](https://nomadomics.com/travel-insurance-exclusions) and "
            "[b](https://www.nomadomics.blog/portable-wifi-vs-esim-vs-local-sim).\n")
    assert _count_internal(body) >= MIN_INTERNAL_LINKS
    assert ensure_internal_links(body, CORPUS, own_slug="x") == body


def test_unlinked_body_gets_links():
    body = ("Budgeting apps are everywhere. Compare Travel Insurance Exclusions "
            "before you buy. Digital Nomad Communities In Every Major Hub lists "
            "the usual suspects.\n")
    out = ensure_internal_links(body, CORPUS, own_slug="budgeting-apps-for-digital-nomads")
    assert _count_internal(out) >= MIN_INTERNAL_LINKS, out


def test_prefers_contextual_inline_link():
    body = "Before you book, read Travel Insurance Exclusions carefully.\n"
    out = ensure_internal_links(body, CORPUS, own_slug="new-article")
    # the mention itself should become the anchor, not a bare appended list
    assert "[Travel Insurance Exclusions](/travel-insurance-exclusions)" in out, out


def test_never_self_links():
    corpus = CORPUS + [{"slug": "self-article", "title": "Self Article"}]
    body = "This article is Self Article talking about itself.\n"
    out = ensure_internal_links(body, corpus, own_slug="self-article")
    assert "/self-article" not in out, out


def test_idempotent():
    body = "Travel Insurance Exclusions matter. Digital Nomad Communities In Every Major Hub too.\n"
    once = ensure_internal_links(body, CORPUS, own_slug="new-article")
    twice = ensure_internal_links(once, CORPUS, own_slug="new-article")
    assert once == twice, "second call must add nothing"
    assert _count_internal(once) == _count_internal(twice)


def test_empty_corpus_is_a_noop_not_a_crash():
    body = "No corpus available.\n"
    assert ensure_internal_links(body, [], own_slug="x") == body
