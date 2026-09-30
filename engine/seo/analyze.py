"""Deterministic SEO analysis + meta generation + confidence scoring.

Per the model rule (2026-08-11) this stage uses NO LLM — it is a pure heuristic,
so it costs nothing and is fully testable. It produces:
  - seo_score (0-100): keyword coverage, structure, FAQ, meta length
  - confidence (0-100): weighted fusion of research validity / SEO / voice / facts
  - meta_title / meta_description / excerpt suggestions
  - a list of fixes for rejected (<threshold) articles
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from research.research import ResearchResult
from writer.writer import ArticleDraft
from freshness import freshness_report

# Confidence weights (plan §7): research 30 / SEO 25 / voice 25 / factual 20
RESEARCH_W = 0.30
SEO_W = 0.25
VOICE_W = 0.25
FACTUAL_W = 0.20


@dataclass
class SEOReport:
    seo_score: int
    confidence: int
    meta_title: str
    meta_description: str
    excerpt: str
    fixes: list[str] = field(default_factory=list)
    voice_score: int = 0
    factual_score: int = 0
    research_score: int = 0
    structure_score: int = 0
    breakdown: dict = field(default_factory=dict)
    freshness_issues: list = field(default_factory=list)
    freshness_penalty: int = 0


def _count_keyword(text: str, keyword: str) -> int:
    if not keyword:
        return 0
    return len(re.findall(re.escape(keyword.lower()), text.lower()))


def _structure_score(md: str) -> int:
    """Structural richness 0-100: comparison tables, bullet blocks, H3 density,
    and Pros/Cons sections. Rewards the structure contract (writer/editor prompt),
    penalizing walls of prose."""
    lines = md.splitlines()
    tables = 0
    bullet_blocks = 0
    n_h3 = 0
    has_pros = has_cons = False
    in_bullet_block = False

    for line in lines:
        s = line.strip()
        # Markdown table separator row (| --- | --- |) — one per table.
        if s.startswith("|") and "---" in s and re.match(r"^\|[\s:|-]+\|$", s):
            tables += 1
        # Consecutive bullet lines count as one block.
        if re.match(r"^[-*•]\s+\S", s):
            if not in_bullet_block:
                bullet_blocks += 1
                in_bullet_block = True
        else:
            in_bullet_block = False
        if s.startswith("### "):
            n_h3 += 1
        low = s.lower().rstrip(":")
        if low in ("### pros", "pros", "**pros**"):
            has_pros = True
        if low in ("### cons", "cons", "**cons**"):
            has_cons = True

    score = 0
    if tables >= 1:
        score += 30
    if bullet_blocks >= 4:
        score += 30
    elif bullet_blocks >= 2:
        score += 20
    elif bullet_blocks >= 1:
        score += 10
    if n_h3 >= 4:
        score += 15
    elif n_h3 >= 1:
        score += 8
    if has_pros and has_cons:
        score += 25
    elif has_pros or has_cons:
        score += 12
    return min(100, score)


def _h1s(md: str) -> list[str]:
    return [l.lstrip("#").strip() for l in md.splitlines() if l.startswith("# ") or l.startswith("## ")]


def analyze_seo(
    draft: ArticleDraft,
    primary_keyword: str,
    secondary_keywords: Optional[list[str]] = None,
    research: Optional[ResearchResult] = None,
    newest_year: Optional[int] = None,
) -> SEOReport:
    prim = (primary_keyword or "").strip()
    secs = [s for s in (secondary_keywords or []) if s.strip()]
    body = draft.markdown
    points = 0
    reasons: list[str] = []

    def add(p, why):
        nonlocal points
        points += p
        reasons.append(f"{why} (+{p})")

    # Title / H1 contains focus keyword
    title_line = next((l for l in body.splitlines() if l.startswith("# ")), "")
    has_h1_kw = prim and prim.lower() in title_line.lower()
    if has_h1_kw:
        add(15, "H1 contains focus keyword")

    # H2 heading coverage: at least 4 H2 sections
    h2s = [l for l in body.splitlines() if l.startswith("## ")]
    if len(h2s) >= 4:
        add(15, "4+ H2 sections")
    elif h2s:
        add(8, f"{len(h2s)} H2 sections (want 4+)")

    # Secondary keyword in H2s
    h2_text = " ".join(h2s).lower()
    sec_hit = sum(1 for s in secs if s.lower() in h2_text)
    if sec_hit >= 2:
        add(15, "2+ secondary keywords in H2s")
    elif sec_hit == 1:
        add(8, "1 secondary keyword in H2s")

    # FAQ present with >=3 questions
    faqs = [l for l in body.splitlines() if l.startswith("### ") and l.strip().endswith("?")]
    if len(faqs) >= 3:
        add(15, "3+ FAQ questions")
    elif faqs:
        add(8, f"{len(faqs)} FAQ questions (want 3+)")

    # Keyword density in body (primary): aim 0.5-1.5%
    words = len(body.split())
    kw_count = _count_keyword(body, prim) if prim else 0
    density = 0.0
    if words > 0:
        density = kw_count / words
        if 0.004 <= density <= 0.02:
            add(15, "healthy primary-keyword density")
        elif density > 0.02:
            add(5, "keyword density high (>2%)")
        else:
            add(2, f"low keyword density ({density:.1%})")

    # Word count
    wc = draft.word_count
    if 1200 <= wc <= 2400:
        add(10, "target word count range")
    elif wc >= 700:
        add(5, "adequate length")
    else:
        add(0, f"short ({wc} words)")

    # Excerpt / meta length heuristics (use first sentence-derived values)
    first_sentence = _first_sentence(body)
    meta_title = _make_meta_title(prim, title_line)
    meta_desc = _make_meta_desc(body, prim)
    # 47c = the 60c SERP budget minus the 13c " · Nomadomics" brand suffix, so a
    # title in this band is served WITH the brand (t_7197386f).
    if 40 <= len(meta_title) <= META_TITLE_VALUE_MAX:
        add(10, "meta title fits the 47c branded SERP budget")
    if META_DESC_MIN <= len(meta_desc) <= META_DESC_MAX:
        add(10, "meta description 120-160 chars")

    # Structure bonus: tables/bullets/H3/pros-cons raise the on-page SEO score.
    structure = _structure_score(body)
    if structure >= 40:
        add(15, f"rich structure (tables/bullets/pros-cons) +{structure//4}")
    elif structure >= 15:
        add(8, f"some structure +{structure//4}")
    elif structure > 0:
        add(4, f"minimal structure +{structure//4}")

    seo_score = min(100, points)

    # Voice heuristic (crude: detect voice markers from exemplar)
    voice_score = _voice_score(body)
    # Factual grounding
    factual_score = _factual_score(draft, research)
    # Fact-freshness gate (t_00bfe56f): a body whose money figures carry no
    # dated source in their citation context loses factual confidence, so a
    # stale YMYL number is visible before the article reaches in_review.
    # newest_year is opt-in: the auto-scoring path never passes it, keeping
    # the scorer immune to calendar-year vs data-vintage staleness while
    # review-time callers opt into the stale check.
    fresh = freshness_report(body, newest_year=newest_year)
    factual_score = max(0, factual_score - fresh.penalty)
    # Research validity
    research_score = _research_score(research)

    confidence = round(
        RESEARCH_W * research_score + SEO_W * seo_score + VOICE_W * voice_score + FACTUAL_W * factual_score
    )

    fixes = _build_fixes(
        seo_score, has_h1_kw=has_h1_kw, n_h2=len(h2s), n_faq=len(faqs),
        wc=wc, meta_title=meta_title, meta_desc=meta_desc, density=density,
        structure=structure,
    )

    return SEOReport(
        seo_score=seo_score,
        confidence=confidence,
        meta_title=meta_title,
        meta_description=meta_desc,
        excerpt=first_sentence,
        fixes=fixes,
        voice_score=voice_score,
        factual_score=factual_score,
        research_score=research_score,
        structure_score=structure,
        freshness_issues=fresh.issues,
        freshness_penalty=fresh.penalty,
        breakdown={
            "h1_kw": has_h1_kw, "n_h2": len(h2s), "n_faq": len(faqs),
            "words": wc, "density": round(density, 4),
            "meta_title_len": len(meta_title), "meta_desc_len": len(meta_desc),
            "structure": structure,
            "freshness_penalty": fresh.penalty,
            "freshness_undated": sum(1 for i in fresh.issues if i.kind == "no_dated_source"),
            "freshness_stale": sum(1 for i in fresh.issues if i.kind == "stale"),
        },
    )


def _first_sentence(md: str) -> str:
    text = re.sub(r"^#.*$", "", md, flags=re.M).strip()
    text = re.sub(r"[#*`>]", "", text)
    if not text:
        return ""
    # first 1-2 sentences up to ~160 chars
    m = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    out = ""
    for s in m:
        if len(out) + len(s) > 155:
            break
        out += (s + " ")
    out = out.strip()
    if not out:
        # The opener alone fills the budget (house-voice scene-setters run 180c+):
        # cut it on a word boundary instead of returning "". An empty excerpt
        # leaves the card / hero / RSS description blank and trips the content
        # invariant, so this branch must always produce a sentence-shaped string.
        head = text.replace("\n", " ").strip()
        cut = head[:155].rsplit(" ", 1)[0].rstrip(" ,;:")
        out = (cut or head[:154]).rstrip() + "\u2026"
    return out


# Meta budgets (t_7197386f). The SERP title budget is 60c INCLUDING the
# site-wide " · Nomadomics" brand suffix (frontend/src/lib/seo.ts::TITLE_BUDGET,
# 13c), so the authored value may use at most 47c. The description budget is the
# Strapi schema cap; Google renders ~155c, and the copy deck targets 120-160c.
META_TITLE_VALUE_MAX = 47
META_DESC_MIN = 120
META_DESC_MAX = 160


def _fit_meta_title_value(value: str) -> str:
    """Fit a metaTitle VALUE into the 47c branded budget.

    The served title is `value + " · Nomadomics"` and must stay within the 60c
    SERP budget. A cut lands on a word boundary — never the old
    `base[:57] + "..."` hard cut, which shipped 60c metaTitles that read as
    broken (live 2026-09-28: three published titles ended in a literal '...').
    """
    s = re.sub(r"\s+", " ", value or "").strip()
    if len(s) <= META_TITLE_VALUE_MAX:
        return s
    cut = s[: META_TITLE_VALUE_MAX].rsplit(" ", 1)[0].rstrip(" -–—:;,.")
    return cut or s[: META_TITLE_VALUE_MAX].rstrip(" -–—:;,.")


def _make_meta_title(prim: str, title_line: str) -> str:
    base = title_line.lstrip("# ").strip() or (prim + " Guide")
    base = re.sub(r"\s*\|\s*.*$", "", base).strip()
    return _fit_meta_title_value(base)


def _sentences(body: str) -> list[str]:
    """Clean sentence strings from a markdown body — the raw material the
    excerpt and the meta description are both drawn from (headings and markup
    symbols removed, newlines collapsed into spaces)."""
    text = re.sub(r"^#.*$", "", body or "", flags=re.M)
    text = re.sub(r"[#*`>]", "", text)
    text = text.replace("\n", " ").strip()
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]


def _word_prefix(text: str, limit: int) -> str:
    """First words of `text` up to `limit` chars, on a word boundary, trailing
    separators stripped — never a mid-word cut and never a literal '...'."""
    s = re.sub(r"\s+", " ", text or "").strip()
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0].rstrip(" -–—:;,")
    return cut or s[:limit].rstrip(" -–—:;,")


def _fit_meta_desc(candidate: str) -> str:
    """Fit a description into the 120-160c budget, on word boundaries, with a
    terminal full stop.

    Never a literal '...' cut: the old `s[:157] + "..."` burned three
    characters on punctuation and read as truncated in the SERP (the monitor
    and the write-time invariant both reject a trailing ellipsis). A candidate
    that already ends in punctuation keeps it; otherwise a period is added so
    the snippet is a complete sentence.
    """
    s = re.sub(r"\s+", " ", candidate or "").strip()
    if len(s) > META_DESC_MAX:
        s = _word_prefix(s, META_DESC_MAX)
    if s and not s.endswith((".", "!", "?", ")")):
        s += "."
    return s


def _make_meta_desc(body: str, prim: str) -> str:
    """A 120-160c meta description derived from the article's own sentences and
    guaranteed distinct from the excerpt.

    The old generator had exactly three outcomes and none was authored copy —
    `md == excerpt` for 140-160c openers, the WordPress-migration tail
    ` Learn how to save money on <prim>.` for short openers, and a mid-word
    `s[:157] + "..."` cut over 160c (proved live 2026-09-28). The excerpt is the
    opener PLUS whatever fits under its ~155c budget, so the description must
    draw from a DIFFERENT window: it starts at sentence 2 and only falls back to
    the opener when the body text is too thin to fill the band on its own
    (the two strings still differ, the description being longer). `prim` is kept
    for call compatibility; it is never appended as a template.
    """
    sentences = _sentences(body)
    if not sentences:
        return _fit_meta_desc("")
    window = sentences[1:] if len(sentences) > 1 else sentences
    desc = ""
    for next_sentence in window:
        joined = f"{desc} {next_sentence}".strip()
        if len(joined) > META_DESC_MAX:
            if len(desc) < META_DESC_MIN:
                desc = f"{desc} {_word_prefix(next_sentence, META_DESC_MAX - len(desc) - 1)}".strip()
            break
        desc = joined
        if len(desc) >= META_DESC_MIN:
            break
    if len(desc) < META_DESC_MIN and len(sentences) > 1:
        desc = f"{sentences[0]} {desc}".strip()
    return _fit_meta_desc(desc)


def _voice_score(body: str) -> int:
    """Heuristic voice-match score out of 100 (exemplar markers)."""
    score = 0
    txt = body.lower()
    markers = {
        "2nd person (you/your)": len(re.findall(r"\b(you|your|you're)\b", txt)) >= 5,
        "contractions": len(re.findall(r"\b(won't|can't|it's|you're|don't)\b", txt)) >= 3,
        "em-dash": "\u2014" in body or "--" in body,
        "money-first ($/€/%)": len(re.findall(r"[$€%]\s?\d", body)) >= 2,
        "conversational filler": any(p in txt for p in ("here's the thing", "let's be real", "truth bomb")),
        "scene-setter": any(p in txt for p in ("picture this", "imagine this")),
        "no filler intro": not re.search(r"\bin this article\b|\blet's explore\b", txt),
    }
    points = sum(1 for v in markers.values() if v)
    # weight: 7 markers; base 30 + 10 each
    score = 30 + points * 10
    return min(100, score)


def _factual_score(draft: ArticleDraft, research: Optional[ResearchResult]) -> int:
    """Factual grounding: prefer the writer's declared used_facts; fall back to
    verbatim-citation matching for research claims. Paraphrasing is normal, so
    we count facts the writer declared used OR that appear near-verbatim.
    """
    if not research or not research.facts:
        return 50
    declared = set(f.strip().lower() for f in (draft.used_facts or []) if f.strip())
    body_lower = draft.markdown.lower()
    matched = 0
    for f in research.facts:
        norm = f.claim.strip().lower().replace("\n", " ")
        # declared used counts; else verbatim-able substring match
        if norm in declared or (len(norm) > 40 and norm[:40] in body_lower):
            matched += 1
    if len(research.facts) == 0:
        return 50
    ratio = matched / len(research.facts)
    return min(100, round(ratio * 120))  # 2/3 facts matched -> 80+


def _research_score(research: Optional[ResearchResult]) -> int:
    if not research or not research.facts:
        return 0
    n = len(research.facts)
    if n >= 4:
        return 100
    if n == 3:
        return 85
    if n == 2:
        return 60
    return 30


def _build_fixes(seo_score, *, has_h1_kw, n_h2, n_faq, wc, meta_title, meta_desc, density, structure=0):
    fixes = []
    if structure < 40:
        fixes.append(
            f"Add structure: bullet lists under headings, a comparison table, and "
            f"Pros/Cons (structure score {structure}/100)."
        )
    if seo_score < 70:
        if not has_h1_kw:
            fixes.append("Include the focus keyword in the H1/title.")
        if n_h2 < 4:
            fixes.append(f"Add more H2 sections (have {n_h2}, want 4+).")
        if n_faq < 3:
            fixes.append(f"Add FAQ questions (have {n_faq}, want 3+).")
        if wc < 800:
            fixes.append(f"Expand the article (currently {wc} words).")
        if not (40 <= len(meta_title) <= META_TITLE_VALUE_MAX):
            fixes.append(f"Adjust meta title length (currently {len(meta_title)}).")
        if not (META_DESC_MIN <= len(meta_desc) <= META_DESC_MAX):
            fixes.append(f"Adjust meta description length (currently {len(meta_desc)}).")
        if not (0.004 <= density <= 0.02):
            fixes.append(f"Tune keyword density (currently {density:.1%}).")
    return fixes