"""Internal-link floor enforcement + fail-closed quality gates (kanban t_8518b65e).

Guy decisions 2026-10-12 (items 6 + 8): repair the 48/49 internal-link
coverage defect AND enforce the >=2 internal-link threshold in the publish
path; new content-quality failures fail closed into quarantine (blocked +
journaled, never published — mirroring the t_cae3c2d2 quarantine gate rather
than inventing a new state).

Pinned here:

* `invariants.internal_link_issues` — the named floor gate (relative ``/slug``
  and absolute ``nomadomics.(com|blog)`` targets, distinct, using the same
  detector as the backstop so gate and fixer can never disagree).
* `article_invariant_errors(published_corpus=...)` — the internal-link check is
  wired under the corpus branch, so the draft write path (no corpus in reach)
  keeps its backstop-only behavior while the publish lane enforces the floor.
  This mirrors the corpus-repetition gate precedent exactly.
* `publish.publish_one` — fail closed at three points: (1) the published-corpus
  read errors -> the run is journaled and skipped (no candidate can be
  cleanly evaluated); (2) a candidate's gate evaluation raises -> that
  article is journaled and blocked while other candidates are still scanned;
  (3) the FINAL body (post-polish, the markdown actually shipped) is below the
  internal-link floor -> journaled skip, never written.
* `pipeline_cli` draft lane AUTO_PUBLISH — the internal-link floor must hold on
  the body being auto-published; a below-threshold body lands in_review with a
  journaled refusal instead of shipping (the 13:00 publish lane retries).

Run:  cd ~/nomadomics-v2 && env -u PYTHONPATH .venv/bin/python -m pytest \
          engine/tests/test_internal_link_publish_gate.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import invariants  # noqa: E402
from invariants import (  # noqa: E402
    MIN_INTERNAL_LINKS,
    article_invariant_errors,
    body_internal_link_targets,
    internal_link_issues,
)
import publish  # noqa: E402

VALID_DESC = (
    "Living costs, visa rules and internet speeds differ in every hub. "
    "This guide compares the practical numbers so you can pick a base "
    "before you book a flight."
)

CITATIONS = (
    "## Sources\n\n"
    "- [IRS A](https://irs.gov/a)\n"
    "- [State B](https://travel.state.gov/b)\n"
)


def candidate(body: str, slug: str = "new-slug") -> dict:
    return {
        "excerpt": "A real excerpt sentence.",
        "metaTitle": "A title",
        "metaDescription": VALID_DESC,
        "slug": slug,
        "bodyMarkdown": body,
    }


def body_below_floor() -> str:
    return (
        "# Guide\n\nThe fee is $10 and the threshold is $20.\n\n"
        + CITATIONS
    )


def body_at_floor() -> str:
    return (
        "# Guide\n\nThe fee is $10 and the threshold is $20. See "
        "[the eSIM guide](/best-esim-plans-for-digital-nomads) and "
        "[travel insurance notes](/travel-insurance-for-digital-nomads).\n\n"
        + CITATIONS
    )


# --- invariants.internal_link_issues ----------------------------------------

def test_floor_counts_relative_and_absolute_targets():
    body = (
        "Text with [a](/alpha) and [b](https://nomadomics.com/beta) and "
        "[c](https://www.nomadomics.blog/gamma).\n"
    )
    # three distinct targets -> at the floor and above it
    assert internal_link_issues(body) == []
    assert internal_link_issues(body, min_links=4)  # min_links=4 fails


def test_floor_dedupes_repeated_targets():
    body = (
        "Text with [a](/alpha), again [a](/alpha), and once more "
        "[a](https://nomadomics.com/alpha).\n"
    )
    assert len(body_internal_link_targets(body)) == 1
    assert internal_link_issues(body)


def test_floor_fails_below_two_and_passes_at_two():
    assert internal_link_issues(body_below_floor()) == [
        f"fewer than {MIN_INTERNAL_LINKS} internal links (have 0)"
    ]
    one = "# T\n\nSee [a](/alpha).\n\n" + CITATIONS
    assert internal_link_issues(one)
    assert internal_link_issues(body_at_floor()) == []


# --- article_invariant_errors wiring ----------------------------------------

def test_article_gate_enforces_floor_only_with_corpus():
    """Publish lane (corpus in reach) rejects below-threshold; draft write
    path (no corpus) is unaffected — the same shape as the repetition gate."""
    below = candidate(body_below_floor())
    # without a corpus the internal floor is inert (draft write path)
    assert not any(
        "internal links" in e for e in article_invariant_errors(below)
    )
    # with the corpus (publish lane) the named failure appears
    errors = article_invariant_errors(below, published_corpus=[])
    assert any("internal links" in e and f"have 0" in e for e in errors)


def test_article_gate_clean_candidate_still_passes_with_corpus():
    errors = article_invariant_errors(
        candidate(body_at_floor()), published_corpus=[]
    )
    assert errors == []


# --- resolution contract (fleet-monitor parity) ------------------------------

def test_floor_resolves_targets_against_published_slugs():
    """A shape-count of 2 with one DANGLING target counts 1, exactly like the
    fleet monitor (the live 48/49 defect): only published targets count."""
    body = (
        "# Guide\n\nSee [the health guide](/nomad-health-insurance-guide) and "
        "[the apps roundup](/essential-apps-for-digital-nomads).\n\n" + CITATIONS
    )
    # shape-only (no corpus in reach) says 2 -> at floor
    assert internal_link_issues(body) == []
    # resolution says 1 of 2 resolves -> below floor
    issues = internal_link_issues(
        body, published_slugs={"nomad-health-insurance-guide", "other-slug"})
    assert issues == [
        "fewer than 2 internal links to published articles (have 1)"
    ]
    # both targets published -> at floor
    assert internal_link_issues(
        body, published_slugs={"nomad-health-insurance-guide",
                               "essential-apps-for-digital-nomads"}) == []


def test_floor_never_counts_the_own_slug():
    body = "# Guide\n\nSee [me](/own-slug) and [the guide](/nomad-health-insurance-guide)."
    assert internal_link_issues(
        body, published_slugs={"own-slug", "nomad-health-insurance-guide"},
        own_slug="own-slug") == [
            "fewer than 2 internal links to published articles (have 1)"
        ]


def test_article_gate_resolves_against_the_live_corpus():
    """article_invariant_errors with a NON-EMPTY corpus enforces resolution:
    a body whose internal links mostly point at non-published slugs fails the
    publish gate — the exact shape that shipped the 48/49 defect."""
    body = (
        "# Guide\n\nSee [the health guide](/nomad-health-insurance-guide) and "
        "[the apps roundup](/essential-apps-for-digital-nomads).\n\n" + CITATIONS
    )
    corpus = [{"slug": "nomad-health-insurance-guide"}, {"slug": "other-slug"}]
    errors = article_invariant_errors(candidate(body), published_corpus=corpus)
    assert any("internal links to published articles" in e and "have 1" in e
               for e in errors)
    # with both targets in the corpus the same body passes
    corpus2 = [{"slug": "nomad-health-insurance-guide"},
               {"slug": "essential-apps-for-digital-nomads"}]
    errors2 = article_invariant_errors(candidate(body), published_corpus=corpus2)
    assert not any("internal links" in e for e in errors2)


# --- publish_one fail-closed points -----------------------------------------

class FakeClient:
    """Minimal duck-typed Strapi agent for publish_one interactions."""

    def __init__(self, articles, *, corpus_raises=False):
        self.articles = articles
        self.corpus_raises = corpus_raises
        self.updates = []
        self.calls = []
        self.corpus_calls = 0

    def list_published_titles(self):
        return []

    def _request(self, method, path, params=None, body=None):
        self.calls.append((method, path, params))
        self.corpus_calls += 1
        if self.corpus_raises and params and params.get("filters[status][$eq]") == "published":
            raise OSError("network down (fixture)")
        if path == "/api/articles" and params and params.get("filters[status][$eq]") == "in_review":
            return {"data": self.articles}
        if path == "/api/articles" and params and params.get("filters[status][$eq]") == "published":
            return {"data": [a for a in self.articles if a.get("status") == "published"]}
        return {"data": []}

    def update_article(self, doc_id, fields, *, status="draft"):
        self.updates.append((doc_id, fields, status))

    def close(self):
        pass


def _make_article(slug="tax-article", body=None, confidence=87, doc_id="doc-1"):
    a = {
        "slug": slug,
        "documentId": doc_id,
        "title": slug.replace("-", " ").title(),
        "confidence": confidence,
        "status": "in_review",
        "bodyMarkdown": body or body_at_floor(),
        "excerpt": "A short excerpt for the card.",
        "metaTitle": "Tax Article",
        "metaDescription": VALID_DESC,
        "focusKeyword": "taxes",
        "topicDecision": "needs_review",
    }
    return a


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "PUBLISH_STATE_FILE", tmp_path / "publish-pipeline.jsonl")
    monkeypatch.setattr(publish, "SHARED_LEDGER", tmp_path / "publish-ledger.jsonl")
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", tmp_path / "pipeline.jsonl")
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", tmp_path / "release-approvals.jsonl")
    monkeypatch.setattr(publish, "SNAPSHOT", tmp_path / "published-slugs.json")
    monkeypatch.setattr(publish, "PUBLIC_CARDS", tmp_path / "cards")
    monkeypatch.setattr(publish, "PUBLIC_OG", tmp_path / "og")
    monkeypatch.setattr(publish, "browser_asset_ready", lambda slug: (True, "fixture receipt"))
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())


def _read_events(path):
    if not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def test_corpus_fetch_error_fails_closed_and_journals(monkeypatch, tmp_path):
    """A gate read that ERRORS must not wave candidates through: journaled skip."""
    client = FakeClient([_make_article()], corpus_raises=True)

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    assert "corpus fetch failed" in result["reason"]
    assert client.updates == []  # nothing written
    events = _read_events(publish.PUBLISH_STATE_FILE)
    assert any(e["event"] == "publish_gate_error"
               and e["gate"] == "published_corpus_fetch" for e in events)


def test_candidate_gate_exception_journals_and_blocks_only_that_article(monkeypatch, tmp_path):
    """A candidate whose gate ERRORS is journaled + skipped; a healthy sibling
    is still eligible — fail closed is per-article, not run-wide."""
    broken = _make_article(slug="broken", doc_id="doc-broken", body=body_below_floor())
    healthy = _make_article(slug="healthy", doc_id="doc-healthy")

    real_gate = publish.article_invariant_errors

    def exploding_gate(article, **kw):
        if article.get("slug") == "broken":
            raise RuntimeError("gate exploded (fixture)")
        return real_gate(article, **kw)

    monkeypatch.setattr(publish, "article_invariant_errors", exploding_gate)
    client = FakeClient([broken, healthy])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "dry_run"
    assert result["slug"] == "healthy"
    assert client.updates == []
    events = _read_events(publish.PUBLISH_STATE_FILE)
    hits = [e for e in events if e["event"] == "publish_gate_error"
            and e.get("slug") == "broken"]
    assert hits and hits[-1]["gate"] == "article_invariants"


def test_final_body_below_floor_is_journaled_skip_never_published(monkeypatch, tmp_path):
    """Candidate selection passed on the STORED body (at floor), but the
    polish pass writes the body actually shipped — if THAT body drops below
    the floor (and the backstop has no corpus to top up from), the publish is
    a journaled skip and the published layer is never touched."""
    winner = _make_article(slug="below-floor", body=body_at_floor())
    # the polished body LOSES the internal links the stored body had
    monkeypatch.setattr(publish, "polish_article",
                        lambda *a, **k: {"markdown": body_below_floor()})
    monkeypatch.setattr(publish, "list_published", lambda c, **k: [])
    client = FakeClient([winner])

    result = publish.publish_one(client, None, dry_run=False)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    assert "internal-link floor blocked publish" in result["reason"]
    assert client.updates == []  # the published layer was never touched
    events = _read_events(publish.PUBLISH_STATE_FILE)
    assert any(e["event"] == "publish_refused_internal_links"
               and e["slug"] == "below-floor" for e in events)


def test_final_body_at_floor_still_publishes(monkeypatch, tmp_path):
    """The floor does not over-block: a compliant final body reaches the write."""
    winner = _make_article(slug="at-floor", body=body_at_floor())
    monkeypatch.setattr(publish, "polish_article", lambda *a, **k: None)
    monkeypatch.setattr(publish, "list_published", lambda c, **k: [])
    monkeypatch.setattr(publish, "style_judge_gate", lambda a, cfg=None: {"ok": True})
    client = FakeClient([winner])

    result = publish.publish_one(client, None, dry_run=False,
                                 skip_image=True, no_commit=True)  # type: ignore[arg-type]

    assert result["event"] == "published"
    assert result["slug"] == "at-floor"
    # the write carried the body with its two internal links
    written = client.updates[-1][1]
    assert len(body_internal_link_targets(written["bodyMarkdown"])) >= MIN_INTERNAL_LINKS


def test_final_body_gate_error_journals_and_skips(monkeypatch, tmp_path):
    """A raised gate in the final-body chain is journaled and never ships."""
    winner = _make_article(slug="gate-error", body=body_at_floor())

    def exploding_backstop(md, corpus, **kw):
        raise TimeoutError("corpus read timed out (fixture)")

    monkeypatch.setattr(publish, "ensure_internal_links", exploding_backstop)
    monkeypatch.setattr(publish, "polish_article", lambda *a, **k: None)
    monkeypatch.setattr(publish, "list_published", lambda c, **k: [])
    client = FakeClient([winner])

    result = publish.publish_one(client, None, dry_run=False)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    assert "gate error" in result["reason"]
    assert client.updates == []
    events = _read_events(publish.PUBLISH_STATE_FILE)
    assert any(e["event"] == "publish_gate_error"
               and e.get("gate") == "final-body" for e in events)


# --- pipeline_cli draft-lane AUTO_PUBLISH floor (t_8518b65e) -----------------

def test_draft_lane_autopublish_blocked_below_internal_floor(monkeypatch, tmp_path):
    """AUTO_PUBLISH must fail closed: a body whose backstop could not reach the
    internal-link floor (empty corpus at write time) lands in_review with a
    journaled refusal — the draft lane never auto-publishes it."""
    from test_pipeline import FakeStrapi, make_cfg, _make_high_conf_draft

    class EmptyCorpusStrapi(FakeStrapi):
        def list_published_titles(self):
            return []

    import pipeline_cli
    from research.research import Fact, ResearchResult
    from writer.writer import ArticleDraft
    from editor.editor import EditedDraft
    from seo.analyze import SEOReport

    monkeypatch.setattr(pipeline_cli, "PUBLISH_LEDGER", tmp_path / "publish-ledger.jsonl")
    monkeypatch.setattr(pipeline_cli, "STATE_FILE", tmp_path / "pipeline.jsonl")
    client = EmptyCorpusStrapi()
    client.topic["attributes"].update({"slug": "esim-plans", "category": "gear",
                                       "primaryKeyword": "eSIM travel"})
    cfg = make_cfg()
    cfg = type(cfg)(
        strapi_url=cfg.strapi_url, strapi_engine_token=cfg.strapi_engine_token,
        openrouter_api_key=cfg.openrouter_api_key,
        auto_publish_enabled=True, first_n_human_review=0,
    )
    body = _make_high_conf_draft()
    monkeypatch.setattr(pipeline_cli, "browser_asset_ready", lambda slug: (True, "fixture receipt"))
    monkeypatch.setattr(
        pipeline_cli, "research_topic",
        lambda topic, kw, config=None, **k: ResearchResult(
            topic=topic,
            facts=[
                Fact(claim="Airalo covers 200+ countries.", source_url="https://airalo.com"),
                Fact(claim="Roaming costs $50+ per trip.", source_url="https://www.fcc.gov/roaming"),
                Fact(claim="eSIM cuts roaming cost by 80%.", source_url="https://example.com/e"),
            ],
        ),
    )
    monkeypatch.setattr(pipeline_cli, "validate_research", lambda r, min_facts=3: (True, [], []))
    monkeypatch.setattr(
        pipeline_cli, "draft_article",
        lambda *a, **k: ArticleDraft(markdown=body, word_count=len(body.split()),
                                     used_facts=["Airalo covers 200+ countries."]),
    )
    monkeypatch.setattr(
        pipeline_cli, "edit_draft",
        lambda draft, topic, kw, research, config=None, **k: EditedDraft(
            markdown=draft.markdown, word_count=draft.word_count,
            used_facts=list(draft.used_facts), edit_report="pass",
        ),
    )
    monkeypatch.setattr(
        pipeline_cli, "analyze_seo",
        lambda draft, pk, secondary_keywords=None, research=None: SEOReport(
            seo_score=85, confidence=90, meta_title="X",
            meta_description=VALID_DESC, excerpt="Z.",
        ),
    )

    result = pipeline_cli.draft_one(client, cfg, "esim-plans")  # type: ignore[arg-type]

    assert result["published"] is False
    # never a published-layer write
    assert not any(s[2] == "published" for s in client.published)
    # article landed in_review for the 13:00 lane to retry
    assert client.published and client.published[-1][1].get("status") == "in_review"
    # the refusal is journaled with the floor detail
    events = [json.loads(line) for line in
              pipeline_cli.STATE_FILE.read_text().splitlines() if line.strip()]
    refusals = [e for e in events if e["event"] == "autopublish_refused_internal_links"]
    assert refusals and refusals[-1]["slug"] == "esim-plans"
    assert any("internal links" in err for err in refusals[-1]["errors"])