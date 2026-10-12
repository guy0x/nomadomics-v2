"""Deterministic, warning-only slop finder for editorial QA.

Pattern-detection rules adapted from 'No AI Slop' (petergyang/no-ai-slop,
MIT). This module is pure Python with no external dependencies — no LLM,
no auto-rewrite, no publish gates. Findings are advisory only.

Public API:
    check_text(text: str) -> list[dict]
"""

import re
import typing as t

# ── Pattern definitions ────────────────────────────────────────────────────

# Generic intro phrases that bury the punchline
GENERIC_INTRO_PATTERNS = [
    r"In today's\s+(fast-paced\s+)?world",
    r"In this\s+(article|blog|post|guide)",
    r"Let's\s+(explore|dive into|take a look at|discover)",
    r"Welcome to",
]

# Empty conclusion sign-offs
EMPTY_CONCLUSION_PATTERNS = [
    r"In\s+(conclusion|summary|closing)",
    r"To\s+sum\s+up",
]

# Meta claims that puff up content
META_CLAIM_PATTERNS = [
    r"This\s+(comprehensive|ultimate|definitive|complete)\s+guide",
    r"This\s+article\s+will",
]

# Weasel/hedge words that weaken claims
HEDGE_PATTERNS = [
    r"\bcould\s+possibly\b",
    r"\barguably\b",
    r"\bsomewhat\b",
    r"\bmight\b(?!\s+not)",
    r"\bsome\s+say\b",
]

MIN_HEDGE_WORD_LENGTH = 4  # skip short words that could be false positives


def _find_closing_passages(text: str) -> list[tuple[int, int, str]]:
    """Find empty conclusion phrases that start paragraphs."""
    findings: list[tuple[int, int, str]] = []
    for pat in EMPTY_CONCLUSION_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            start = m.start()
            # Only flag if at start of text or after a paragraph break
            if start == 0 or text[max(0, start - 2):start] in ("\n\n", "\n", ""):
                findings.append((start, m.end(), m.group(0)))
    return findings


def _find_repeated_openings(text: str) -> list[dict]:
    """Find sentences that start with the same set of words in a paragraph."""
    findings: list[dict] = []
    paragraphs = text.split("\n\n")
    for para in paragraphs:
        if not para.strip():
            continue
        sentences = re.split(r'(?<=[.!?])\s+', para.strip())
        # Group by the first 5 words
        opening_map: dict[str, list[tuple[int, int]]] = {}
        for sent in sentences:
            words = sent.split()
            if len(words) < 5:
                continue
            key = " ".join(words[:3]).lower()
            if key not in opening_map:
                opening_map[key] = []
            opening_map[key].append(
                (text.index(sent), text.index(sent) + len(sent))
            )
        for key, spans in opening_map.items():
            if len(spans) >= 2:
                for start, end in spans:
                    findings.append({
                        "rule_id": "repeated_openings",
                        "severity": "warning",
                        "span": (start, end),
                        "message": f"Repeated opening: '{key}'",
                    })
    return findings


def check_text(text: str) -> list[dict]:
    """Check text for AI-writing slop patterns.

    Returns a list of dicts, each with:
        - rule_id (str)
        - severity (str): always 'warning'
        - span (tuple[int, int]): start/end char indices
        - message (str): human-readable description

    Returns an empty list for clean prose.
    """
    if not text or not text.strip():
        return []

    findings: list[dict] = []

    # -- Generic intros --
    for pat in GENERIC_INTRO_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            findings.append({
                "rule_id": "generic_intro",
                "severity": "warning",
                "span": (m.start(), m.end()),
                "message": f"Generic intro phrase: '{m.group(0)}'",
            })

    # -- Empty conclusions (last third of text only) --
    for start, end, match in _find_closing_passages(text):
        findings.append({
            "rule_id": "empty_conclusion",
            "severity": "warning",
            "span": (start, end),
            "message": f"Empty conclusion phrase: '{match}'",
        })

    # -- Meta claims --
    for pat in META_CLAIM_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            findings.append({
                "rule_id": "meta_claims",
                "severity": "warning",
                "span": (m.start(), m.end()),
                "message": f"Meta claim: '{m.group(0)}'",
            })

    # -- Hedge words --
    for pat in HEDGE_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            findings.append({
                "rule_id": "hedge_words",
                "severity": "warning",
                "span": (m.start(), m.end()),
                "message": f"Hedge word: '{m.group(0)}'",
            })

    # -- Repeated openings (within paragraphs) --
    findings.extend(_find_repeated_openings(text))

    # Deduplicate identical findings (same rule_id + same span)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for f in findings:
        key = (f["rule_id"], f["span"])
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    return deduped