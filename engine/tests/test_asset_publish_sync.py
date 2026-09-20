"""Tests for cover-art shipping + live verification (kanban t_69dcb49a).

Regression target: commit_assets() committed the cover art but nothing pushed it,
and the post-publish live check asserted ONLY the article page — so the lane
reported `live: true`, exit 0, for a page whose card/og art 404'd because its
commit never reached origin/main (Vercel deploys from git pushes). Measured live
2026-09-20: /cost-of-living-chiang-mai 200 while cards/ and og/ .png were 404 on
commit 4524ded (local main ahead 2, origin/main 7b5a641).

The fix: the push lives next to the commit (every publish path ships), the asset
URLs are asserted after the page with a bounded retry for deploy lag, and a
publish that is not fully live exits non-zero.
"""
import sys
import subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import publish  # noqa: E402
from publish import pending_asset_commits, push_assets, verify_assets_live  # noqa: E402

SITE = "https://nomadomics-v2.vercel.app"
SLUG = "cost-of-living-chiang-mai"


def _cp(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["git"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


# --- pending_asset_commits ---------------------------------------------------

def test_pending_asset_commits_counts_local_ahead(monkeypatch):
    monkeypatch.setattr(publish.subprocess, "run", lambda *a, **k: _cp(stdout="2\n"))
    assert pending_asset_commits() == 2


def test_pending_asset_commits_zero_when_synced(monkeypatch):
    monkeypatch.setattr(publish.subprocess, "run", lambda *a, **k: _cp(stdout="0\n"))
    assert pending_asset_commits() == 0


def test_pending_asset_commits_unknown_on_git_error(monkeypatch):
    def boom(*a, **k):
        raise subprocess.CalledProcessError(128, "git")
    monkeypatch.setattr(publish.subprocess, "run", boom)
    assert pending_asset_commits() == -1


# --- push_assets -------------------------------------------------------------

def test_push_assets_noop_when_origin_up_to_date(monkeypatch):
    calls = []
    monkeypatch.setattr(publish, "pending_asset_commits", lambda: 0)
    monkeypatch.setattr(publish.subprocess, "run", lambda *a, **k: calls.append(a) or _cp())
    ok, detail = push_assets()
    assert ok is True
    assert "nothing to push" in detail
    assert calls == []  # never shells out git push when there is nothing to ship


def test_push_assets_ships_pending_commits(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["timeout"] = kwargs.get("timeout")
        return _cp(stdout="To github.com:guy0x/nomadomics-v2.git\n   7b5a641..4524ded  main -> main\n")

    monkeypatch.setattr(publish, "pending_asset_commits", lambda: 2)
    monkeypatch.setattr(publish.subprocess, "run", fake_run)
    ok, detail = push_assets()
    assert ok is True
    assert detail == "pushed 2 commit(s)"
    assert seen["cmd"] == ["git", "push", "origin", "main"]
    assert seen["timeout"] == publish.PUSH_TIMEOUT_SECONDS  # bounded, never unbounded


def test_push_assets_reports_failure_instead_of_swallowing(monkeypatch):
    monkeypatch.setattr(publish, "pending_asset_commits", lambda: 1)
    monkeypatch.setattr(
        publish.subprocess, "run",
        lambda *a, **k: _cp(stderr="remote: Permission denied\n", returncode=128),
    )
    ok, detail = push_assets()
    assert ok is False
    assert "Permission denied" in detail


def test_push_assets_reports_timeout(monkeypatch):
    def wedged(*a, **k):
        raise subprocess.TimeoutExpired("git push", publish.PUSH_TIMEOUT_SECONDS)
    monkeypatch.setattr(publish, "pending_asset_commits", lambda: 1)
    monkeypatch.setattr(publish.subprocess, "run", wedged)
    ok, detail = push_assets()
    assert ok is False
    assert "timed out" in detail


# --- verify_assets_live ------------------------------------------------------

class FakeHttp:
    """Serves a scripted status per URL, then repeats the last one."""

    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.hits = []

    def __call__(self, url, **kwargs):
        self.hits.append(url)
        for kind, codes in self.script.items():
            if url.endswith(f"/{kind}/{SLUG}.png"):
                code = codes.pop(0) if len(codes) > 1 else codes[0]
                return type("R", (), {"status_code": code})()
        return type("R", (), {"status_code": 404})()


def test_verify_assets_live_retries_past_deploy_lag(monkeypatch):
    """A just-pushed card can 404 for a moment while Vercel builds: retry, then pass."""
    fake = FakeHttp({"cards": [404, 200], "og": [200]})
    monkeypatch.setattr(publish.httpx, "get", fake)
    out = verify_assets_live(SLUG, SITE, attempts=3, delay=0)
    assert out["assetsLive"] is True
    assert out["assetAttempts"] == 2
    assert out["assetStatus"] == {"cards": 200, "og": 200}


def test_verify_assets_live_true_miss_is_not_masked(monkeypatch):
    """Art that never lands stays a failure — retries must not fake a pass."""
    fake = FakeHttp({"cards": [404], "og": [404]})
    monkeypatch.setattr(publish.httpx, "get", fake)
    out = verify_assets_live(SLUG, SITE, attempts=2, delay=0)
    assert out["assetsLive"] is False
    assert out["assetAttempts"] == 2
    assert out["assetStatus"] == {"cards": 404, "og": 404}


def test_verify_assets_live_network_error_counts_as_not_live(monkeypatch):
    def dead(url, **kwargs):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(publish.httpx, "get", dead)
    out = verify_assets_live(SLUG, SITE, attempts=2, delay=0)
    assert out["assetsLive"] is False
    assert out["assetStatus"] == {"cards": 0, "og": 0}


# --- publish_one wiring ------------------------------------------------------

class FakeClient:
    """Minimal duck-typed Strapi agent for publish_one's interactions."""

    def __init__(self, articles):
        self.articles = articles
        self.updates = []

    def _request(self, method, path, params=None, body=None):
        if path == "/api/articles" and params and params.get("filters[status][$eq]") == "in_review":
            return {"data": self.articles}
        if path == "/api/articles" and params and params.get("filters[status][$eq]") == "published":
            return {"data": [a for a in self.articles if a.get("status") == "published"]}
        return {"data": []}

    def update_article(self, doc_id, fields):
        self.updates.append((doc_id, fields))

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "PUBLISH_STATE_FILE", tmp_path / "publish-pipeline.jsonl")
    monkeypatch.setattr(publish, "DRAFT_JOURNAL", tmp_path / "pipeline.jsonl")
    monkeypatch.setattr(publish, "RELEASE_APPROVALS", tmp_path / "release-approvals.jsonl")
    monkeypatch.setattr(publish, "SNAPSHOT", tmp_path / "published-slugs.json")
    monkeypatch.setattr(publish, "PUBLIC_CARDS", tmp_path / "cards")
    monkeypatch.setattr(publish, "PUBLIC_OG", tmp_path / "og")


def _ready_article():
    return {
        "slug": SLUG,
        "documentId": "doc-1",
        "title": "Cost of Living in Chiang Mai",
        "confidence": 90,
        "status": "in_review",
        "bodyMarkdown": "# Cost of Living in Chiang Mai\n\nBody content here.\n",
        "focusKeyword": "chiang mai cost of living",
    }


def _publish(monkeypatch, *, page_code, asset_code, push_result=(True, "pushed 2 commit(s)")):
    """Run the real publish_one with the network + side effects stubbed."""
    monkeypatch.setattr(publish, "polish_article", lambda *a, **k: None)
    monkeypatch.setattr(publish, "generate_cover", lambda slug, title, **k: True)
    monkeypatch.setattr(publish, "list_published", lambda client, **k: [])
    monkeypatch.setattr(publish, "write_slug_snapshot", lambda slugs: False)
    monkeypatch.setattr(publish, "commit_assets", lambda slug: True)
    monkeypatch.setattr(publish, "push_assets", lambda: push_result)

    def fake_get(url, **kwargs):
        code = page_code if url.rstrip("/") == f"{SITE}/{SLUG}" else asset_code
        return type("R", (), {"status_code": code, "text": "Cost of Living in Chiang Mai"})()
    monkeypatch.setattr(publish.httpx, "get", fake_get)
    monkeypatch.setattr(publish, "ASSET_VERIFY_ATTEMPTS", 1)
    monkeypatch.setattr(publish, "ASSET_VERIFY_DELAY_SECONDS", 0.0)
    monkeypatch.delenv("NOMADOMICS_ASSET_VERIFY_ATTEMPTS", raising=False)
    monkeypatch.delenv("NOMADOMICS_ASSET_VERIFY_DELAY", raising=False)
    return publish.publish_one(FakeClient([_ready_article()]), None)  # type: ignore[arg-type]


def test_publish_one_pushes_after_commit(monkeypatch):
    result = _publish(monkeypatch, page_code=200, asset_code=200)
    assert result["event"] == "published"
    assert result["push"] == "ok"
    assert result["pushDetail"] == "pushed 2 commit(s)"


def test_publish_one_not_live_when_art_is_not_served(monkeypatch):
    """The 2026-09-20 shape: page 200, art 404 -> published, NOT live."""
    result = _publish(monkeypatch, page_code=200, asset_code=404)
    assert result["httpStatus"] == 200
    assert result["assetsLive"] is False
    assert result["assetStatus"] == {"cards": 404, "og": 404}
    assert result["live"] is False


def test_publish_one_live_when_page_and_art_serve(monkeypatch):
    result = _publish(monkeypatch, page_code=200, asset_code=200)
    assert result["assetsLive"] is True
    assert result["live"] is True


def test_publish_one_reports_failed_push(monkeypatch):
    result = _publish(monkeypatch, page_code=200, asset_code=404,
                      push_result=(False, "remote: Permission denied"))
    assert result["push"] == "failed"
    assert result["pushDetail"] == "remote: Permission denied"
    assert result["live"] is False


# --- CLI exit code -----------------------------------------------------------

def _cli_publish(monkeypatch, canned):
    from engine import pipeline_cli as cli

    monkeypatch.setattr(cli, "StrapiClient", lambda cfg: FakeClient([]))
    monkeypatch.setattr(cli, "_publish_one_runner", lambda *a, **k: canned)
    return cli.main(["publish"])


def test_cli_publish_exits_1_when_not_live(monkeypatch):
    rc = _cli_publish(monkeypatch, {
        "event": "published", "slug": SLUG, "live": False, "httpStatus": 200,
        "assetStatus": {"cards": 404, "og": 404}, "push": "ok",
    })
    assert rc == 1


def test_cli_publish_exits_0_when_live(monkeypatch):
    rc = _cli_publish(monkeypatch, {
        "event": "published", "slug": SLUG, "live": True, "assetsLive": True,
    })
    assert rc == 0


def test_cli_publish_exits_0_on_skip(monkeypatch):
    rc = _cli_publish(monkeypatch, {"event": "skip", "reason": "already published today"})
    assert rc == 0