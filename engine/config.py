"""Nomadomics engine — configuration loader.

Loads settings from the project `.env` (gitignored) without ever printing key
values. Enforces Guy's 2026-08-11 model rule: the OpenRouter key is allowed to
call FREE (:free) models only during the testing phase; premium is gated.

Never import this outside the engine package without reason. All key values
live in-memory only and are masked in any repr/log output.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv(path: Path = ENV_PATH) -> dict[str, str]:
    """Minimal .env parser (no external dep). Returns only the parsed pairs."""
    parsed: dict[str, str] = {}
    if not path.exists():
        return parsed
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        parsed[key.strip()] = val.strip()
    return parsed


@dataclass(frozen=True)
class Config:
    strapi_url: str
    strapi_engine_token: str
    openrouter_api_key: str
    # Gemini provider (primary). Key is a copy of Guy's Google key; base_url is the
    # OpenAI-compatible endpoint (generativelanguage.googleapis.com/v1beta/openai) so
    # the existing chat/completions calls work unchanged. Gemini honors json_object /
    # structured output more reliably than OpenRouter free models.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_research_model: str = "gemini-2.5-flash"
    gemini_draft_model: str = "gemini-2.5-flash"
    gemini_edit_model: str = "gemini-2.5-flash"
    # Per-stage provider: "gemini" primary, "openrouter" fallback.
    research_provider: str = "gemini"
    draft_provider: str = "gemini"
    edit_provider: str = "gemini"
    # Model rule: FREE MODELS ONLY until production (Guy 2026-08-11)
    # Verified against OpenRouter catalog 2026-08-11 — qwen3-32b:free no longer
    # exists. gemma-4-26b-a4b-it:free confirmed working live; gemma-4-31b-it:free
    # is the stronger writer but has been intermittently rate-limited upstream
    # (2026-08-11), so it sits in fallback, not primary.
    research_model: str = "google/gemma-4-26b-a4b-it:free"
    draft_model: str = "google/gemma-4-26b-a4b-it:free"
    premium_model: str = "google/gemini-2.5-pro"  # gated: only for final-draft polish
    premium_enabled: bool = False  # False until Guy flips to production
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    fallback_models: tuple = (
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-nano-12b-v2-vl:free",
    )
    # Trust-ladder defaults (overridable per run)
    auto_publish_threshold: int = 80
    needs_review_min: int = 60
    reject_below: int = 60
    first_n_human_review: int = 0  # Guy 2026-08-29: no first-N hold — auto-publish from day one at >=80
    # v1 rule: automation NEVER publishes unless Guy flips AUTO_PUBLISH_ENABLED=true.
    auto_publish_enabled: bool = False
    # Bearer token guarding the dashboard's mutating endpoints (run-batch, topics/add).
    # Empty disables those endpoints entirely (fail-closed). Never logged.
    dashboard_admin_token: str = ""
    _secret_fields: tuple = field(
        default=("strapi_engine_token", "openrouter_api_key", "gemini_api_key", "dashboard_admin_token"),
        repr=False,
    )

    def is_free_model(self, model: str | None = None) -> bool:
        m = model or self.draft_model
        return m.endswith(":free") or "free" in m.lower()


def load_config(*, env_path: Path = ENV_PATH) -> Config:
    """Build Config from the project .env. Raises if required keys are missing."""
    env = _load_dotenv(env_path)
    missing = [k for k in ("STRAPI_ENGINE_TOKEN", "OPENROUTER_API_KEY") if not env.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing required env keys in {env_path}: {', '.join(missing)}. "
            "Add them to the gitignored .env (never commit)."
        )
    premium = env.get("PREMIUM_MODEL_ENABLED", "").strip().lower() in ("1", "true", "yes")
    auto_publish = env.get("AUTO_PUBLISH_ENABLED", "").strip().lower() in ("1", "true", "yes")
    return Config(
        strapi_url=env.get("STRAPI_URL", "http://localhost:1337").rstrip("/"),
        strapi_engine_token=env["STRAPI_ENGINE_TOKEN"],
        openrouter_api_key=env["OPENROUTER_API_KEY"],
        gemini_api_key=env.get("GEMINI_API_KEY", ""),
        premium_enabled=premium,
        auto_publish_enabled=auto_publish,
        dashboard_admin_token=env.get("DASHBOARD_ADMIN_TOKEN", ""),
    )


def redact(config: Config) -> dict:
    """Config as a safe dict with secret values masked (for logs / reports)."""
    return {
        "strapi_url": config.strapi_url,
        "research_model": config.gemini_research_model if config.research_provider == "gemini" else config.research_model,
        "draft_model": config.gemini_draft_model if config.draft_provider == "gemini" else config.draft_model,
        "edit_model": config.gemini_edit_model,
        "research_provider": config.research_provider,
        "draft_provider": config.draft_provider,
        "edit_provider": config.edit_provider,
        "premium_model": config.premium_model,
        "premium_enabled": config.premium_enabled,
        "auto_publish_enabled": config.auto_publish_enabled,
        "auto_publish_threshold": config.auto_publish_threshold,
        "gemini_key_set": bool(config.gemini_api_key),
        "is_free_testing_mode": all(
            config.is_free_model(m) for m in (config.research_model, config.draft_model)
        ) and not config.premium_enabled,
    }
