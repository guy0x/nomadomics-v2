"""Tests for the published-slug snapshot refresh (publish.write_slug_snapshot).

The image gate validates against frontend/scripts/published-slugs.json, and the
publisher was the one path that never updated it — so it drifted on every publish and
the gate passed against a stale universe (20 published, 15 listed). These pin the
contract: write on change, stay quiet when identical, and never wipe or raise.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import publish  # noqa: E402


def snapshot_at(tmp_path, monkeypatch):
    path = tmp_path / "published-slugs.json"
    monkeypatch.setattr(publish, "SNAPSHOT", path)
    return path


def test_writes_the_sorted_set_when_the_file_is_stale(tmp_path, monkeypatch):
    path = snapshot_at(tmp_path, monkeypatch)
    path.write_text(json.dumps(["old-slug"], indent=2))

    changed = publish.write_slug_snapshot(["b-slug", "a-slug"])

    assert changed is True
    assert json.loads(path.read_text()) == ["a-slug", "b-slug"]


def test_is_idempotent_when_the_set_is_unchanged(tmp_path, monkeypatch):
    path = snapshot_at(tmp_path, monkeypatch)
    path.write_text(json.dumps(["a-slug", "b-slug"], indent=2))

    assert publish.write_slug_snapshot(["b-slug", "a-slug"]) is False


def test_creates_the_file_when_missing(tmp_path, monkeypatch):
    path = snapshot_at(tmp_path, monkeypatch)

    assert publish.write_slug_snapshot(["only-slug"]) is True
    assert json.loads(path.read_text()) == ["only-slug"]


def test_an_empty_set_never_wipes_the_file(tmp_path, monkeypatch):
    """A Strapi hiccup returning no rows must not empty the gate's universe."""
    path = snapshot_at(tmp_path, monkeypatch)
    path.write_text(json.dumps(["kept-slug"], indent=2))

    assert publish.write_slug_snapshot([]) is False
    assert publish.write_slug_snapshot(None) is False
    assert json.loads(path.read_text()) == ["kept-slug"]


def test_duplicates_and_blanks_are_dropped(tmp_path, monkeypatch):
    path = snapshot_at(tmp_path, monkeypatch)

    assert publish.write_slug_snapshot(["b", "a", "b", "", None]) is True
    assert json.loads(path.read_text()) == ["a", "b"]


def test_a_write_failure_returns_false_and_never_raises(tmp_path, monkeypatch):
    """Best-effort by design: the publisher must not fail over the snapshot."""
    blocked = tmp_path / "nope" / "published-slugs.json"  # parent does not exist
    monkeypatch.setattr(publish, "SNAPSHOT", blocked)

    assert publish.write_slug_snapshot(["a-slug"]) is False


def test_commit_assets_stages_the_snapshot(tmp_path, monkeypatch):
    """The art commit must carry the snapshot, or the gate re-drifts."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stderr = b""
        return R()

    monkeypatch.setattr(publish.subprocess, "run", fake_run)

    assert publish.commit_assets("some-slug") is True
    assert calls[0][:2] == ["git", "add"]
    assert "frontend/scripts/published-slugs.json" in calls[0]
    assert "frontend/public/cards/some-slug.png" in calls[0]
