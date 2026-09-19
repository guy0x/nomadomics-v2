"""Meta-field trimming: fit the cap, never cut with an ellipsis.

The polish step hands back metaTitle/metaDescription over the Strapi schema caps.
The old hard cut (`text[:57] + "..."`) both burned three characters on punctuation
and published snippets that read as broken — measured live on 2026-09-19, e.g.
"Travel Hacking for Beginners: 10 Simple Ways to Fly Cheap...".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from publish import _fit  # noqa: E402


def test_short_text_is_untouched():
    assert _fit("Best ATMs in Spain", 60) == "Best ATMs in Spain"
    assert _fit("", 60) == ""


def test_text_exactly_at_the_cap_is_untouched():
    text = "x" * 60
    assert _fit(text, 60) == text


def test_overlong_text_is_fitted_without_an_ellipsis():
    text = "Travel Hacking for Beginners: 10 Simple Ways to Fly Cheap and Travel Smart"
    out = _fit(text, 60)
    assert len(out) <= 60
    assert not out.endswith("...")
    assert "…" not in out
    assert out == text[: len(out)]        # a prefix cut, nothing reordered
    assert out.split() == text.split()[: len(out.split())]   # whole words only


def test_trailing_separators_are_not_left_dangling():
    out = _fit("Digital Nomad Taxes 2026: Residency Rules & What You Owe, and more", 50)
    assert len(out) <= 50
    assert not out.endswith((",", ";", ":", "-", " "))


def test_single_long_word_falls_back_to_a_hard_cut():
    assert _fit("x" * 80, 60) == "x" * 60
