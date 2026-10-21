"""Tests for the quarantine-class disclaimer invariant (t_d0608cc0).

A quarantine-class article (topicDecision=quarantine, or journal quarantine
joined by documentId) must carry a standard tax/legal disclaimer — an
explicit not-advice clause ("not legal/tax/financial advice") AND a
consult-a-qualified-professional clause — before the publish lane passes it.
Non-quarantine articles stay disclaimer-optional: the general lane is
unchanged.

Covers:
  * the disclaimer patterns themselves ("acceptable phrasings" contract)
  * disclaimer_issues (named missing-clause errors)
  * article_invariant_errors(quarantined=...) wiring + '-only' rows
  * disclaimer_gate_class membership semantics (no release-approval exemption)
  * publish_one end-to-end: released quarantine-class article without the
    disclaimer is invariant-blocked; with the disclaimer it flows through.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import publish  # noqa: E402
from invariants import disclaimer_issues, article_invariant_errors  # noqa: E402
from publish import disclaimer_gate_class, is_quarantined, publish_one  # noqa: E402

# Keep the published-lane harness isolated the way test_quarantine_gate does.
# Monkeypatched state files + _published_slugs (all three journals/locks live)
# + a read-only in-memory client.
from test_quarantine_gate import FakeClient, make_article  # noqa: E402


# --- disclaimer pattern contract -------------------------------------------

def _body(text: str) -> str:
    return f"# Tax Article\n\n{text}\n\n## Sources\n\n- [IRS](https://irs.gov/one)\n- [IRS two](https://irs.gov/two)\n"


def test_disclaimer_issues_names_both_missing_clauses():
    errors = disclaimer_issues(_body("Body text with no disclaimer at all."))
    assert len(errors) == 1
    assert "not legal/tax/financial advice" in errors[0]
    assert "consult a qualified professional" in errors[0]


def test_disclaimer_issues_passes_when_both_clauses_present():
    body = _body(
        "This article is for general information only and is not legal, tax, or "
        "financial advice. Consult a qualified professional for your "
        "jurisdiction before acting on anything here."
    )
    assert disclaimer_issues(body) == []


def test_disclaimer_issues_accepts_reasonable_phrasings():
    # Alternate negations + consult verbs + qualifiers all count.
    cases = [
        "Not financial advice — talk to a licensed tax adviser with any "
        "questions.",
        "This article does not constitute tax, legal, or financial advice. "
        "Seek professional advice from a qualified expert.",
        "This is not legal advice. Speak with your tax professional.",
    ]
    for text in cases:
        assert disclaimer_issues(_body(text)) == [], f"failed: {text!r}"


def test_disclaimer_issues_does_not_count_partial_clauses():
    # "consult" alone, or "professional" alone, is not the contract — both
    # clauses are required.
    body = _body("Consult a professional before acting on this information.")
    errors = disclaimer_issues(body)
    assert len(errors) == 1
    assert "not legal/tax/financial advice" in errors[0]


# --- article_invariant_errors wiring --------------------------------------

def test_general_lane_stays_disclaimer_optional():
    a = make_article(slug="general-travel", confidence=87, decision="needs_review")
    plain = article_invariant_errors(a)
    flagged = article_invariant_errors(a, quarantined=True)
    # The general lane must never start complaining about a disclaimer.
    assert "disclaimer" not in plain
    # The quarantine-class variant still names the missing clause.
    assert any("disclaimer" in e for e in flagged)


def test_quarantined_article_without_disclaimer_fails():
    a = make_article(slug="quarantine-tax", confidence=92, decision="quarantine")
    assert article_invariant_errors(a, quarantined=True) == [
        "quarantine-class body missing required disclaimer clause(s): "
        "'not legal/tax/financial advice'; 'consult a qualified professional'"
    ]


def test_quarantined_article_with_disclaimer_passes():
    body = _body(
        "This article is for general information only and is not legal, tax, or "
        "financial advice. Consult a qualified professional for your "
        "jurisdiction before acting on anything here."
    )
    a = make_article(slug="disclaimed-tax", confidence=92, decision="quarantine")
    a["bodyMarkdown"] = body
    assert article_invariant_errors(a, quarantined=True) == []


# --- disclaimer_gate_class membership ---------------------------------------

@pytest.mark.parametrize(
    "decision,journal,doc_id,expected",
    [
        ("quarantine", None, "doc-q", True),                       # field
        ("needs_review", {"doc-file"}, "doc-file", True),          # journal
        ("unknown", set(), "doc-x", False),                        # nothing
        ("unknown", {"doc-journal"}, "doc-journal", True),         # released via journal join
        ("quarantine", {"doc-q"}, "doc-q", True),                  # approvals must NOT exempt
    ],
)
def test_disclaimer_gate_class(decision, journal, doc_id, expected):
    a = make_article(slug="gate-fault", confidence=87, decision=decision,
                     doc_id=doc_id)
    if journal is None:
        journal = set()
    assert disclaimer_gate_class(a, journal) is expected


@pytest.mark.parametrize(
    "decision,approvals,journal,expected",
    [
        ("quarantine", {"doc-approvals"}, None, True),   # approvals must NOT waive the disclaimer
        ("quarantine", {"doc-approvals"}, {"doc-file"}, True),
        ("needs_review", set(), None, False),
    ],
)
def test_disclaimer_gate_class_versus_is_quarantined(decision, approvals, journal, expected, tmp_path, monkeypatch):
    from publish import release_approved_docids, is_quarantined

    a = make_article(slug="gate-2", confidence=87, decision=decision, doc_id="doc-1")
    journal = journal or set()
    # Mirror the real release ledger (the --release path writes this file).
    (tmp_path / "release-approvals.jsonl").write_text(
        "\n".join(
            json.dumps({"ts": "2026-10-21T00:00:00Z", "slug": a["slug"],
                        "articleDocumentId": a["documentId"], "source": "cli-release"})
            for _ in approvals
        ) + "\n" if approvals else "")
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", tmp_path / "release-approvals.jsonl")

    assert disclaimer_gate_class(a, journal) is expected


def test_disclaimer_gate_class_survives_release_approval(tmp_path, monkeypatch):
    """The disclaimer invariant does NOT waive on release: the 13:00 lane
    refuses a quarantine-class article even when a human approval ledger
    marks it released (is_quarantined() would exempt it)."""
    from publish import release_approved_docids, is_quarantined

    a = make_article(slug="gate-field", confidence=87, decision="quarantine",
                     doc_id="doc-field")
    (tmp_path / "release-approvals.jsonl").write_text(
        json.dumps({"ts": "2026-10-21T00:00:00Z", "slug": a["slug"],
                    "articleDocumentId": a["documentId"], "source": "cli-release"})
        + "\n")
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", tmp_path / "release-approvals.jsonl")

    assert disclaimer_gate_class(a, set()) is True
    # is_quarantined() exempts exactly this case — the contrast is the point.
    assert is_quarantined(a, set(), release_approved_docids()) is False


# --- publish_one end-to-end -------------------------------------------------
# Released (approval-recorded) quarantine-class articles are un-gated by
# is_quarantined, so the disclaimer invariant is the only thing standing between
# such an article and the 13:00 lane. These pin the fail-closed handling.

def _released_quarantine_article(doc_id="rel-doc", decision="quarantine"):
    return make_article(slug="rel-tax", confidence=92, decision=decision,
                        doc_id=doc_id)


def test_release_approval_does_not_waive_the_disclaimer(tmp_path, monkeypatch):
    """A quarantine-class article (field OR journal) that is approval-released
    WITHOUT the disclaimer must be invariant-blocked — the 13:00 lane refuses it."""
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", tmp_path / "pipeline.jsonl")
    (tmp_path / "pipeline.jsonl").write_text(
        json.dumps({"event": "article_created", "articleDocumentId": "rel-doc",
                    "decision": "quarantine", "slug": "rel-tax"}) + "\n")
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", tmp_path / "release-approvals.jsonl")
    (tmp_path / "release-approvals.jsonl").write_text(
        json.dumps({"ts": "2026-10-21T00:00:00Z", "slug": "rel-tax",
                    "articleDocumentId": "rel-doc", "source": "cli-release"}) + "\n")
    monkeypatch.setattr(publish, "browser_asset_ready", lambda s: (True, "fixture receipt"))
    client = FakeClient([_released_quarantine_article()])

    result = publish_one(client, None, dry_run=True)

    assert result["event"] == "skip"
    assert "invariant-blocked" in result["reason"]
    assert "disclaimer" in result["reason"]


def test_release_approval_with_disclaimer_passes_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", tmp_path / "pipeline.jsonl")
    (tmp_path / "pipeline.jsonl").write_text(
        json.dumps({"event": "article_created", "articleDocumentId": "rel-doc",
                    "decision": "quarantine", "slug": "rel-tax"}) + "\n")
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", tmp_path / "release-approvals.jsonl")
    (tmp_path / "release-approvals.jsonl").write_text(
        json.dumps({"ts": "2026-10-21T00:00:00Z", "slug": "rel-tax",
                    "articleDocumentId": "rel-doc", "source": "cli-release"}) + "\n")
    monkeypatch.setattr(publish, "browser_asset_ready", lambda s: (True, "fixture receipt"))
    client = FakeClient([_released_quarantine_article()])

    body = "\n\n".join([
        "This article is for general information only and is not legal, tax, or "
        "financial advice. Consult a qualified professional for your "
        "jurisdiction before acting on anything here.",
        _body("Body content here. Read [related guidance](/best-esim-plans-for-digital-nomads) "
              "and the [tax primer](/digital-nomad-taxes)."),
    ])
    client.articles[0]["bodyMarkdown"] = body

    result = publish_one(client, None, dry_run=True)

    assert result["event"] == "dry_run"
    assert result["slug"] == "rel-tax"
