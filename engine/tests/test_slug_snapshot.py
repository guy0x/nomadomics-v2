"""Tests for the published-slug snapshot refresh (publish.write_slug_snapshot).

The image gate validates against frontend/scripts/published-slugs.json, and the
publisher was the one path that never updated it — so it drifted on every publish and
the gate passed against a stale universe (20 published, 15 listed). These pin the
contract: write on change, stay quiet when identical, and never wipe or raise.

2026-10-05 (QA F-06 root cause): a slug whose cover files FAILED to generate was
still ledgered — the snapshot was written from the live Strapi set with no
existence check, so a generation failure produced a ledgered-but-absent slug that
every later sweep then skipped as "already covered". The snapshot must refuse any
slug whose cards/og PNG is absent from disk: a ledger entry with no file is not a
success. Tests here fail RED on the pre-fix code (they were run against it and
failed exactly as the production defect predicted).
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


def art_dirs_at(tmp_path, monkeypatch):
    """Point the art-dir constants at a temp tree; helper returns a creator."""
    cards = tmp_path / "cards"
    og = tmp_path / "og"
    cards.mkdir()
    og.mkdir()
    monkeypatch.setattr(publish, "PUBLIC_CARDS", cards)
    monkeypatch.setattr(publish, "PUBLIC_OG", og)

    def make(slug: str, *, card: bool = True, og_img: bool = True):
        if card:
            (cards / f"{slug}.png").write_bytes(b"\x89PNG fake")
        if og_img:
            (og / f"{slug}.png").write_bytes(b"\x89PNG fake")

    return make


def test_writes_the_sorted_set_when_the_file_is_stale(tmp_path, monkeypatch):
    path = snapshot_at(tmp_path, monkeypatch)
    make = art_dirs_at(tmp_path, monkeypatch)
    make("a-slug")
    make("b-slug")
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
    make = art_dirs_at(tmp_path, monkeypatch)
    make("only-slug")

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
    make = art_dirs_at(tmp_path, monkeypatch)
    make("a")
    make("b")

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


# ---------------------------------------------------------------------------
# F-06 root cause (2026-10-05): the ledger must never contain a slug whose
# cover files are absent. RED on pre-fix code — verified before the fix.
# ---------------------------------------------------------------------------

def test_refuses_slug_with_no_art_on_disk(tmp_path, monkeypatch):
    """The production defect: barcelona published, generate_cover failed
    non-fatally, snapshot still recorded it. Now the snapshot refuses."""
    path = snapshot_at(tmp_path, monkeypatch)
    make = art_dirs_at(tmp_path, monkeypatch)
    make("covered-slug")
    # no-slug: NOT created on disk

    changed = publish.write_slug_snapshot(["covered-slug", "no-slug"])

    written = json.loads(path.read_text())
    assert "no-slug" not in written, (
        "snapshot must not ledger a slug whose card/og files are absent"
    )
    assert written == ["covered-slug"]
    assert changed is True


def test_refuses_slug_with_only_one_of_two_files(tmp_path, monkeypatch):
    """Half-generated (card but no og) is still a ghost in the making.

    Contract when EVERY slug is refused: the snapshot is left untouched
    (early return, no file created) — an all-ghost set writes nothing.
    """
    path = snapshot_at(tmp_path, monkeypatch)
    make = art_dirs_at(tmp_path, monkeypatch)
    make("half-slug", og_img=False)

    changed = publish.write_slug_snapshot(["half-slug"])

    assert changed is False
    assert not path.exists()


def test_writes_slugs_that_do_have_both_files(tmp_path, monkeypatch):
    """The happy path must survive: real art on disk -> ledgered as before."""
    path = snapshot_at(tmp_path, monkeypatch)
    make = art_dirs_at(tmp_path, monkeypatch)
    make("real-slug")

    assert publish.write_slug_snapshot(["real-slug"]) is True
    assert json.loads(path.read_text()) == ["real-slug"]
