"""Tests for the gemini-smoke one-command live check (kanban t_7e0fea29).

The smoke command is the rotation runbook's verify step (t_5cfa68d0 §5): it
must PASS on a working key, PASS with a distinct message on a live-but-
rate-limited key (429), FAIL with the rotation alarm on 401/403, and fail
closed (exit 2) on an unset key or a network error — printing only key
FINGERPRINTS (len + sha256[:8]), never the key value.
"""
import hashlib
import sys
from pathlib import Path

import httpx
import pytest  # noqa: F401  (suite convention)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from smoke import run_smoke


def make_cfg(**over):
    kw = dict(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="or-key",
        gemini_api_key="g-key",
    )
    kw.update(over)
    return Config(**kw)


class FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""

    def json(self):
        return {"error": {"status": "UNAUTHENTICATED"}}


class FakeClient:
    """Stands in for httpx.Client (context-manager form used by smoke.py)."""

    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        return self.resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run(monkeypatch, capsys, cfg, resp):
    client = FakeClient(resp)
    monkeypatch.setattr("smoke.httpx.Client", lambda *a, **k: client)
    rc = run_smoke(config=cfg)
    ro = capsys.readouterr()
    return rc, ro.out, ro.err, client


# --- the three key states -----------------------------------------------------


def test_pass_on_200(monkeypatch, capsys):
    rc, out, err, client = _run(monkeypatch, capsys, make_cfg(), FakeResp(200))
    assert rc == 0
    assert "PASS" in out
    assert "ALARM" not in out + err
    assert len(client.calls) == 1
    url, payload, headers = client.calls[0]
    assert ":generateContent" in url
    assert headers["x-goog-api-key"] == "g-key"  # header auth, like the engine's verdict probe
    assert payload["contents"][0]["parts"][0]["text"] == "ping"


def test_rate_limited_key_is_still_pass(monkeypatch, capsys):
    """429 = the key AUTHENTICATED; free-tier quota is not an invalid key."""
    rc, out, err, _ = _run(monkeypatch, capsys, make_cfg(), FakeResp(429))
    assert rc == 0
    assert "429" in out
    assert "rate-limited" in out.lower()


def test_auth_rejected_exit_1_with_alarm(monkeypatch, capsys):
    rc, out, err, _ = _run(monkeypatch, capsys, make_cfg(), FakeResp(401))
    assert rc == 1
    # Same alarm vocabulary the cron surface greps for (t_8db05179).
    assert "ALARM: Gemini key invalid - rotation needed" in err
    assert "FAIL" in err
    assert "401" in err


def test_403_is_the_same_auth_class(monkeypatch, capsys):
    rc, _, _, _ = _run(monkeypatch, capsys, make_cfg(), FakeResp(403))
    assert rc == 1


# --- fail-closed paths ---------------------------------------------------------


def test_no_key_fails_closed_without_network(monkeypatch, capsys):
    rc, out, err, client = _run(monkeypatch, capsys, make_cfg(gemini_api_key=""), None)
    assert rc == 2
    assert "no GEMINI_API_KEY" in err
    assert client.calls == []


def test_network_error_fails_closed(monkeypatch, capsys):
    class BoomClient(FakeClient):
        def post(self, url, json=None, headers=None):
            raise httpx.ConnectError("connection refused")

    client = BoomClient(None)
    monkeypatch.setattr("smoke.httpx.Client", lambda *a, **k: client)
    rc = run_smoke(config=make_cfg())
    ro = capsys.readouterr()
    assert rc == 2
    assert "network error" in ro.err


# --- redaction ------------------------------------------------------------------


def test_fingerprint_shown_key_value_never(monkeypatch, capsys):
    secret = "AIzaSUPERSECRETVALUE1234567890abcdefg"
    rc, out, err, _ = _run(monkeypatch, capsys, make_cfg(gemini_api_key=secret), FakeResp(401))
    combined = out + err
    assert secret not in combined
    # The sha256[:8] fingerprint IS shown — that is the operator's identification aid.
    assert hashlib.sha256(secret.encode()).hexdigest()[:8] in combined


def test_key_file_diff_mode_never_hits_network(monkeypatch, capsys, tmp_path):
    """--key-file compares fingerprints and advises; it does NOT probe or write .env."""
    kf = tmp_path / "candidate.key"
    kf.write_text("AIzaFAKE0000000000000000000000000000000")
    client = FakeClient(None)
    monkeypatch.setattr("smoke.httpx.Client", lambda *a, **k: client)
    rc = run_smoke(config=make_cfg(), key_file=str(kf))
    ro = capsys.readouterr()
    assert rc == 2  # diff verdict: engine .env still holds a different key
    assert "DIFFERENT from key file" in ro.out
    assert "AIza… (AI Studio" in ro.out  # shape detected as the correct mint
    assert client.calls == []  # no network call in diff mode
    assert "AIzaFAKE" not in ro.out + ro.err  # fingerprint only, never the value


def test_key_file_vertex_shape_is_named_as_the_dead_shape(monkeypatch, capsys, tmp_path):
    kf = tmp_path / "candidate.key"
    kf.write_text("AQ.somevertexexpressremnant")
    client = FakeClient(None)
    monkeypatch.setattr("smoke.httpx.Client", lambda *a, **k: client)
    rc = run_smoke(config=make_cfg(), key_file=str(kf))
    ro = capsys.readouterr()
    assert rc == 2
    assert "Vertex express" in ro.out


# --- CLI wiring ------------------------------------------------------------------


def test_cli_dispatches_gemini_smoke(monkeypatch, capsys):
    import pipeline_cli

    class FakeStrapi:
        def close(self):
            pass

    seen = {}

    def fake_smoke(config, key_file):
        seen["config"] = config
        seen["key_file"] = key_file
        return 0

    monkeypatch.setattr(pipeline_cli, "StrapiClient", lambda cfg: FakeStrapi())
    monkeypatch.setattr(pipeline_cli, "run_gemini_smoke", fake_smoke)
    rc = pipeline_cli.main(["gemini-smoke"])
    assert rc == 0
    assert seen["key_file"] is None
