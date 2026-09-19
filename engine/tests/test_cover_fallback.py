"""Tests for the cover-art provider chain (publish.fetch_cover_bytes/image_routes).

Regression target: cover generation failed NON-FATALLY when the Cake key was
locked (401 "invalid session", weekly cap) and three consecutive published posts
went live with no card/OG art, with nothing to retry them. The chain must now fall
through to the next provider instead of giving up on the first dead key, and must
still return False (never raise) when every route is unusable.
"""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import publish  # noqa: E402
from publish import (  # noqa: E402
    CAKE_KEY_ENV,
    FALLBACK_IMAGE_KEY_ENV,
    FALLBACK_IMAGE_MODEL,
    fetch_cover_bytes,
    generate_cover,
    image_routes,
)

PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake-image-bytes").decode()


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"", text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Records every call; returns scripted responses per (host, attempt)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []
        self.gets = []

    def _next(self):
        return self.responses.pop(0) if self.responses else FakeResponse(500)

    def post(self, url, **kwargs):
        self.posts.append(url)
        return self._next()

    def get(self, url, **kwargs):
        self.gets.append(url)
        return self._next()

    def close(self):
        pass


@pytest.fixture
def both_keys(monkeypatch):
    monkeypatch.setenv(CAKE_KEY_ENV, "cake-key")
    monkeypatch.setenv(FALLBACK_IMAGE_KEY_ENV, "fallback-key")


@pytest.fixture
def only_fallback(monkeypatch):
    monkeypatch.delenv(CAKE_KEY_ENV, raising=False)
    monkeypatch.setenv(FALLBACK_IMAGE_KEY_ENV, "fallback-key")


# --- route selection ---------------------------------------------------------

def test_cake_is_preferred_then_fallback(both_keys):
    labels = [r["label"] for r in image_routes()]
    assert labels[0].startswith("cake-nano/")
    assert labels[1] == FALLBACK_IMAGE_MODEL


def test_routes_skip_providers_without_a_key(only_fallback):
    routes = image_routes()
    assert [r["label"] for r in routes] == [FALLBACK_IMAGE_MODEL]


def test_no_keys_means_no_routes(monkeypatch):
    monkeypatch.delenv(CAKE_KEY_ENV, raising=False)
    monkeypatch.delenv(FALLBACK_IMAGE_KEY_ENV, raising=False)
    assert image_routes() == []


# --- the regression: a locked key must not end cover generation --------------

def test_locked_cake_key_falls_through_to_the_fallback(both_keys):
    """401 cake (weekly cap) -> the fallback provider still delivers the image."""
    client = FakeClient([
        FakeResponse(401, {}),                       # cake: invalid session
        FakeResponse(200, {"data": [{"b64_json": PNG_B64}]}),  # fallback: ok
    ])

    raw, route = fetch_cover_bytes("Some Title", http_client=client)

    assert raw == base64.b64decode(PNG_B64)
    assert route == FALLBACK_IMAGE_MODEL
    assert len(client.posts) == 2
    assert client.posts[0].startswith(publish.CAKE_BASE)
    assert client.posts[1].startswith(publish.FALLBACK_IMAGE_BASE)


def test_unsent_cake_call_is_skipped_when_its_key_is_absent(only_fallback):
    client = FakeClient([FakeResponse(200, {"data": [{"b64_json": PNG_B64}]})])

    raw, route = fetch_cover_bytes("Some Title", http_client=client)

    assert raw and route == FALLBACK_IMAGE_MODEL
    assert client.posts == [f"{publish.FALLBACK_IMAGE_BASE}/images/generations"]


def test_every_route_failing_returns_empty_not_an_exception(both_keys):
    client = FakeClient([
        FakeResponse(401, {}),          # cake locked
        FakeResponse(500, {}, text="boom"),  # fallback server error
    ])

    assert fetch_cover_bytes("Some Title", http_client=client) == (None, "")


def test_network_error_falls_through_to_the_next_route(both_keys):
    class Exploding(FakeClient):
        def post(self, url, **kwargs):
            self.posts.append(url)
            if len(self.posts) == 1:
                raise RuntimeError("connection reset")
            return FakeResponse(200, {"data": [{"b64_json": PNG_B64}]})

    client = Exploding([])

    raw, route = fetch_cover_bytes("Some Title", http_client=client)

    assert raw and route == FALLBACK_IMAGE_MODEL


# --- response shapes ---------------------------------------------------------

def test_data_url_shape_is_decoded(only_fallback):
    """nano-banana returns `url` as a data: URL rather than b64_json."""
    client = FakeClient([
        FakeResponse(200, {"data": [{"url": f"data:image/png;base64,{PNG_B64}"}]}),
    ])

    raw, route = fetch_cover_bytes("Some Title", http_client=client)

    assert raw == base64.b64decode(PNG_B64)
    assert route == FALLBACK_IMAGE_MODEL
    assert client.gets == []  # nothing to fetch over the network


def test_http_url_shape_is_fetched(only_fallback):
    client = FakeClient([
        FakeResponse(200, {"data": [{"url": "https://cdn.example/cover.png"}]}),
        FakeResponse(200, content=b"\x89PNG-fetched"),
    ])

    raw, route = fetch_cover_bytes("Some Title", http_client=client)

    assert raw == b"\x89PNG-fetched"
    assert client.gets == ["https://cdn.example/cover.png"]


def test_empty_payload_is_not_an_image(only_fallback):
    client = FakeClient([FakeResponse(200, {"data": []})])

    assert fetch_cover_bytes("Some Title", http_client=client) == (None, "")


# --- generate_cover contract -------------------------------------------------

def test_generate_cover_returns_false_without_any_key(monkeypatch, tmp_path):
    monkeypatch.delenv(CAKE_KEY_ENV, raising=False)
    monkeypatch.delenv(FALLBACK_IMAGE_KEY_ENV, raising=False)

    assert generate_cover("some-slug", "Some Title") is False
    assert not (publish.PUBLIC_CARDS / "some-slug.png").exists()


def test_generate_cover_returns_false_when_all_routes_fail(both_keys):
    client = FakeClient([FakeResponse(401, {}), FakeResponse(403, {})])

    assert generate_cover("some-slug", "Some Title", http_client=client) is False
