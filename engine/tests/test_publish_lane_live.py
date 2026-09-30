"""Live acceptance for the publish lane: it must EXECUTE, not just skip.

Opt-in — it writes to the local Strapi (the engine's own test environment):
    NOMADOMICS_STRAPI_LIVE_TEST=1 pytest engine/tests/test_publish_lane_live.py

What it proves (kanban t_8f1614e2, P1 of the PANT-173 chain): with the
draft-layer union in `publish.list_in_review()` and the ratified-E gates intact,
`publish.publish_one()` really publishes — candidate selection, the
`status="published"` write to the published layer, and the read-back.

Safety, because this runs against the real content database:

* the fixture is a throwaway document created in the DRAFT layer with app status
  `in_review` (the only status the lane selects) and two real citations, so it is
  the lane's top candidate;
* the run ABORTS before publishing unless the dry run selects the fixture, so a
  production article can never be shipped by this test;
* the quarantine journal and the release ledger are the REAL files (copied), not
  empty ones — an empty journal silently un-quarantines every legacy row;
* the publish ledgers are redirected to tmp, so the fixture is not recorded as
  "today's publish" and the 13:00 cron is not suppressed;
* `skip_image=True, no_commit=True` keeps cover art and the git/Vercel push out;
* the fixture rows are deleted from Postgres afterwards (the engine token has no
  delete permission by design).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_ENV = "NOMADOMICS_STRAPI_LIVE_TEST"


def _strapi_reachable():
    from config import load_config
    from strapi import StrapiClient

    client = StrapiClient(load_config())
    try:
        client._request("GET", "/api/articles", params={"pagination[pageSize]": 1})
    except Exception as e:  # noqa: BLE001
        client.close()
        pytest.skip(f"local Strapi not reachable: {e}")
    return client


def _pg_env():
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
    if env.get("DATABASE_CLIENT") != "postgres" or not all(
        env.get(k) for k in ("DATABASE_NAME", "DATABASE_USERNAME", "DATABASE_PASSWORD")
    ):
        return None
    return env


def _drop_document(document_id: str) -> bool:
    if not document_id.isalnum():
        raise ValueError("refusing to interpolate a non-alphanumeric documentId")
    env = _pg_env()
    if env is None or shutil.which("psql") is None:
        return False
    cmd = [
        "psql", "-h", env.get("DATABASE_HOST", "127.0.0.1"),
        "-p", env.get("DATABASE_PORT", "5432"), "-U", env["DATABASE_USERNAME"],
        "-d", env["DATABASE_NAME"], "-v", "ON_ERROR_STOP=1",
        "-c", f"delete from articles where document_id = '{document_id}';",
    ]
    done = subprocess.run(
        cmd, env={**os.environ, "PGPASSWORD": env["DATABASE_PASSWORD"]},
        capture_output=True, text=True,
    )
    return done.returncode == 0


def _published_layer(client, slug):
    rows = client._request(
        "GET", "/api/articles",
        params={"filters[slug][$eq]": slug, "status": "published", "pagination[pageSize]": 1},
    ).get("data", [])
    return rows[0] if rows else None


@pytest.mark.skipif(
    os.environ.get(LIVE_ENV) != "1",
    reason=f"publishes a throwaway fixture to the local Strapi; set {LIVE_ENV}=1 to run",
)
def test_publish_one_publishes_a_draft_layer_candidate(monkeypatch, tmp_path):
    import publish

    if _pg_env() is None or shutil.which("psql") is None:
        pytest.skip("no fixture cleanup path (psql/DATABASE_* creds unavailable) — refusing to write")
    from config import load_config

    cfg = load_config()
    client = _strapi_reachable()
    stamp = f"{int(time.time())}"
    slug = f"zz-publish-acceptance-{stamp}"
    doc_id = None

    # Ledgers redirected so the fixture can never be recorded as "today's
    # publish" (which would make the 13:00 lane skip the rest of the day). The
    # quarantine journal and release ledger deliberately stay REAL: an empty
    # journal silently un-quarantines every legacy row (2026-09-25: a harness
    # with an empty journal published the quarantined fbar-fatca-guide article;
    # it was reverted row-for-row from the 03:00 backup).
    monkeypatch.setattr(publish, "PUBLISH_STATE_FILE", tmp_path / "publish-pipeline.jsonl")
    monkeypatch.setattr(publish, "SHARED_LEDGER", tmp_path / "publish-ledger.jsonl")
    assert publish.journal_quarantined_docids(), "quarantine journal did not load — refusing to run"

    try:
        created = client.create_article({
            "title": f"ZZ Publish Acceptance {stamp}",
            "slug": slug,
            "status": "in_review",  # the app status the lane selects
            "topicDecision": "needs_review",
            "confidence": 99,  # top of the queue, so the fixture is the candidate
            "focusKeyword": "publish acceptance",
            "excerpt": "A throwaway fixture used to prove the publish lane executes.",
            "metaTitle": f"ZZ Publish Acceptance {stamp}",
            "metaDescription": (
                "A throwaway fixture used to prove the publish lane executes. "
                "This longer copy satisfies the meta-shape invariants so the "
                "lane reaches the publish step."
            ),
            "bodyMarkdown": (
                f"# ZZ Publish Acceptance {stamp}\n\n"
                "Fixture body with two verifiable citations.\n\n"
                "https://www.irs.gov/individuals/international-taxpayers\n"
                "https://travel.state.gov/content/travel.html\n"
            ),
        })
        doc_id = created["data"]["documentId"]

        # 1. the union makes the draft-layer fixture visible
        visible = {a.get("slug") for a in publish.list_in_review(client)}
        assert slug in visible, "the lane cannot see a draft-layer in_review article"

        # 2. the dry run must select the fixture — otherwise ABORT (no publish)
        dry = publish.publish_one(client, cfg, dry_run=True, skip_image=True, no_commit=True)
        assert dry.get("slug") == slug, (
            f"refusing to publish: the lane selected {dry.get('slug')!r}, not the fixture"
        )

        # 3. the real publish write
        result = publish.publish_one(client, cfg, dry_run=False, skip_image=True, no_commit=True)
        assert result.get("event") == "published"
        assert result.get("slug") == slug

        # 4. read the published layer back
        row = _published_layer(client, slug)
        assert row is not None, "the published layer has no row for the fixture"
        assert row.get("status") == "published"
        assert row.get("publishedAt")
    finally:
        if doc_id:
            removed = _drop_document(doc_id)
            client.close()
            if not removed:
                raise RuntimeError(
                    f"fixture document {doc_id} (slug {slug}) was NOT removed — "
                    "delete it from Strapi/postgres by hand"
                )
