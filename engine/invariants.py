"""Write-time article invariants (ratified E, 2026-09-23; meta-shape rules t_7197386f).

An article is publishable only when the excerpt and meta are non-empty, the
slug has no year, at least two citations are real and visible in a ``## Sources``
section, the opening is not one of the retired generic templates, and all links
pass link hygiene. The publish lane additionally enforces an internal-link
floor (>= 2 distinct internal targets, t_8518b65e). Meta fields are shaped
copy rather than generator artifacts —
the metaDescription is distinct from the excerpt, carries no migration template
tail, ends in terminal punctuation and fits 120-160c; neither meta field ends
in a literal '...'; the metaTitle fits the 60c SERP budget. A citation is real
only when the supplied fetch returns a page whose host matches the URL.
Unreachable, empty, and host-mismatched results are not real. This module does
not publish and does not read secrets.
"""
from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

_YEAR = re.compile(r"20\d{2}")
_FAKE_HOSTS = {"example.com", "example.org", "localhost", "example.net"}

# Meta shape rules (t_7197386f) — mirror the budgets the generator targets:
# description 120-160c (Strapi schema cap 160), title value <= 47c so the
# served title (value + 13c " · Nomadomics") fits the 60c SERP budget. The
# frontend drops the brand for 48-60c values (titledWithBrand), so the guard
# hard-fails the title only past the 60c served cap.
META_DESC_MIN = 120
META_DESC_MAX = 160
META_TITLE_MAX = 60
META_TITLE_VALUE_MAX = 47
_TEMPLATE_TAIL_RE = re.compile(r"Learn how to save money on", re.I)
_ELLIPSIS_ENDS = ("...", "\u2026")
_TERMINAL_ENDS = (".", "!", "?", ")")

# Content-quality gates (canonized 2026-10-11 from the audit evidence used on
# slide 6). The historical corpus overused a "Picture this" opening and often
# had inline citations without a reader-visible source list. New writes must
# prevent both regressions; existing published content is not bulk-rewritten by
# this module.
_SOURCES_HEADING_RE = re.compile(r"(?im)^\s*##\s+sources\s*$")
_GENERIC_OPENING_RE = re.compile(
    r"(?i)^\s*(?:picture\s+this\b|imagine\s+(?:this|you\b))"
)


def citation_fetch(url: str):
    """Offline structural fetch. Does not open a network connection.

    Hosts that are placeholders return 404. Any other https URL returns a
    short page on the same host. Tests that need unreachable or mismatched
    pages pass their own fetch into `citation_is_real`.
    """
    host = (urlparse(url).hostname or "").lower()
    if not url.startswith("https://") or host in _FAKE_HOSTS:
        return 404, "", url
    return 200, "page", url


def citation_is_real(url: str, fetch) -> bool:
    """True only when `fetch` returns a non-empty 200 page on the same host."""
    if not url:
        return False
    try:
        status, body, final = fetch(url)
    except Exception:
        return False
    if int(status or 0) != 200 or not str(body or "").strip():
        return False
    asked = (urlparse(url).hostname or "").lower()
    got = (urlparse(str(final or "")).hostname or "").lower()
    if not asked or asked != got:
        return False
    return True


def _norm_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def meta_title_issues(meta_title: str) -> list[str]:
    """Named metaTitle shape failures (t_7197386f): literal ellipsis cuts and
    values that cannot fit the 60c served SERP budget even without the brand."""
    mt = _norm_spaces(meta_title)
    if not mt:
        return []
    issues = []
    if mt.endswith(_ELLIPSIS_ENDS):
        issues.append("metaTitle ends in an ellipsis cut")
    if len(mt) > META_TITLE_MAX:
        issues.append(f"metaTitle exceeds the {META_TITLE_MAX}c SERP budget")
    return issues


def meta_description_issues(meta_description: str, excerpt: str) -> list[str]:
    """Named metaDescription shape failures (t_7197386f): the three shapes the
    old generator could only produce — excerpt-duplicate, the WordPress-migration
    template tail, and a literal ellipsis cut — plus the length and terminal
    punctuation contract the generator now guarantees."""
    md = _norm_spaces(meta_description)
    if not md:
        return []
    issues = []
    if md.endswith(_ELLIPSIS_ENDS):
        issues.append("metaDescription ends in an ellipsis cut")
    if _TEMPLATE_TAIL_RE.search(md):
        issues.append("metaDescription carries the migration template tail")
    ex = _norm_spaces(excerpt)
    if ex and md.lower() == ex.lower():
        issues.append("metaDescription duplicates the excerpt")
    if not (META_DESC_MIN <= len(md) <= META_DESC_MAX):
        issues.append(f"metaDescription outside {META_DESC_MIN}-{META_DESC_MAX}c")
    if md and not md.endswith(_TERMINAL_ENDS):
        issues.append("metaDescription lacks terminal punctuation")
    return issues


def check_write_invariants(article: dict, citations: list | None = None, fetch=None) -> list[str]:
    """Return invariant failures. Empty means the article may be written."""
    fetch = fetch or citation_fetch
    errors: list[str] = []
    if not str(article.get("excerpt") or "").strip():
        errors.append("empty excerpt")
    if not str(article.get("metaTitle") or "").strip() or not str(article.get("metaDescription") or "").strip():
        errors.append("empty meta")
    errors.extend(meta_title_issues(str(article.get("metaTitle") or "")))
    errors.extend(
        meta_description_issues(
            str(article.get("metaDescription") or ""),
            str(article.get("excerpt") or ""),
        )
    )
    slug = str(article.get("slug") or "")
    if not slug or _YEAR.search(slug):
        errors.append("slug is not yearless")
    real = 0
    for item in citations or []:
        url = item.get("url") if isinstance(item, dict) else str(item)
        if citation_is_real(url or "", fetch):
            real += 1
    if real < 2:
        errors.append("fewer than 2 real citations")
    return errors


def source_section_urls(body: str) -> list[str]:
    """Return real-looking URLs inside the first visible ``## Sources`` section.

    Section parsing is intentionally markdown-light: source bullets and markdown
    links are both accepted, but the section must exist as a reader-visible H2.
    Reality (HTTP status/body/host) is checked by ``source_section_issues`` with
    the injected fetch, not by this extractor.
    """
    body = body or ""
    heading = _SOURCES_HEADING_RE.search(body)
    if not heading:
        return []
    tail = body[heading.end():]
    next_heading = re.search(r"(?im)^\s*##\s+", tail)
    section = tail[:next_heading.start()] if next_heading else tail
    return body_citation_urls(section)


def source_section_issues(body: str, fetch=None) -> list[str]:
    """Named failures for the citation contract (2026-10-11: Guy's rule).

    Blog articles need hyperlinks, not a works-cited footer: the contract is
    >=2 real inline hyperlinks woven into the body. A trailing ``## Sources``
    section is OPTIONAL — when present it still counts toward coverage, but its
    absence alone is no longer a failure.
    """
    fetch = fetch or citation_fetch
    inline = [u for u in body_markdown_link_urls(body) if citation_is_real(u, fetch)]
    section = [u for u in source_section_urls(body) if citation_is_real(u, fetch)]
    if len(inline) + len(section) < 2:
        return ["fewer than 2 real inline citations (body hyperlinks or Sources entries)"]
    return []


def _first_prose_paragraph(body: str) -> str:
    """The article's first prose paragraph, with the H1 removed."""
    prose = re.sub(r"(?m)^\s*#\s+.*$", "", body or "", count=1).strip()
    return re.split(r"\n\s*\n", prose, maxsplit=1)[0].strip()


def opening_pattern_issues(body: str) -> list[str]:
    """Reject retired generic opener templates that caused corpus repetition."""
    if _GENERIC_OPENING_RE.match(_first_prose_paragraph(body)):
        return ["generic opening template is not allowed"]
    return []


# --- Corpus-repetition gate (t_252b48e7, 2026-10-12) --------------------------
# Guy's MCQ verdict: BOTH mechanisms. Evidence: "Picture this, you" opened 13
# published articles identically and "vibrant" appears in 29 of 50 published
# articles, while the retired regex bans only two named openers. This is the
# generalized form: (1) any opener 3-gram already used by >= 2 published
# articles is a repeated opener template; (2) a seeded cliche census fails an
# article that leans on >= 2 seeded phrases. Deterministic, no LLM, no new
# state — the caller passes the published corpus it already fetched.
CLICHE_PHRASES = (
    "vibrant", "boasts", "nestled", "hidden gem", "look no further",
    "game-changer", "when it comes to",
)
CLICHE_MAX_PER_ARTICLE = 2      # distinct seeded phrases allowed per article
OPENER_WORD_WINDOW = 6          # the first N words count as the "opener"
OPENER_NGRAM_SIZE = 3
# A 3-gram shared by both members of a two-row corpus proves nothing (and
# OPENER_MIN_CORPUS=3 means a site's second-ever article can never be blocked
# by its first), so the opener check needs at least this many usable bodies.
OPENER_MIN_CORPUS = 3
_WORD_RE = re.compile(r"[a-z0-9']+")


def _opener_ngrams(body: str) -> set[str]:
    """The opener's word 3-grams (lowercased), within the first ~6 words."""
    first = _first_prose_paragraph(body or "")
    words = _WORD_RE.findall(first.lower())[:OPENER_WORD_WINDOW]
    n = OPENER_NGRAM_SIZE
    if len(words) < n:
        return set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def cliche_issues(body: str, max_phrases: int = CLICHE_MAX_PER_ARTICLE) -> list[str]:
    """Named failure when the body leans on too many seeded cliche phrases.

    The threshold counts DISTINCT seeded phrases present ("using >= 2 seeded
    cliches"), case-insensitively; the message carries per-phrase hit counts
    so a rewrite knows what to strip.
    """
    text = (body or "").lower()
    present = []
    for phrase in CLICHE_PHRASES:
        hits = len(re.findall(re.escape(phrase), text))
        if hits:
            present.append((phrase, hits))
    if len(present) < max_phrases:
        return []
    census = ", ".join(f"'{p}' x{h}" for p, h in present)
    return [
        f"cliche density over threshold "
        f"({len(present)}/{len(CLICHE_PHRASES)} seeded phrases; {census})"
    ]


def corpus_repetition_issues(
    body: str,
    published_rows: list[dict],
    *,
    own_slug: str = "",
) -> list[str]:
    """Named failures tying this body to repeated shapes in the live corpus.

    ``published_rows`` are published article rows ({slug, bodyMarkdown});
    callers pass the corpus they already fetched (the publish lane's
    link-target read), so this adds no request of its own. Rows without body
    text and the article's own slug are skipped; the opener check is inert
    below OPENER_MIN_CORPUS usable bodies.
    """
    bodies = [
        (str(r.get("slug") or ""), str(r.get("bodyMarkdown") or ""))
        for r in published_rows or []
    ]
    bodies = [(s, b) for s, b in bodies if b.strip() and s != own_slug]

    issues: list[str] = []
    grams = _opener_ngrams(body)
    if grams and len(bodies) >= OPENER_MIN_CORPUS:
        counts: Counter[str] = Counter()
        for _slug, b in bodies:
            for gram in _opener_ngrams(b):
                counts[gram] += 1
        for gram in sorted(grams):
            n = counts.get(gram, 0)
            if n >= 2:
                issues.append(f"opener 3-gram '{gram}' already used by {n} articles")
    issues.extend(cliche_issues(body))
    return issues


def article_invariant_errors(
    article: dict,
    fetch=None,
    published_corpus: list[dict] | None = None,
) -> list[str]:
    """All write/publish invariants for a Strapi article row.

    This is the single shared gate used by the draft and daily publish lanes:
    metadata/citations, visible source coverage, opening diversity, and link
    hygiene must agree before a write or publish can proceed.

    With ``published_corpus`` (the publish lane's already-fetched published
    rows, bodyMarkdown included) the corpus-repetition gate runs too: a
    repeated opener 3-gram or seeded-cliche overload fails alongside the shape
    gates. Without it the gate stays inert — the draft lane's write check has
    no body corpus in reach, and fetching one there would add a second read
    the card forbids.
    """
    body = article.get("bodyMarkdown") or ""
    errors = check_write_invariants(
        {
            "excerpt": article.get("excerpt"),
            "metaTitle": article.get("metaTitle"),
            "metaDescription": article.get("metaDescription"),
            "slug": article.get("slug"),
        },
        [{"url": u} for u in body_citation_urls(body)],
        fetch=fetch,
    )
    errors.extend(source_section_issues(body, fetch=fetch))
    errors.extend(opening_pattern_issues(body))
    errors.extend(link_hygiene_issues(body))
    if published_corpus is not None:
        errors.extend(corpus_repetition_issues(
            body, published_corpus, own_slug=str(article.get("slug") or "")))
        # Internal-link floor (t_8518b65e): the publish lane MUST NOT ship a
        # body with fewer than MIN_INTERNAL_LINKS internal links. The gate is
        # corpus-gated like the repetition gate above so the draft lane's
        # write check (no corpus in reach) keeps accepting drafts and the
        # ensure_internal_links backstop stays its only link source; the
        # publish step enforces the floor. With the corpus in hand the count
        # resolves like the fleet monitor: only links to published articles
        # count, never the article's own slug.
        published_slugs = {str(r.get("slug")) for r in published_corpus if r.get("slug")}
        errors.extend(internal_link_issues(
            body, published_slugs=published_slugs or None,
            own_slug=str(article.get("slug") or "")))
    return errors


def body_citation_urls(body: str) -> list[str]:
    """https URLs in an article body, in order of appearance, deduped."""
    return list(dict.fromkeys(re.findall(r"https://[^\s)>\]\"]+", body or "")))


def body_markdown_link_urls(body: str) -> list[str]:
    """URLs appearing as proper ``[anchor](url)`` markdown links in the body.

    Excludes the ``## Sources`` section (those are counted separately) and
    dedupes, preserving order. Bare/paren URLs are deliberately excluded —
    link hygiene flags those shapes already.
    """
    body = body or ""
    heading = _SOURCES_HEADING_RE.search(body)
    prose = body[:heading.start()] if heading else body
    urls = re.findall(r"\[[^\]]+\]\((https?://[^)\s]+)\)", prose)
    return list(dict.fromkeys(urls))


# ---- Link hygiene (QA: Guy 2026-10-05) ------------------------------
# Every link must be a proper `[anchor](url)` hyperlink woven into natural
# prose. The corpus historically shipped three violations the frontend renders
# as broken/garbage: bare URLs dropped into prose, URLs wrapped in parens as
# plain text (not markdown links), and hyphenated-slug anchors that point to
# the wrong target (e.g. an internal slug anchor href'd to an external host).
_RAW_URL_RE = re.compile(r"https?://[^\s\)\]\u3011\u300d\u3000\"'<>]+")
_SLUG_ANCHOR_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")


def link_hygiene_issues(body: str) -> list[str]:
    """Named QA failures for a body's internal/external links.

    Flags four shapes the frontend cannot render as sane hyperlinks:

      * RAW URL     — an ``http(s)://`` token that appears in prose *not*
                      inside a markdown link. Renders as a bare text URL.
      * PAREN URL   — an ``http(s)://`` wrapped in ``( )`` as plain text
                      without the ``[...](...)`` markdown form.
      * SLUG ANCHOR — a markdown link whose visible anchor is a hyphenated
                      lowercase slug (``[best-esim-plans-for-digital-nomads]``)
                      instead of natural text.
      * WRONG-DOMAIN — a slug-anchor link whose href is an *internal* slug
                      pattern aimed at an external host (e.g. a Nomadonics
                      article slug link to ``https://nomadlist.com``).
    """
    body = body or ""
    issues: list[str] = []
    for m in _MD_LINK.finditer(body):
        anchor = m.group(1).strip()
        url = m.group(2).strip()
        if _SLUG_ANCHOR_RE.match(anchor):
            dom = urlparse(url).hostname or ""
            flag = "wrong-domain" if re.match(r"https?://", url) and not re.match(
                r"(?:www\.)?nomadomics\.(?:com|blog)$", dom
            ) else "slug-anchor"
            issues.append(f"link-anchor [{anchor}] -> {url} ({flag})")
    # mask markdown links so bare-URL detection only sees prose
    prose = _MD_LINK.sub("", body)
    for m in _RAW_URL_RE.finditer(prose):
        before = prose[max(0, m.start() - 1):m.start()]
        prev = prose[max(0, m.start() - 4):m.start()]
        if prev and prev.rstrip().endswith("("):
            issues.append(f"paren-url {m.group(0)[:80]}")
        else:
            issues.append(f"raw-url {m.group(0)[:80]}")
    return issues


def _fact_source(fact) -> tuple[str, str]:
    """(url, title) of a research fact, whether dataclass or dict."""
    if isinstance(fact, dict):
        return str(fact.get("source_url") or ""), str(fact.get("source_title") or "")
    return str(getattr(fact, "source_url", "") or ""), str(
        getattr(fact, "source_title", "") or ""
    )


def _source_line(url: str, title: str) -> str:
    """Render a source as a proper markdown link, even without a title."""
    anchor = _norm_spaces(title) or "Source"
    return f"- [{anchor}]({url})"


def _insert_source_lines(body: str, lines: list[str]) -> str:
    """Insert missing source bullets into the first visible Sources section."""
    if not lines:
        return body
    heading = _SOURCES_HEADING_RE.search(body or "")
    if not heading:
        joined = "\n".join(lines)
        return f"{(body or '').rstrip()}\n\n## Sources\n\n{joined}\n"
    return (
        body[:heading.end()]
        + "\n\n"
        + "\n".join(lines)
        + "\n"
        + body[heading.end():].lstrip("\n")
    )


def ensure_body_citations(body: str, facts, fetch=None) -> str:
    """Guarantee two real citations per the citation contract (Guy's rule).

    Since 2026-10-11 the contract is >=2 real inline hyperlinks in the body;
    a trailing ``## Sources`` section is optional. This backstop therefore only
    acts when the body lacks two real inline (or section) links, appending the
    smallest missing set of real research sources. Generated bullets are always
    markdown links so the link-hygiene gate cannot reject its own repair. The
    function is idempotent and never fabricates a source.
    """
    fetch = fetch or citation_fetch
    real: list[tuple[str, str]] = []
    seen: set[str] = set()
    for fact in facts or []:
        url, title = _fact_source(fact)
        if url and url not in seen and citation_is_real(url, fetch):
            real.append((url, title))
            seen.add(url)

    body = body or ""
    cited = [u for u in body_citation_urls(body) if citation_is_real(u, fetch)]
    if len(cited) >= 2:
        return body
    visible = [u for u in source_section_urls(body) if citation_is_real(u, fetch)]
    visible_set = set(visible)
    cited_set = set(cited)
    needed = max(0, 2 - len(cited))
    fresh = [item for item in real
             if item[0] not in visible_set and item[0] not in cited_set]
    additions = (fresh or [item for item in real if item[0] not in visible_set])[:needed]
    if not additions:
        return body
    return _insert_source_lines(body, [_source_line(url, title) for url, title in additions])


# --- Internal-link backstop (2026-10-04) --------------------------------------
# The citation analogue of `ensure_body_citations`. The writer prompt does not
# ask for internal links and nothing post-processed the body, so every newly
# published article shipped with whatever the model happened to emit — usually
# none. Live 2026-10-04: `budgeting-apps-for-digital-nomads` published with 0
# internal links against a corpus at 41/42. The earlier 09-23..10-01 cohort was
# repaired by a one-off data pass, which fixed history but left this publish
# path untouched, so the regression recurred on the very next article.
MIN_INTERNAL_LINKS = 2

_INTERNAL_ABS = re.compile(
    r"https?://(?:www\.)?nomadomics\.(?:com|blog)/", re.I)
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def body_internal_link_targets(body: str) -> list[str]:
    """Distinct internal link targets in `body`, counting BOTH forms.

    Relative `/slug` and absolute `https://nomadomics.(com|blog)/slug` both
    count. An absolute-only-vs-relative-only mismatch between the detector and
    the fixer is exactly what made an earlier scan report 8 unlinked articles
    when there were 9, so both sides must use this function.
    """
    seen: list[str] = []
    for m in _MD_LINK.finditer(body or ""):
        url = m.group(2).split("#")[0].strip()
        if url.startswith("/"):
            key = url
        elif _INTERNAL_ABS.match(url):
            key = "/" + url.split("nomadomics.", 1)[1].split("/", 1)[1]
        else:
            continue
        if key not in seen:
            seen.append(key)
    return seen


_TITLE_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "what", "when", "where", "which", "who", "why", "with", "your",
}


def internal_link_issues(body: str, min_links: int = MIN_INTERNAL_LINKS,
                         published_slugs: set[str] | None = None,
                         own_slug: str = "") -> list[str]:
    """Named failure when the body carries fewer than `min_links` internal links.

    Counts DISTINCT internal targets — relative ``/slug`` and absolute
    ``https://nomadomics.(com|blog)/slug`` — with the same detector the
    backstop uses (``body_internal_link_targets``), so the gate and the fixer
    can never disagree about what counts (that disagreement already cost one
    article a false 8-vs-9 scan, 2026-10-04).

    Publish-lane enforcement (t_8518b65e): the draft lane may still WRITE a
    below-threshold body (its ``ensure_internal_links`` backstop tops it up),
    but the publish step must never ship one — a below-floor article is
    blocked, exactly like a below-floor citation count.

    Resolution contract (fleet monitor parity, t_8518b65e): when
    ``published_slugs`` is supplied (the publish lane always has the corpus),
    only targets that resolve to a PUBLISHED article count, and the article's
    own slug never counts. This is how the fleet monitor measures coverage —
    a link to a slug that is not (yet) published is a dangling 404 and counts
    zero, exactly like the bare-slug href if broken. ``internal-link coverage
    is 48/49`` survived because the shape-only count said 2 while the monitor
    correctly counted 1 (live 2026-10-12:
    ``international-health-insurance-claims-abroad`` linked a non-published
    slug). An empty/absent slug set degrades to shape-counting: with nothing
    to resolve against, only the link shape can be judged.
    """
    targets = body_internal_link_targets(body or "")
    if published_slugs:
        targets = [
            t.lstrip("/") for t in targets
            if t.lstrip("/") in published_slugs and t.lstrip("/") != own_slug
        ]
    have = len(targets)
    if have >= min_links:
        return []
    if published_slugs:
        noun = "internal links to published articles"
    else:
        noun = "internal links"
    return [f"fewer than {min_links} {noun} (have {have})"]


def _mention_phrases(title: str) -> list[str]:
    """Candidate in-body phrase for a title.

    Deliberately conservative. Corpus titles are SEO forms
    ("Travel Insurance Exclusions: What to Check for Digital Nomads") while a
    body names the topic by its head ("travel insurance exclusions"), so the
    head — the text before any ``: | - —`` break — is the only phrase offered.

    An earlier version emitted progressively shorter leading word-runs down to
    three words. That produced broken prose in live testing: it linked
    "Digital Nomad Communities" inside "Digital Nomad Communities In Every Major
    Hub", leaving a dangling fragment. When a head does not match verbatim, the
    caller falls back to the related list, which reads far better than a
    mid-phrase link.
    """
    head = re.split(r"[:—\-|]", title)[0].strip()
    head = re.sub(r"\s+", " ", head)
    words = re.findall(r"[\w'&]+", head)
    if len(words) < 2:
        return []
    return [head]


def ensure_internal_links(body: str, corpus, *, own_slug: str = "",
                          min_links: int = MIN_INTERNAL_LINKS) -> str:
    """Guarantee the body carries >= `min_links` distinct internal links.

    Mirrors `ensure_body_citations`: the writer is asked to link inline, and
    this is the deterministic backstop for when it doesn't. Prefers CONTEXTUAL
    links — wraps the first in-body mention of a target's title — and only
    tops up with a short related list when that isn't enough to reach the
    floor. Returns the body unchanged when it already complies, so the function
    is idempotent and safe to run on every write.
    """
    body = body or ""
    if len(body_internal_link_targets(body)) >= min_links:
        return body

    own = f"/{own_slug}" if own_slug else None
    targets = []
    for item in corpus or []:
        slug = item.get("slug")
        title = (item.get("title") or "").strip()
        if not slug or not title:
            continue
        href = f"/{slug}"
        if href == own:
            continue                      # never self-link
        targets.append((href, title))

    if not targets:
        return body

    out = body
    linked = 0
    for href, title in targets:
        if len(body_internal_link_targets(out)) >= min_links:
            break
        if href in body_internal_link_targets(out):
            linked += 1
            continue
        # contextual: link the first bare in-body mention of this article. Real
        # titles are long SEO forms ("Travel Insurance Exclusions: What to
        # Check..."), but bodies usually mention the short head of that title,
        # so try the full title first and then progressively shorter leading
        # phrases. Matching the exact title alone fell through to the related
        # list on a body that clearly referenced the topic.
        for phrase in _mention_phrases(title):
            # Case-insensitive match, but the link text keeps the BODY's own
            # casing rather than the corpus title's — a body that writes
            # "travel insurance exclusions" should not be capitalised by a
            # link. Word-boundary guards stop a match inside a longer word or
            # inside an existing markdown label.
            pattern = re.compile(
                r"(?<![\[\(])(" + re.escape(phrase) + r")(?![\]\)])",
                re.IGNORECASE)
            m = pattern.search(out)
            if m:
                found = m.group(1)
                out = (out[:m.start()] + f"[{found}]({href})" + out[m.end():])
                linked += 1
                break

    have = len(body_internal_link_targets(out))
    if have < min_links:
        missing = [(h, t) for h, t in targets
                   if h not in body_internal_link_targets(out)]
        need = min_links - have
        lines = "\n".join(f"- [{t}]({h})" for h, t in missing[:need])
        if lines:
            out = f"{out.rstrip()}\n\n## Related reading\n\n{lines}\n"
    return out
