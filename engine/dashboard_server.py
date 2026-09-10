"""Nomadomics Mission Control & Content Engine Dashboard API Server.

Serves an all-in-one web dashboard for Nomadomics 2.0:
- Mission Control & Real-time Content Pipeline Monitor (Researching / Drafting / In-Review / Published / Failed)
- One-Click Strapi CMS Admin Navigation (http://localhost:1337/admin)
- Content Schedule & Topic Pipeline Management (Queue inspection, add seed topic, trigger batch)
- Live Analytics (Confidence distribution, SEO scores, Word counts, Category breakdown)
- Agent Model & Trust-Ladder Governance (Free vs Premium model inspection, threshold tweaks)
"""

from __future__ import annotations

import http.server
import hmac
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_DIR = Path(__file__).resolve().parent.parent
ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

from config import load_config, redact
from strapi import StrapiClient, StrapiError

STATE_FILE = ENGINE_DIR / "state" / "pipeline.jsonl"
HTML_FILE = ENGINE_DIR / "dashboard.html"

# The dashboard exposes a token-guarded mutation surface. Default bind is
# loopback-only; set DASHBOARD_HOST=0.0.0.0 only when a reverse proxy or a
# container needs to reach it, and always with DASHBOARD_ADMIN_TOKEN set.
DEFAULT_BIND_HOST = "127.0.0.1"

# Global lock for background engine runs
_RUN_LOCK = threading.Lock()
_CURRENT_RUN = {"status": "idle", "topic": None, "started_at": None, "last_result": None}


def _get_admin_token() -> str:
    """Resolve the dashboard admin token (process env first, then project .env).

    Returns "" when unset — callers must treat that as fail-closed.
    """
    token = os.environ.get("DASHBOARD_ADMIN_TOKEN")
    if token:
        return token
    try:
        return load_config().dashboard_admin_token
    except Exception:
        return ""


def _extract_bearer(self) -> str:
    auth = self.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    return self.headers.get("X-Dashboard-Token", "")


def _authorized(self) -> bool:
    token = _get_admin_token()
    if not token:
        return False
    supplied = _extract_bearer(self)
    return hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8"))


def _get_pipeline_logs(limit: int = 25) -> list[dict]:
    if not STATE_FILE.exists():
        return []
    lines = STATE_FILE.read_text().splitlines()
    entries = []
    for line in reversed(lines):
        if line.strip():
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
        if len(entries) >= limit:
            break
    return entries


def _run_batch_async(count: int = 1):
    def worker():
        global _CURRENT_RUN
        with _RUN_LOCK:
            _CURRENT_RUN["status"] = "running"
            _CURRENT_RUN["started_at"] = str(Path(__file__).stat().st_mtime)
            try:
                cmd = [
                    str(REPO_DIR / ".venv" / "bin" / "python"),
                    "-m",
                    "engine.cli",
                    "run-batch",
                    str(count),
                ]
                res = subprocess.run(
                    cmd,
                    cwd=str(REPO_DIR),
                    env=dict(os.environ, PYTHONPATH=""),
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                _CURRENT_RUN["status"] = "completed" if res.returncode == 0 else "failed"
                _CURRENT_RUN["last_result"] = res.stdout or res.stderr
            except Exception as e:
                _CURRENT_RUN["status"] = "failed"
                _CURRENT_RUN["last_result"] = str(e)

    t = threading.Thread(target=worker, daemon=True)
    t.start()


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def _send_json(self, data: dict | list, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            if HTML_FILE.exists():
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(HTML_FILE.read_bytes())
            else:
                self.send_response(404)
                self.end_headers()
            return

        if path == "/api/status":
            cfg = load_config()
            client = StrapiClient(cfg)
            try:
                strapi_ok = True
                articles = client._request("GET", "/api/articles", params={"pagination[pageSize]": 100}).get("data", [])
                topics = client._request("GET", "/api/topics", params={"pagination[pageSize]": 100}).get("data", [])
            except Exception as e:
                strapi_ok = False
                articles = []
                topics = []
            finally:
                client.close()

            logs = _get_pipeline_logs(20)

            payload = {
                "system": {
                    "strapi_status": "online" if strapi_ok else "offline",
                    "strapi_admin_url": f"{cfg.strapi_url}/admin",
                    "strapi_api_url": cfg.strapi_url,
                    "engine_runner": _CURRENT_RUN,
                    "config": redact(cfg),
                },
                "stats": {
                    "total_articles": len(articles),
                    "total_topics": len(topics),
                    "drafts_in_review": sum(1 for a in articles if a.get("status") in ("draft", "in_review")),
                    "published": sum(1 for a in articles if a.get("status") == "published"),
                    "pending_topics": sum(1 for t in topics if t.get("status") == "pending"),
                    "avg_confidence": round(sum(a.get("confidence", 0) for a in articles) / len(articles), 1) if articles else 0,
                    "avg_seo_score": round(sum(a.get("seoScore", 0) for a in articles) / len(articles), 1) if articles else 0,
                },
                "articles": articles,
                "topics": topics,
                "logs": logs,
            }
            self._send_json(payload)
            return

        self._send_json({"error": "Not Found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}

        if not _authorized(self):
            self._send_json({"error": "Unauthorized"}, status=401)
            return

        if path == "/api/run-batch":
            count = int(body.get("count", 1))
            if _RUN_LOCK.locked():
                self._send_json({"status": "busy", "message": "Pipeline already running"}, status=409)
                return
            _run_batch_async(count)
            self._send_json({"status": "started", "count": count})
            return

        if path == "/api/topics/add":
            title = body.get("title", "").strip()
            keyword = body.get("primaryKeyword", "").strip()
            category = body.get("category", "digital-nomad").strip()
            if not title:
                self._send_json({"error": "Title is required"}, status=400)
                return
            slug = title.lower().replace(" ", "-").replace("'", "").replace('"', "")
            cfg = load_config()
            client = StrapiClient(cfg)
            try:
                res = client._request(
                    "POST",
                    "/api/topics",
                    body={
                        "data": {
                            "title": title,
                            "slug": slug,
                            "primaryKeyword": keyword,
                            "category": category,
                            "status": "pending",
                            "priority": int(body.get("priority", 5)),
                            "targetWordCount": int(body.get("targetWordCount", 1800)),
                        }
                    },
                )
                self._send_json({"success": True, "topic": res.get("data")})
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)
            finally:
                client.close()
            return

        self._send_json({"error": "Not Found"}, status=404)


def run_server(port: int = 8080, host: str = DEFAULT_BIND_HOST):
    server = http.server.HTTPServer((host, port), DashboardHandler)
    bind_desc = "localhost" if host in ("127.0.0.1", "localhost") else host
    print(f"🚀 Nomadomics Mission Control running at http://{bind_desc}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    host = os.environ.get("DASHBOARD_HOST", DEFAULT_BIND_HOST)
    run_server(port, host)
