"""Which LAYER an article write lands on (kanban t_60ad2c8e).

`StrapiClient.update_article()` used to PUT with no `?status=`. On this Strapi
(v5, `api::article.article` with draftAndPublish: true) that write goes THROUGH
to the published layer and re-stamps `publishedAt`, so a code path meant to
"edit a draft" republished a live article with no human gate — the 2026-09-22
incident (documentId su1sx6rek6wnz7yfaayna7qh), same class as the 2026-08
quarantine leak.

Three layers of coverage here:
  1. the query param the client actually sends (default = draft, fail-safe);
  2. the CLI release path, which edits an ALREADY-PUBLISHED article;
  3. a live regression against the local Strapi (opt-in; see LIVE_ENV below).

The live test is opt-in because it writes: set NOMADOMICS_STRAPI_LIVE_TEST=1.
It creates a throwaway fixture article whose custom `status` enum stays "draft"
(so the frontend, which filters the published layer on that enum, never serves
it), publishes the fixture's own published layer to have something to protect,
asserts the default write leaves that layer byte-identical and the explicit
publish step does not, then removes the fixture. It never touches a real
article.

Cleanup note: the `engine-write` API token is least-privilege — find, findOne,
create, update on article/author/topic, and NO delete — so a fixture cannot be
removed through the REST API. The test therefore drops its own rows at the DB
level (psql + the repo's DATABASE_* creds) and SKIPS entirely when psql or those
creds are unavailable, rather than leaking rows into the content database.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config  # noqa: E402
from strapi import StrapiClient  # noqa: E402

LIVE_ENV = "NOMADOMICS_STRAPI_LIVE_TEST"


def make_cfg():
    return Config(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="key",
        first_n_human_review=3,
    )


# --- 1. the request the client sends -----------------------------------------

class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    @property
    def text(self):
        return json.dumps(self._payload)

    def json(self):
        return self._payload


class RecordingHTTP:
    """Captures the kwargs StrapiClient hands to httpx."""

    def __init__(self):
        self.calls = []

    def request(self, method, url, json=None, params=None):
        self.calls.append({"method": method, "url": url, "json": json, "params": params})
        return _Resp({"data": {"documentId": "doc-1"}})


def make_client():
    http = RecordingHTTP()
    return StrapiClient(make_cfg(), http_client=http), http


def test_default_write_targets_the_draft_layer():
    """Fail-safe default: no explicit status means `?status=draft`.

    Without the param Strapi writes through to the published layer, which is
    exactly how the incident shipped reviewed copy to the live page.
    """
    client, http = make_client()
    client.update_article("doc-1", {"bodyMarkdown": "edited"})
    call = http.calls[-1]
    assert call["method"] == "PUT"
    assert call["url"].endswith("/api/articles/doc-1")
    assert call["params"] == {"status": "draft"}
    assert call["json"] == {"data": {"bodyMarkdown": "edited"}}


def test_explicit_published_targets_the_published_layer():
    client, http = make_client()
    client.update_article("doc-1", {"status": "published"}, status="published")
    assert http.calls[-1]["params"] == {"status": "published"}


def test_status_none_omits_the_param_and_writes_through():
    """`None` is the historical (dangerous) behaviour, kept only as an explicit
    opt-in so a caller cannot reach it by accident."""
    client, http = make_client()
    client.update_article("doc-1", {"bodyMarkdown": "x"}, status=None)
    assert http.calls[-1]["params"] is None


def test_write_through_cannot_change_the_app_status():
    """A withdrawal is a DRAFT-layer write (t_8e96e368).

    Through a write-through PUT the same payload leaves the document published
    and re-stamps `publishedAt` — verified live 2026-10-07T08:11:06Z, the write
    meant to unpublish the Berlin article re-published it. Refuse the
    combination before any request instead.
    """
    client, http = make_client()
    with pytest.raises(ValueError):
        client.update_article("doc-1", {"status": "in_review"}, status=None)
    assert http.calls == []


def test_draft_layer_app_status_change_is_allowed():
    """The withdrawal path itself stays open: `?status=draft` (the default)."""
    client, http = make_client()
    client.update_article("doc-1", {"status": "in_review"}, status="draft")
    assert http.calls[-1]["params"] == {"status": "draft"}
    assert http.calls[-1]["json"] == {"data": {"status": "in_review"}}


def test_publishedat_in_the_payload_is_not_a_publish_mechanism():
    """v5 ignores an explicit `publishedAt` (the document service owns it), so a
    timestamp can never be restored by payload — only `status="published"`
    publishes. A payload carrying `publishedAt` must still send `?status=draft`.
    """
    client, http = make_client()
    client.update_article("doc-1", {"publishedAt": "2026-09-22T06:03:35.000Z"})
    assert http.calls[-1]["params"] == {"status": "draft"}


def test_unknown_status_is_rejected_before_any_request():
    client, http = make_client()
    with pytest.raises(ValueError):
        client.update_article("doc-1", {"bodyMarkdown": "x"}, status="publish")
    assert http.calls == []


# --- 2. the CLI release path (edits an already-published article) -------------

class ReleaseClient:
    """Duck-typed StrapiClient for `engine.cli publish --release <slug>`."""

    def __init__(self, article):
        self.article = article
        self.writes = []

    def get_topic_by_slug(self, slug):
        return {"documentId": "topic-1", "status": "published"}

    def _request(self, method, path, params=None, body=None):
        if path == "/api/articles":
            return {"data": [self.article]}
        return {"data": None}

    def update_article(self, doc_id, fields, *, status="draft"):
        self.writes.append({"doc_id": doc_id, "fields": fields, "status": status})
        return {"data": {"documentId": doc_id}}

    def close(self):
        pass


def test_cli_release_flip_writes_the_draft_layer_only(monkeypatch, tmp_path):
    """`publish --release` exists for articles that are ALREADY published, so a
    write-through would re-stamp publishedAt on a live page. The topicDecision
    flip must target the draft layer — while the human approval ledger is still
    recorded (the release authority is unchanged)."""
    import publish
    import pipeline_cli as cli

    article = {
        "documentId": "doc-q",
        "slug": "sensitive-topic",
        "topicDecision": "quarantine",
        "confidence": 90,
        "status": "published",
    }
    client = ReleaseClient(article)
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "StrapiClient", lambda cfg: client)
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", tmp_path / "release-approvals.jsonl")
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", tmp_path / "pipeline.jsonl")

    rc = cli.main(["publish", "--release", "sensitive-topic"])

    assert rc == 0
    assert [w["status"] for w in client.writes] == ["draft"]
    assert client.writes[0]["fields"] == {"topicDecision": "needs_review"}
    assert (tmp_path / "release-approvals.jsonl").exists()


# --- 3. live regression against the local Strapi -----------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]


def _live_client():
    from config import load_config

    cfg = load_config()
    client = StrapiClient(cfg)
    try:
        client._request("GET", "/api/articles", params={"pagination[pageSize]": 1})
    except Exception as e:  # noqa: BLE001
        client.close()
        pytest.skip(f"local Strapi not reachable: {e}")
    return client


def _layer(client, slug, layer):
    """Read one draft&publish layer (Strapi v5: `?status=draft|published`)."""
    rows = client._request(
        "GET",
        "/api/articles",
        params={
            "filters[slug][$eq]": slug,
            "status": layer,
            "pagination[pageSize]": 1,
        },
    ).get("data", [])
    assert rows, f"no {layer}-layer row for {slug}"
    return rows[0]


def _sha(text):
    return hashlib.sha256((text or "").encode()).hexdigest()


def _pg_env():
    """DATABASE_* values from the repo `.env`, used ONLY for fixture cleanup.

    Values are never printed or logged; a missing/partial config returns None so
    the caller can decline to write at all.
    """
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return None
    env: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    if env.get("DATABASE_CLIENT") != "postgres":
        return None
    if not all(env.get(k) for k in ("DATABASE_NAME", "DATABASE_USERNAME", "DATABASE_PASSWORD")):
        return None
    return env


def _cleanup_ready() -> bool:
    return shutil.which("psql") is not None and _pg_env() is not None


def _drop_document(document_id: str) -> bool:
    """Delete a fixture document (both layers) straight from Postgres.

    Needed because the engine token has no `delete` permission by design; in v5
    both layers are rows in `articles` sharing `document_id` (only
    `articles_author_lnk` references it, ON DELETE CASCADE).
    """
    if not document_id.isalnum():  # Strapi documentIds are [a-z0-9]
        raise ValueError("refusing to interpolate a non-alphanumeric documentId")
    env = _pg_env()
    if env is None or shutil.which("psql") is None:
        return False
    cmd = [
        "psql",
        "-h", env.get("DATABASE_HOST", "127.0.0.1"),
        "-p", env.get("DATABASE_PORT", "5432"),
        "-U", env["DATABASE_USERNAME"],
        "-d", env["DATABASE_NAME"],
        "-v", "ON_ERROR_STOP=1",
        "-c", f"delete from articles where document_id = '{document_id}';",
    ]
    done = subprocess.run(
        cmd,
        env={**os.environ, "PGPASSWORD": env["DATABASE_PASSWORD"]},
        capture_output=True,
        text=True,
    )
    return done.returncode == 0


@pytest.mark.skipif(
    os.environ.get(LIVE_ENV) != "1",
    reason=f"writes to the local Strapi; set {LIVE_ENV}=1 to run",
)
def test_put_default_leaves_the_published_layer_byte_identical():
    """The regression: editing a published article's draft must not change what
    is live. Includes a control that the explicit publish path DOES change the
    published layer, so the assertions cannot pass vacuously.
    """
    if not _cleanup_ready():
        pytest.skip(
            "no fixture cleanup path (engine token has no delete permission and "
            f"psql/DATABASE_* creds are unavailable) — refusing to write"
        )
    client = _live_client()
    stamp = f"{int(time.time())}-{os.getpid()}"
    slug = f"zz-layer-regression-{stamp}"  # never frontend-visible: enum stays draft
    published_body = f"# fixture {stamp}\n\nPUBLISHED layer body.\n"
    draft_body = f"# fixture {stamp}\n\nDRAFT layer edit.\n"
    doc_id = None
    try:
        created = client.create_article(
            {
                "title": f"ZZ Layer Regression {stamp}",
                "slug": slug,
                "status": "draft",
                "bodyMarkdown": published_body,
            }
        )
        doc_id = created["data"]["documentId"]
        # Give the fixture a published layer worth protecting.
        client.update_article(doc_id, {"bodyMarkdown": published_body}, status="published")

        before = _layer(client, slug, "published")
        assert before["bodyMarkdown"] == published_body
        before_published_at = before.get("publishedAt")
        assert before_published_at, "fixture published layer has no publishedAt"

        # ACT — the default call, i.e. the exact thing that used to leak.
        client.update_article(doc_id, {"bodyMarkdown": draft_body})

        after = _layer(client, slug, "published")
        assert _sha(after["bodyMarkdown"]) == _sha(published_body), (
            "published layer CHANGED: the default write went through"
        )
        assert after.get("publishedAt") == before_published_at, (
            "publishedAt re-stamped: the article was silently republished"
        )
        # …and the edit really landed, on the draft layer.
        assert _layer(client, slug, "draft")["bodyMarkdown"] == draft_body

        # CONTROL — the explicit publish step still writes the published layer.
        client.update_article(
            doc_id, {"bodyMarkdown": published_body + "CONTROL\n"}, status="published"
        )
        control = _layer(client, slug, "published")
        assert control["bodyMarkdown"] != published_body, (
            "control failed: status='published' did not reach the published layer"
        )
    finally:
        if doc_id:
            removed = _drop_document(doc_id)
            client.close()
            if not removed:
                raise RuntimeError(
                    f"fixture document {doc_id} (slug {slug}) was NOT removed — "
                    "delete it from Strapi/postgres by hand"
                )