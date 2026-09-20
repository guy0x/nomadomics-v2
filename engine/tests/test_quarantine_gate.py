"""Tests for the publish-lane quarantine gate (finding t_cae3c2d2).

Regression target: the daily publish lane published articles the draft lane had
explicitly quarantined (decision=quarantine for sensitive topics). The gate now
skips quarantine-class articles in candidate selection AND hard-refuses one that
reaches the publish step, while a missing topicDecision ('unknown') keeps the
legacy in_review+confidence behavior so pre-gate articles are not starved.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import publish  # noqa: E402
from publish import article_decision, is_quarantined  # noqa: E402


class FakeClient:
    """Minimal duck-typed Strapi agent for publish_one's interactions."""

    def __init__(self, articles):
        self.articles = articles  # list of article dicts (Strapi v5 flat shape)
        self.published_rows = []
        self.updates = []
        self.publish_state = []  # content of publish-pipeline.jsonl (via monkeypatch)
        self.calls = []

    def _request(self, method, path, params=None, body=None):
        self.calls.append((method, path, params))
        if path == "/api/articles" and params and params.get("filters[status][$eq]") == "in_review":
            return {"data": self.articles}
        if path == "/api/articles" and params and params.get("filters[status][$eq]") == "published":
            return {"data": [a for a in self.articles if a.get("status") == "published"]}
        return {"data": []}

    def update_article(self, doc_id, fields):
        self.updates.append((doc_id, fields))

    def close(self):
        pass


def make_article(
    slug="tax-article",
    confidence=87,
    status="in_review",
    decision=None,
    title="Tax Article",
    doc_id="doc-1",
):
    a = {
        "slug": slug,
        "documentId": doc_id,
        "title": title,
        "confidence": confidence,
        "status": status,
        "bodyMarkdown": "# Title\n\nBody content here.\n\n## Section\nSome text.\n",
        "focusKeyword": "taxes",
    }
    if decision is not None:
        a["topicDecision"] = decision
    return a


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "PUBLISH_STATE_FILE", tmp_path / "publish-pipeline.jsonl")
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", tmp_path / "pipeline.jsonl")
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", tmp_path / "release-approvals.jsonl")
    monkeypatch.setattr(publish, "SNAPSHOT", tmp_path / "published-slugs.json")
    monkeypatch.setattr(publish, "PUBLIC_CARDS", tmp_path / "cards")
    monkeypatch.setattr(publish, "PUBLIC_OG", tmp_path / "og")


# --- decision helpers --------------------------------------------------------

def test_article_decision_reads_field():
    assert article_decision(make_article(decision="quarantine")) == "quarantine"
    assert article_decision(make_article(decision="needs_review")) == "needs_review"


def test_article_decision_missing_is_unknown():
    assert article_decision(make_article()) == "unknown"


def test_article_decision_normalizes_case_and_whitespace():
    assert article_decision(make_article(decision=" Quarantine ")) == "quarantine"


def test_is_quarantined_only_quarantine():
    assert is_quarantined(make_article(decision="quarantine")) is True
    assert is_quarantined(make_article(decision="needs_review")) is False
    assert is_quarantined(make_article()) is False  # missing = not quarantined


# --- candidate selection -----------------------------------------------------

def test_quarantined_high_confidence_article_is_skipped(monkeypatch):
    """A quarantine-class article must NOT be the winner, even at conf 99."""
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())
    client = FakeClient([make_article(decision="quarantine", confidence=99)])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    assert "quarantined (skipped)" in result["reason"]
    assert client.updates == []  # nothing was written
    # only a read happened (the in_review listing); no write/update calls
    assert all(method == "GET" for method, _, _ in client.calls)


def test_quarantined_does_not_block_other_eligible_article(monkeypatch, tmp_path):
    """A quarantined high-confidence article is skipped, a healthy one wins."""
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())
    client = FakeClient([
        make_article(slug="quar-tax", decision="quarantine", confidence=99),
        make_article(slug="healthy-travel", decision="needs_review", confidence=88),
    ])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "dry_run"
    assert result["slug"] == "healthy-travel"
    assert result["confidence"] == 88


def test_hard_refuse_if_quarantined_article_reaches_publish_step():
    """Even if a quarantine-class article is selected (legacy/concurrent race),
    publish_one must refuse to ship it and make no writes."""
    refused = publish._hard_refuse_if_quarantined(make_article(decision="quarantine"))
    assert refused is not None
    assert refused["event"] == "skip"
    assert "quarantined" in refused["reason"]

    # And a non-quarantine article passes the guard.
    assert publish._hard_refuse_if_quarantined(make_article(decision="needs_review")) is None
    assert publish._hard_refuse_if_quarantined(make_article()) is None  # unknown is fine


def test_unknown_decision_keeps_legacy_behavior(monkeypatch):
    """Pre-gate articles (no topicDecision) remain publishable if conf >= 75."""
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())
    client = FakeClient([make_article(decision=None, confidence=87)])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "dry_run"
    assert result["slug"] == "tax-article"


def test_low_confidence_still_skips(monkeypatch):
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())
    client = FakeClient([make_article(decision="needs_review", confidence=67)])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    assert "no eligible" in result["reason"]


# --- legacy protection: the draft journal join (t_cae3c2d2) ------------------

def _write_journal(tmp_path, rows):
    """Write DRAFT_JOURNAL rows: list of (docid, decision) article_created pairs."""
    path = tmp_path / "pipeline.jsonl"
    lines = []
    for docid, decision, slug in rows:
        lines.append(json.dumps({
            "event": "article_created", "articleDocumentId": docid,
            "decision": decision, "slug": slug,
        }))
    path.write_text("\n".join(lines) + "\n")
    return path


def test_journal_loads_quarantined_docids(tmp_path, monkeypatch):
    p = _write_journal(tmp_path, [
        ("doc-tax", "quarantine", "tax-article"),
        ("doc-health", "needs_review", "travel-insurance"),
        ("doc-other", "quarantine", "unrelated"),
    ])
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", p)

    assert publish.journal_quarantined_docids() == {"doc-tax", "doc-other"}


def test_journal_missing_file_is_empty_set(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", tmp_path / "no-such-file.jsonl")
    assert publish.journal_quarantined_docids() == set()


def test_legacy_quarantined_article_skipped_via_journal(monkeypatch, tmp_path):
    """Pre-topicDecision articles are protected by the draft journal join."""
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())
    jp = _write_journal(tmp_path, [("legacy-tax-doc", "quarantine", "legacy-tax")])
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", jp)
    # No topicDecision field (legacy shape).
    client = FakeClient([make_article(slug="legacy-tax", decision=None,
                                      confidence=99, doc_id="legacy-tax-doc")])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    assert "quarantined (skipped)" in result["reason"]


def test_legacy_non_quarantined_still_eligible(monkeypatch, tmp_path):
    """A legacy article NOT in the journal's quarantine set keeps legacy behavior."""
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())
    jp = _write_journal(tmp_path, [("legacy-health-doc", "needs_review", "insurance")])
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", jp)
    client = FakeClient([make_article(slug="insurance", decision=None,
                                      confidence=88, doc_id="legacy-health-doc")])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "dry_run"
    assert result["slug"] == "insurance"


def test_hard_refuse_uses_journal_too(tmp_path, monkeypatch):
    jp = _write_journal(tmp_path, [("legacy-tax-doc", "quarantine", "legacy-tax")])
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", jp)
    journal = publish.journal_quarantined_docids()
    refused = publish._hard_refuse_if_quarantined(
        make_article(slug="legacy-tax", decision=None, doc_id="legacy-tax-doc"), journal)
    assert refused is not None
    assert refused["event"] == "skip"


# --- explicit human release override (--release + release-approvals.jsonl) ---

def test_release_approval_overrides_field_and_journal(tmp_path, monkeypatch):
    """A documentId in the approval ledger is exempt from quarantine entirely."""
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())
    # Both signals say quarantine: server field AND journal record.
    jp = _write_journal(tmp_path, [("rel-tax-doc", "quarantine", "rel-tax")])
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", jp)
    # Approval ledger marks it released.
    ap = tmp_path / "release-approvals.jsonl"
    ap.write_text(json.dumps({"ts": "2026-09-20T00:00:00Z",
                              "slug": "rel-tax", "articleDocumentId": "rel-tax-doc",
                              "source": "cli-release"}) + "\n")
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", ap)
    client = FakeClient([make_article(slug="rel-tax", decision="quarantine",
                                      confidence=88, doc_id="rel-tax-doc")])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "dry_run"
    assert result["slug"] == "rel-tax"  # released -> eligible again


def test_release_approval_record_writes_ledger(tmp_path, monkeypatch):
    ap = tmp_path / "release-approvals.jsonl"
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", ap)

    ok = publish.record_release_approval(make_article(slug="x", doc_id="doc-x"),
                                         source="test")
    assert ok is True
    lines = ap.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["slug"] == "x"
    assert rec["articleDocumentId"] == "doc-x"
    assert rec["source"] == "test"
    assert "ts" in rec


# --- CLI release branch: journal-only quarantine must be releasable ---------

def test_cli_release_journal_only_quarantine(tmp_path, monkeypatch, capsys, mocker=None):
    """A legacy article (no server field) recorded quarantine in the journal can
    be released: the approval ledger is written and the message says released
    via journal join. Mirrors the publish gate (field OR journal)."""
    from engine import pipeline_cli as cli

    jp = _write_journal(tmp_path, [("leg-doc", "quarantine", "legacy-slug")])
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", jp)
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", tmp_path / "release-approvals.jsonl")

    legacy = {
        "documentId": "leg-doc",
        "slug": "legacy-slug",
        "title": "Legacy Tax Article",
        "status": "in_review",
        "confidence": 88,
    }
    calls = []

    class DummyClient:
        def get_topic_by_slug(self, slug):
            return {"attributes": {"slug": slug, "status": "in_review"}}
        def _request(self, method, path, params=None, **kw):
            calls.append((method, path, params))
            if params and params.get("filters[slug][$eq]") == "legacy-slug":
                return {"data": [legacy]}
            return {"data": []}
        def update_article(self, doc_id, data, **kw):
            calls.append(("PUT", doc_id, data))
            return {"data": {"documentId": doc_id}}
        def close(self):
            pass

    monkeypatch.setattr(cli, "StrapiClient", lambda cfg: DummyClient())

    rc = cli.main(["publish", "--release", "legacy-slug"])
    out = capsys.readouterr()
    assert rc == 0
    assert "approved for release" in out.out
    assert "journal join" in out.out
    # No server-side field flip happened (field was unknown, not quarantine).
    assert not any(c[0] == "PUT" for c in calls)
    # Ledger written.
    lines = (tmp_path / "release-approvals.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["articleDocumentId"] == "leg-doc"
