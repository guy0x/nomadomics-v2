"""One-command live check for the Gemini key (kanban t_7e0fea29).

The rotation runbook (kanban t_5cfa68d0, §5) ends in "is the new key live?".
This command answers it without touching Strapi, the draft queue, or any
state file: one minimal ``generateContent`` call against the Gemini endpoint
the engine itself is configured with (``Config.gemini_base_url`` /
``Config.gemini_edit_model``), using ``Config.gemini_api_key``.

Exit codes:
  0  key works (HTTP 200; 429 also exits 0 — the key authenticated, the
     free tier is merely out of quota right now)
  1  key rejected (401/403) — the exact class the fail-soft edit hop now
     skips; "rotation needed" (kanban t_8db05179)
  2  key unset, or anything else went wrong (network, unexpected payload)

No argument form: the key is read from the engine's own .env, i.e. exactly
the credential the pipeline uses — never from the Hermes .env. Output shows
only the key's length and sha256 prefix; the value itself is never printed,
sent anywhere, or written to any log. A --key-file run reads the file and
prints a diff verdict WITHOUT writing the engine .env (the USER does the
one-line edit, or asks for it, per the runbook).

Usage (from repo root or engine dir):
  python -m engine.cli gemini-smoke
  python -m engine.cli gemini-smoke --key-file ~/.hermes/secrets/google_api_key
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# Same shim as engine/cli.py: makes `python -m engine.smoke` and
# `python engine/smoke.py` work alongside the canonical `python -m engine.cli
# gemini-smoke` entry, under the project's flat-import layout.
_ENGINE_DIR = Path(__file__).resolve().parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

import httpx

from config import Config, load_config

# Minimal, cheapest possible probe — mirrors the runbook's curl probe (a).
_SMOKE_PROMPT = "ping"
_SMOKE_MAX_TOKENS = 1


def _fp(key: str) -> str:
    """Human-safe fingerprint: len + sha256[:8]. Never the value."""
    return f"len={len(key)} sha256[:8]={hashlib.sha256(key.encode()).hexdigest()[:8]}"


def _key_file_fingerprint(path: str | Path) -> tuple[str, str]:
    """(fingerprint, first-token-shape) of a key file, for the diff verdict."""
    raw = Path(path).read_text().strip()
    if not raw:
        raise RuntimeError(f"key file is empty: {path}")
    shape = "AIza… (AI Studio — correct)" if raw.startswith("AIza") else (
        "AQ. … (Vertex express token — the shape that just died)"
        if raw.startswith("AQ.") else "unrecognized prefix"
    )
    return _fp(raw), shape


def _gemini_status(base_url: str, model: str, key: str) -> tuple[int, str]:
    """One generateContent call; returns (http_status, short_detail).

    Uses the OpenAI-compatible surface ONLY to derive the native endpoint
    from the same configured base, then speaks native generateContent —
    the wire format the runbook's curl probe and the verdict t_75301181
    reproduced the 401 on.
    """
    native_base = base_url.split("/openai")[0]
    url = f"{native_base}/models/{model}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    payload = {
        "contents": [{"parts": [{"text": _SMOKE_PROMPT}]}],
        "generationConfig": {"maxOutputTokens": _SMOKE_MAX_TOKENS},
    }
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)) as c:
        resp = c.post(url, json=payload, headers=headers)
    detail = ""
    if resp.status_code != 200:
        # Error bodies can echo request context — keep only the status text.
        try:
            err = resp.json().get("error", {})
            detail = str(err.get("status") or err.get("message", ""))[:120]
        except (json.JSONDecodeError, AttributeError):
            detail = resp.text[:120] if resp.text else ""
    return resp.status_code, detail


def run_smoke(config: Config | None = None, key_file: str | None = None) -> int:
    cfg = config or load_config()

    print(f"gemini-smoke: endpoint={cfg.gemini_base_url} model={cfg.gemini_edit_model}")

    if key_file:
        fp, shape = _key_file_fingerprint(key_file)
        print(f"gemini-smoke: key-file {key_file}: {fp} — {shape}")
        live_fp = _fp(cfg.gemini_api_key) if cfg.gemini_api_key else "(no key set)"
        same = fp == live_fp
        print(
            "gemini-smoke: engine .env key: " + live_fp
            + (" — SAME as key file" if same else " — DIFFERENT from key file")
        )
        if not same:
            print(
                "gemini-smoke: the engine reads its own .env, not this file. "
                "Update GEMINI_API_KEY in ~/nomadomics-v2/.env (line 27) — see "
                "runbook §4 — then rerun without --key-file.",
                file=sys.stderr,
            )
            return 2

    if not cfg.gemini_api_key:
        print(
            "gemini-smoke: FAIL — no GEMINI_API_KEY set in the engine .env. "
            "Rotation: runbook kanban t_5cfa68d0.",
            file=sys.stderr,
        )
        return 2

    print(f"gemini-smoke: key fingerprint {_fp(cfg.gemini_api_key)}")
    try:
        status, detail = _gemini_status(cfg.gemini_base_url, cfg.gemini_edit_model, cfg.gemini_api_key)
    except httpx.HTTPError as e:
        print(f"gemini-smoke: FAIL — network error reaching Gemini: {type(e).__name__}", file=sys.stderr)
        return 2

    if status == 200:
        print("gemini-smoke: PASS — Gemini key works (HTTP 200). Edit hop will use it.")
        return 0
    if status == 429:
        print(
            "gemini-smoke: PASS — key is LIVE but rate-limited (HTTP 429). "
            "Authentication succeeded; free-tier quota exhausted right now.",
        )
        return 0
    if status in (401, 403):
        # Match the alarm vocabulary the cron surface greps for (t_8db05179).
        print(
            f"ALARM: Gemini key invalid - rotation needed (gemini/{cfg.gemini_edit_model} "
            f"-> HTTP {status} auth rejected)",
            file=sys.stderr,
        )
        print(
            f"gemini-smoke: FAIL — key rejected (HTTP {status}{' ' + detail if detail else ''}). "
            "Rotation: runbook kanban t_5cfa68d0.",
            file=sys.stderr,
        )
        return 1

    print(
        f"gemini-smoke: FAIL — unexpected HTTP {status}{' ' + detail if detail else ''} "
        "(key may be fine; investigate before rotating)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    args = sys.argv[1:]
    kf = None
    if "--key-file" in args:
        i = args.index("--key-file")
        if i + 1 >= len(args):
            print("usage: python -m engine.cli gemini-smoke [--key-file <path>]", file=sys.stderr)
            sys.exit(2)
        kf = args[i + 1]
    sys.exit(run_smoke(key_file=kf))
