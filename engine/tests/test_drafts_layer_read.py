"""`engine.cli drafts` must read the WORKING layer (kanban t_8f1614e2).

`StrapiClient.list_drafts()` asked for `filters[status][$in]=draft,in_review` but
never passed `?status=draft`, so Strapi v5 answered from the PUBLISHED layer: the
operator listing showed 3 rows where the draft layer held 40 (`in_review`) over
21 documents, and the layer its own writer (`update_article`, default
`status="draft"`) fills was invisible. The read path is now layer-explicit and
deduped, matching `publish.list_in_review()`.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config  # noqa: E402
from strapi import StrapiClient  # noqa: E402


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    @property
    def text(self):
        return json.dumps(self._payload)

    def json(self):
        return self._payload


class LayerHTTP:
    """Serves one canned page per draft&publish layer, recording the requests."""

    def __init__(self, published_rows=(), draft_rows=()):
        self.published_rows = list(published_rows)
        self.draft_rows = list(draft_rows)
        self.calls = []

    def request(self, method, url, json=None, params=None):
        self.calls.append({"method": method, "url": url, "params": params})
        params = params or {}
        rows = self.draft_rows if params.get("status") == "draft" else self.published_rows
        return _Resp({"data": rows, "meta": {"pagination": {"total": len(rows)}}})


def make_client(published_rows=(), draft_rows=()):
    cfg = Config(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="key",
        first_n_human_review=3,
    )
    http = LayerHTTP(published_rows, draft_rows)
    return StrapiClient(cfg, http_client=http), http


def row(
    slug,
    doc_id,
    *,
    status="in_review",
    created_at="2026-09-21T08:00:23.000Z",
    updated_at="2026-09-21T08:00:23.000Z",
    layer="",
):
    return {
        "slug": slug,
        "documentId": doc_id,
        "title": slug.replace("-", " ").title(),
        "status": status,
        "confidence": 80,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "layer": layer,  # test-only trace of which layer served this row
    }


# --- the request the client sends --------------------------------------------

def test_list_drafts_reads_the_working_layer():
    """Without `?status=draft` Strapi answers from the published layer, which is
    exactly how the backlog stayed invisible."""
    client, http = make_client()
    client.list_drafts()

    params = http.calls[-1]["params"]
    assert params["status"] == "draft"
    assert params["filters[status][$in][0]"] == "draft"
    assert params["filters[status][$in][1]"] == "in_review"


def test_list_drafts_asks_for_a_double_page_so_dedupe_cannot_starve_it():
    """The instance returns duplicate rows per document; a limit-sized page would
    spend half its budget on duplicates and hide real documents."""
    client, http = make_client()
    client.list_drafts(limit=10)

    assert http.calls[-1]["params"]["pagination[pageSize]"] == 20


# --- what comes back ---------------------------------------------------------

def test_list_drafts_returns_a_never_published_document():
    """The 09-22 regression: a document created by the batch lives only in the
    draft layer, so a published-layer read can never see it."""
    client, _ = make_client(draft_rows=[row("draft-only", "d1", layer="draft")])

    out = client.list_drafts()

    assert [a["slug"] for a in out] == ["draft-only"]


def test_list_drafts_dedupes_by_document_id_keeping_the_freshest_copy():
    stale = row("dup", "d1", updated_at="2026-09-19T11:15:29.000Z", layer="draft")
    fresh = row("dup", "d1", updated_at="2026-09-22T22:46:55.000Z", layer="draft")
    client, _ = make_client(draft_rows=[stale, fresh])

    out = client.list_drafts()

    assert len(out) == 1
    assert out[0]["updatedAt"] == "2026-09-22T22:46:55.000Z"


def test_list_drafts_is_newest_first_and_capped():
    client, _ = make_client(draft_rows=[
        row("older", "d1", created_at="2026-09-16T08:16:00.000Z"),
        row("newer", "d2", created_at="2026-09-21T08:00:23.000Z"),
        row("middle", "d3", created_at="2026-09-18T10:00:00.000Z"),
    ])

    out = client.list_drafts(limit=2)

    assert [a["slug"] for a in out] == ["newer", "middle"]


def test_list_drafts_skips_rows_without_a_document_id():
    client, _ = make_client(draft_rows=[
        {"slug": "orphan", "status": "in_review"},
        row("ok", "d1"),
    ])

    assert [a["slug"] for a in client.list_drafts()] == ["ok"]


def test_published_layer_relic_does_not_hide_the_draft_backlog():
    """Live shape of the bug: the published layer held ONE stale in_review relic
    (fbar) while the draft layer held the 40-row backlog. A layer-explicit read
    returns the backlog, not the relic."""
    client, http = make_client(
        published_rows=[row("fbar-fatca-guide-digital-nomads", "relic-1", layer="pub")],
        draft_rows=[row(f"draft-{i}", f"d{i}", layer="draft") for i in range(5)],
    )

    out = client.list_drafts()

    assert len(out) == 5
    assert "fbar-fatca-guide-digital-nomads" not in {a["slug"] for a in out}
    assert [a["slug"] for a in out if a.get("layer") == "pub"] == []


# --- the CLI surface ---------------------------------------------------------

def test_cli_drafts_prints_the_working_layer(monkeypatch, capsys):
    import pipeline_cli as cli

    client, _ = make_client(
        published_rows=[row("pub-relic", "d1", layer="pub")],
        draft_rows=[row("draft-a", "d2", layer="draft"), row("draft-b", "d3", layer="draft")],
    )
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "StrapiClient", lambda cfg: client)

    rc = cli.main(["drafts"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "2 draft/in-review article(s)" in out
    assert "Draft A" in out and "Draft B" in out
    assert "Pub Relic" not in out
