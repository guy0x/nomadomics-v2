"""Tests for the dashboard server's security hardening.

Covers the quick-win groundwork:
- loopback bind by default (no wildcard host)
- no wildcard CORS headers on any response
- token-gated mutating endpoints (POST) with fail-closed behaviour

Runs against a real ThreadingHTTPServer on an ephemeral loopback port so these
assertions exercise the actual HTTP surface, not just helper functions.
"""
import http.client
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dashboard_server as ds  # noqa: E402

ADMIN_TOKEN = "test-dashboard-secret"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setattr(ds, "_run_batch_async", lambda count=1: None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address  # (host, port)
    srv.shutdown()
    t.join(timeout=5)
    srv.server_close()


def _request(addr, method, path, body=None, headers=None, token=None):
    conn = http.client.HTTPConnection(*addr, timeout=10)
    hdrs = dict(headers or {})
    if token is not None:
        hdrs["Authorization"] = f"Bearer {token}"
    if body is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "application/json"
    payload = json.dumps(body) if body is not None else None
    conn.request(method, path, body=payload, headers=hdrs)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    return resp.status, dict(resp.getheaders()), data


# --- bind host -------------------------------------------------------------

def test_default_bind_host_is_loopback():
    assert ds.DEFAULT_BIND_HOST == "127.0.0.1"


def test_run_server_defaults_to_loopback():
    # run_server's default host arg must be loopback, not 0.0.0.0
    defaults = ds.run_server.__defaults__
    assert defaults is not None and defaults[-1] == "127.0.0.1"


# --- CORS ------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [("GET", "/api/does-not-exist")])
def test_json_response_has_no_cors_headers(server, method, path):
    status, headers, _ = _request(server, method, path)
    assert status == 404
    assert "access-control-allow-origin" not in headers
    assert "access-control-allow-methods" not in headers


def test_options_response_has_no_cors_headers(server):
    status, headers, _ = _request(server, "OPTIONS", "/")
    assert status == 204
    assert "access-control-allow-origin" not in headers


# --- auth on mutating endpoints -------------------------------------------

def test_post_run_batch_without_token_is_401(server):
    status, _, _ = _request(server, "POST", "/api/run-batch", body={"count": 1})
    assert status == 401


def test_post_topics_add_without_token_is_401(server):
    status, _, _ = _request(server, "POST", "/api/topics/add", body={"title": "X"})
    assert status == 401


def test_post_with_wrong_token_is_401(server):
    status, _, _ = _request(
        server, "POST", "/api/run-batch", body={"count": 1}, token="wrong-token"
    )
    assert status == 401


def test_post_with_correct_token_passes_auth(server):
    status, _, body = _request(
        server, "POST", "/api/run-batch", body={"count": 2}, token=ADMIN_TOKEN
    )
    assert status == 200
    assert json.loads(body) == {"status": "started", "count": 2}


def test_post_supports_x_dashboard_token_header(server):
    status, _, body = _request(
        server,
        "POST",
        "/api/run-batch",
        body={"count": 1},
        headers={"X-Dashboard-Token": ADMIN_TOKEN},
    )
    assert status == 200
    assert json.loads(body)["status"] == "started"


def test_mutating_endpoints_fail_closed_when_token_unset(monkeypatch):
    monkeypatch.delenv("DASHBOARD_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(ds, "_get_admin_token", lambda: "")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        status, _, _ = _request(
            srv.server_address, "POST", "/api/run-batch", body={"count": 1}, token="anything"
        )
        assert status == 401
    finally:
        srv.shutdown()
        t.join(timeout=5)
        srv.server_close()


# --- read endpoints stay open ---------------------------------------------

def test_get_endpoint_is_open_without_auth(server, monkeypatch):
    # A GET 404 JSON response proves GET paths are not gated by the token.
    status, _, _ = _request(server, "GET", "/api/nope")
    assert status == 404