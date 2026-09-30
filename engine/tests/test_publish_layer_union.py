"""Tests for the publish lane's two-layer `in_review` union (kanban t_e7d03242).

Regression target: `list_in_review()` read the PUBLISHED layer only. Strapi v5
creates a document in the DRAFT layer and every lane write since the 2026-09-22
write-layer fix (`StrapiClient.update_article` defaults `status="draft"`) stamps
that same working layer, so an article the 09:00 batch created was invisible to
the 13:00 lane (verified live 2026-09-25: published-layer `in_review` = 1 row,
draft layer = 40 rows over 21 documents). The union adds the draft layer and
reduces both to one row per documentId; every gate (quarantine, confidence,
already-published, ratified-E invariants) is unchanged.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import publish  # noqa: E402
from publish import list_in_review  # noqa: E402


class FakeClient:
    """Duck-typed Strapi client serving both draft&publish layers."""

    def __init__(self, published_rows=(), draft_rows=()):
        self.published_rows = list(published_rows)
        self.draft_rows = list(draft_rows)
        self.calls = []
        self.updates = []

    def _request(self, method, path, body=None, params=None):
        self.calls.append((method, path, params))
        if path != "/api/articles":
            return {"data": []}
        params = params or {}
        if params.get("status") == "draft":
            return {"data": self.draft_rows}
        return {"data": self.published_rows}

    def update_article(self, doc_id, fields, *, status="draft"):
        self.updates.append((doc_id, fields, status))

    def close(self):
        pass


def row(
    slug,
    doc_id,
    *,
    status="in_review",
    confidence=80,
    updated_at="2026-09-25T00:00:00.000Z",
    layer="",
    decision=None,
    body=None,
    excerpt="A short excerpt for the card.",
):
    """A Strapi v5 flat article row (only the fields the lane reads)."""
    a = {
        "slug": slug,
        "documentId": doc_id,
        "title": slug.replace("-", " ").title(),
        "status": status,
        "confidence": confidence,
        "updatedAt": updated_at,
        "layer": layer,  # test-only trace of which layer served this row
        "publishedAt": None,
        "bodyMarkdown": body
        or (
            "# Title\n\nBody content here.\n\n## Section\nSome text.\n"
            "https://irs.gov/one\nhttps://irs.gov/two\n"
        ),
        "excerpt": excerpt,
        "metaTitle": "A Meta Title",
        "metaDescription": (
            "Living costs, visa rules and internet speeds differ in every hub. "
            "This guide compares the practical numbers so you can pick a base "
            "before you book a flight."
        ),
        "focusKeyword": "travel",
    }
    if decision is not None:
        a["topicDecision"] = decision
    return a


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "PUBLISH_STATE_FILE", tmp_path / "publish-pipeline.jsonl")
    monkeypatch.setattr(publish, "SHARED_LEDGER", tmp_path / "publish-ledger.jsonl")
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", tmp_path / "pipeline.jsonl")
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", tmp_path / "release-approvals.jsonl")
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())


# --- the union ---------------------------------------------------------------

def test_list_in_review_queries_both_layers():
    client = FakeClient()
    list_in_review(client)  # type: ignore[arg-type]

    params = [c[2] for c in client.calls]
    assert params[0]["filters[status][$eq]"] == "in_review"  # published layer
    assert "status" not in params[0]
    assert params[1]["status"] == "draft"  # working layer
    assert params[1]["filters[status][$eq]"] == "in_review"


def test_list_in_review_returns_draft_layer_only_documents():
    """The 09-22 regression: a never-published document lives in the draft layer."""
    client = FakeClient(draft_rows=[row("draft-only", "d1", layer="draft")])

    out = list_in_review(client)  # type: ignore[arg-type]

    assert [a["slug"] for a in out] == ["draft-only"]


def test_list_in_review_dedupes_by_document_id_across_layers():
    """A document in both layers is returned once, as its in_review copy."""
    client = FakeClient(
        published_rows=[row("shared", "d1", layer="pub", updated_at="2026-09-20T13:00:00.000Z")],
        draft_rows=[
            row("shared", "d1", status="draft", layer="draft", updated_at="2026-09-24T17:00:00.000Z"),
            row("draft-only", "d2", layer="draft", confidence=76),
        ],
    )

    out = list_in_review(client)  # type: ignore[arg-type]
    by_slug = {a["slug"]: a for a in out}

    assert sorted(by_slug) == ["draft-only", "shared"]
    # the in_review copy outranks the stale mirror of the other layer
    assert by_slug["shared"]["layer"] == "pub"
    assert len(out) == len({a["documentId"] for a in out})  # no double-processing


def test_list_in_review_dedupes_duplicate_draft_rows_keeping_freshest():
    """Strapi returns duplicate rows per document (82 rows / 59 docs live); the
    freshest copy wins so the lane never ships a stale body."""
    stale = row("dup", "d1", layer="draft", updated_at="2026-09-19T11:15:29.000Z",
                body="# Old\n\nhttps://a.gov/x\nhttps://b.gov/y\n")
    fresh = row("dup", "d1", layer="draft", updated_at="2026-09-22T22:46:55.000Z")

    out = list_in_review(FakeClient(draft_rows=[stale, fresh]))  # type: ignore[arg-type]

    assert len(out) == 1
    assert out[0]["updatedAt"] == "2026-09-22T22:46:55.000Z"
    assert out[0]["bodyMarkdown"].startswith("# Title")


def test_list_in_review_is_confidence_sorted_and_capped():
    client = FakeClient(draft_rows=[
        row("low", "d1", confidence=60),
        row("mid", "d2", confidence=80),
        row("high", "d3", confidence=95),
    ])

    out = list_in_review(client, limit=2)  # type: ignore[arg-type]

    assert [a["slug"] for a in out] == ["high", "mid"]


# --- the gates still hold ----------------------------------------------------

def test_draft_layer_only_eligible_article_becomes_candidate():
    """A draft-layer-only, non-sensitive, conf>=75 article is now the candidate."""
    client = FakeClient(draft_rows=[row("travel-hacks", "d1", confidence=75, layer="draft")])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "dry_run"
    assert result["slug"] == "travel-hacks"
    assert result["confidence"] == 75


def test_draft_layer_only_quarantined_article_still_skips():
    client = FakeClient(draft_rows=[
        row("nomad-visa", "d1", confidence=95, decision="quarantine", layer="draft"),
    ])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    assert "quarantined (skipped)" in result["reason"]
    assert client.updates == []


def test_draft_layer_only_journal_quarantined_article_still_skips(tmp_path, monkeypatch):
    """Legacy protection survives the union: the journal join is keyed on
    documentId, so which layer served the row cannot bypass it."""
    jp = tmp_path / "pipeline.jsonl"
    jp.write_text(
        '{"event": "article_created", "articleDocumentId": "d1", "decision": "quarantine",'
        ' "slug": "legacy-tax"}\n'
    )
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", jp)
    client = FakeClient(draft_rows=[row("legacy-tax", "d1", confidence=99, layer="draft")])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    assert "quarantined (skipped)" in result["reason"]


def test_draft_layer_only_low_confidence_article_still_skips():
    client = FakeClient(draft_rows=[row("thin", "d1", confidence=74, layer="draft")])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    assert "no eligible" in result["reason"]


def test_draft_layer_only_already_published_article_still_skips(monkeypatch):
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: {"shipped"})
    client = FakeClient(draft_rows=[row("shipped", "d1", confidence=95, layer="draft")])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "skip"


def test_union_does_not_duplicate_slugs_in_skip_report():
    """The reason line names each skipped slug once, not per duplicate row."""
    client = FakeClient(draft_rows=[
        row("dup-quar", "d1", confidence=95, decision="quarantine"),
        row("dup-quar", "d1", confidence=95, decision="quarantine"),
    ])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    # the quarantined list names the slug once, not once per duplicate row
    quarantined = result["reason"].split("quarantined (skipped): ")[1].split(" · ")[0]
    assert quarantined.split(", ") == ["dup-quar"]


def test_skip_reason_names_invariant_blocked_candidates():
    """A visible, non-quarantined, high-confidence article that the ratified-E
    invariants reject is named in the skip line, with its failing invariant —
    otherwise the lane looks idle while it is actually blocked (t_e7d03242)."""
    client = FakeClient(draft_rows=[
        row("no-excerpt", "d1", confidence=87, layer="draft", excerpt="",
            body="# Title\n\nNo links here.\n"),
    ])

    result = publish.publish_one(client, None, dry_run=True)  # type: ignore[arg-type]

    assert result["event"] == "skip"
    blocked = result["reason"].split("invariant-blocked: ")[1]
    assert blocked.startswith("no-excerpt (")
    assert "empty excerpt" in blocked
    assert "fewer than 2 real citations" in blocked
