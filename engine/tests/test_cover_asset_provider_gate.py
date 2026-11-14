"""Regression: the publisher must accept every approved cover-worker receipt."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import publish


def _asset(path: Path, data: bytes, size: tuple[int, int]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "width": size[0],
        "height": size[1],
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def test_higgsfield_ready_receipt_is_a_valid_publish_cover(monkeypatch, tmp_path):
    """The worker's approved Higgsfield route must not be rejected as non-Gemini."""
    slug = "fixture"
    cards, og = tmp_path / "cards", tmp_path / "og"
    card = _asset(cards / f"{slug}.png", b"card", publish.GEMINI_CARD_SIZE)
    og_meta = _asset(og / f"{slug}.png", b"og", publish.GEMINI_OG_SIZE)
    manifest = tmp_path / "assets.json"
    manifest.write_text(json.dumps({"assets": {slug: {
        "status": "ready",
        "provider": "higgsfield:xai/grok-imagine-image-2.0",
        "qa": {"verdict": "pass"},
        "card": card,
        "og": og_meta,
    }}}))
    monkeypatch.setattr(publish, "GEMINI_ASSET_MANIFEST", manifest)
    monkeypatch.setattr(publish, "PUBLIC_CARDS", cards)
    monkeypatch.setattr(publish, "PUBLIC_OG", og)

    assert publish.browser_asset_ready(slug) == (True, "approved cover asset receipt verified")
