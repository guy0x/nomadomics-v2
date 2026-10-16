"""Nomadomics engine — configuration loader.

Loads settings from the project `.env` (gitignored) without ever printing key
values. Enforces Guy's 2026-08-11 model rule: the OpenRouter key is allowed to
call FREE (:free) models only during the testing phase; premium is gated.

Precedence (2026-09-18, the STRAPI_URL trap): the **process environment wins
over `.env`** — the standard dotenv rule — for every key this loader reads, so a
single run can be pointed somewhere else, e.g.

    env -u PYTHONPATH STRAPI_URL=http://127.0.0.1:9 .venv/bin/python -m engine.cli next

Until this rule existed, `os.environ` was never consulted, so that command
silently ran against *live* Strapi. An EMPTY environment value (`FOO=`) counts
as unset and never clobbers a real `.env` value. Because the override is
environment-wide, `load_config()` names (never prints the value of) each key the
environment won, on stderr — the silence was the actual defect.

Never import this outside the engine package without reason. All key values
live in-memory only and are masked in any repr/log output.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
DEFAULT_SITE_PROFILE_PATH = REPO_ROOT / "config" / "sites" / "nomadomics.json"

# The keys `load_config()` reads. Listed only so the override rule has a
# documented surface (and so `env_overrides` reports them); the precedence rule
# itself is generic — any key the `.env` defines is overridable the same way.
CONFIG_KEYS = (
    "STRAPI_URL",
    "STRAPI_ENGINE_TOKEN",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "PREMIUM_MODEL_ENABLED",
    "AUTO_PUBLISH_ENABLED",
    "DASHBOARD_ADMIN_TOKEN",
    # Per-stage provider gate (2026-09-22, t_22a3bbdc; default flipped
    # 2026-10-16, t_5387e209). Values: "gemini" (the canonical lane since
    # 2026-10-11) or "openrouter". Unset/unknown = the dataclass default
    # (gemini) — a bare run-batch must not walk a dead OR chain.
    "RESEARCH_PROVIDER",
    "DRAFT_PROVIDER",
    # Non-secret site identity controls. Empty values remain unset, like all
    # other process overrides handled by `_resolve_env`.
    "NOMADOMICS_SITE_PROFILE",
    "NOMADOMICS_SITE_KEY",
)

# Stage providers a run may select through the environment. Only these two
# stages are gated: `edit` already runs on gemini in production.
STAGE_PROVIDERS = ("openrouter", "gemini")


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


def _resolve_env(
    *, env_path: Path = ENV_PATH, environ: Mapping[str, str] | None = None
) -> tuple[dict[str, str], tuple[str, ...]]:
    """`.env` pairs with the process environment overlaid on top.

    Returns `(resolved, overridden_keys)`. Rule: a non-empty process-environment
    value wins; an absent key, or one present but empty (`STRAPI_URL=` on the
    command line), is treated as *unset* and leaves the `.env` value alone.
    `overridden_keys` carries KEY NAMES only — never a value, so a caller can
    report which settings the environment won without leaking a secret.
    """
    file_env = _load_dotenv(env_path)
    proc_env = os.environ if environ is None else environ
    resolved = dict(file_env)
    overridden: list[str] = []
    for key in sorted(set(file_env) | set(CONFIG_KEYS)):
        value = (proc_env.get(key) or "").strip()
        if not value:
            continue  # absent or empty == unset; never clobber the file value
        if value != file_env.get(key):
            overridden.append(key)
        resolved[key] = value
    return resolved, tuple(overridden)


@dataclass(frozen=True)
class Config:
    strapi_url: str
    # Secrets are `repr=False` so `repr(cfg)` / f"{cfg}" can never leak them; the
    # `_secret_fields` tuple below is the guard list for that (2026-09-18).
    strapi_engine_token: str = field(repr=False)
    openrouter_api_key: str = field(repr=False)
    # Explicit, non-secret site identity. The profile itself is loaded by callers
    # that need its full contract; keeping the path/key here makes every run's
    # scope inspectable without putting secrets in the profile.
    site_profile_path: Path = DEFAULT_SITE_PROFILE_PATH
    site_key: str = "nomadomics"
    # Gemini provider (primary). Key is a copy of Guy's Google key; base_url is the
    # OpenAI-compatible endpoint (generativelanguage.googleapis.com/v1beta/openai) so
    # the existing chat/completions calls work unchanged. Gemini honors json_object /
    # structured output more reliably than OpenRouter free models.
    gemini_api_key: str = field(default="", repr=False)
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    # 2026-10-11 live probe: gemini-2.5-flash returns 404 on this account's
    # OpenAI-compatible endpoint. The already-served lite route answers the
    # real edit payload, so it is the least-cost usable text lane for research,
    # draft, and edit until a newer model is independently verified.
    gemini_research_model: str = "gemini-flash-lite-latest"
    gemini_draft_model: str = "gemini-flash-lite-latest"
    # 2026-09 key: gemini-flash-lite-latest serves all shapes incl. the real
    # edit prompt (200 in ~23s) — verified live 2026-09-21.
    gemini_edit_model: str = "gemini-flash-lite-latest"
    # Per-stage provider. Gemini is the canonical lane since 2026-10-11
    # (kanban t_f4d2aabc): the OpenRouter key in .env is revoked (401 "User not
    # found") and every OR :free hop died at auth, so a bare run-batch outside
    # the wrapper must default to the green Gemini lane, not walk the dead OR
    # chain. Explicit RESEARCH_PROVIDER/DRAFT_PROVIDER=openrouter still works
    # for those who opt in with a valid key.
    research_provider: str = "gemini"
    draft_provider: str = "gemini"
    edit_provider: str = "gemini"
    # Model rule: FREE MODELS ONLY until production (Guy 2026-08-11).
    # Chain reordered 2026-09-21 (t_02673f32, DIAGNOSIS.md t_541d35ee): both
    # gemma-4:free hops hard-429 all day (~8 wasted attempts on 09-21), while
    # nemotron-3-super:free is the only hop that reliably 200s (it carried both
    # of 09-21's successful stages). It leads.
    #
    # Fallback chain rebuilt 2026-09-28 (t_afaa4c2f) from a live probe of the
    # REAL research payload: the two gemma-4 hops are still hard-429 after three
    # weeks (upstream Google AI Studio shared pool, no X-RateLimit headers) and
    # were the only thing behind the model above, so the 09-28 batch had ONE
    # usable hop and lost both topics when it hung. Measured replacements:
    #   nvidia/nemotron-3-ultra-550b-a55b:free  200 in 44.8s — 4 facts / 4 URLs
    #   dots-studio/dots-3-note-preview:free    200 in 71.7s — 3 facts / 3 URLs
    # nvidia/nemotron-3.5-lightning:free stays LAST: slow and wedge-prone under a
    # real payload (>170s un-answered; finish_reason=length at its cap) but it is
    # the only other hop that answers at all, and a hail-mary costs nothing when
    # nothing follows it — llm.attempt_deadline gives the last hop the whole
    # remaining stage, and llm._record_hang benches it after two wedges in a row.
    research_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    draft_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    premium_model: str = "google/gemini-2.5-pro"  # gated: only for final-draft polish
    premium_enabled: bool = False  # False until Guy flips to production
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    fallback_models: tuple = (
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "dots-studio/dots-3-note-preview:free",
        # 2026-09-22 (t_6789212d): nemotron-nano-12b-v2-vl:free 404s on every call
        # ("No endpoints found" — retired from OpenRouter), so the last fallback
        # could never serve. Live-probed both candidates before the swap; 3.5
        # lightning answered a real completion.
        "nvidia/nemotron-3.5-lightning:free",
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
    dashboard_admin_token: str = field(default="", repr=False)
    # KEY NAMES (never values) the process environment overrode in the `.env`
    # for this load — the receipt for a shadow-URL / dry-test override.
    env_overrides: tuple = ()
    # Every field named here MUST also be declared `repr=False` above; a test
    # pins that pairing so a new secret cannot be added unmasked.
    _secret_fields: tuple = field(
        default=("strapi_engine_token", "openrouter_api_key", "gemini_api_key", "dashboard_admin_token"),
        repr=False,
    )

    def is_free_model(self, model: str | None = None) -> bool:
        m = model or self.draft_model
        return m.endswith(":free") or "free" in m.lower()


def _stage_provider(env: Mapping[str, str], key: str) -> str:
    """Read a per-stage provider override from the resolved environment.

    Default and unknown values fall back to ``gemini`` — the canonical free
    lane since 2026-10-11 (kanban t_f4d2aabc), after the OpenRouter key in
    .env was revoked and every OR :free hop began 401ing at auth. A typo (or
    an unset var) can therefore never silently walk the dead OR chain; only
    an explicit ``gemini``/``openrouter`` is honoured, and it is announced by
    name on stderr (never by value): the stage-provider change is a
    spend-policy decision Guy signs off on per run, so it must be visible in
    the run log.

    Named keys only in the message — this never prints a value.
    """
    raw = (env.get(key) or "").strip().lower()
    if not raw:
        return "gemini"
    if raw not in STAGE_PROVIDERS:
        print(
            f"[config] {key} is not one of {'/'.join(STAGE_PROVIDERS)} "
            "— keeping the canonical gemini lane",
            file=sys.stderr,
        )
        return "gemini"
    # Provider choice is already present in redacted `engine.cli info` and
    # lane-smoke state; keep ordinary CLI stdout/stderr byte-clean so cron
    # wrappers can parse the first line deterministically.
    return raw


def _site_profile_path(raw: str | None) -> Path:
    """Resolve the named profile override without consulting any secret input."""
    if not raw or not raw.strip():
        return DEFAULT_SITE_PROFILE_PATH
    path = Path(raw.strip()).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def load_config(
    *, env_path: Path = ENV_PATH, environ: Mapping[str, str] | None = None
) -> Config:
    """Build Config from the project `.env`, overridden by the process environment.

    Raises if required keys are missing from BOTH sources. `environ` defaults to
    `os.environ` read at call time (injectable for tests).
    """
    env, overridden = _resolve_env(env_path=env_path, environ=environ)
    if overridden:
        # Loud, key-names-only: an environment override that silently did nothing
        # is how a "safe" control command once ran against live Strapi.
        print(
            f"[config] process environment overrides .env for: {', '.join(overridden)}",
            file=sys.stderr,
        )
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
        site_profile_path=_site_profile_path(env.get("NOMADOMICS_SITE_PROFILE")),
        site_key=env.get("NOMADOMICS_SITE_KEY", "nomadomics").strip() or "nomadomics",
        premium_enabled=premium,
        auto_publish_enabled=auto_publish,
        dashboard_admin_token=env.get("DASHBOARD_ADMIN_TOKEN", ""),
        # Stage-provider gate (t_22a3bbdc): canonical lane is gemini.
        #   RESEARCH_PROVIDER=openrouter DRAFT_PROVIDER=openrouter engine.cli run-batch 1
        # opts back into the free OpenRouter chain for a run with a valid key.
        research_provider=_stage_provider(env, "RESEARCH_PROVIDER"),
        draft_provider=_stage_provider(env, "DRAFT_PROVIDER"),
        env_overrides=overridden,
    )


def redact(config: Config) -> dict:
    """Config as a safe dict with secret values masked (for logs / reports)."""
    return {
        "strapi_url": config.strapi_url,
        "site_profile_path": str(config.site_profile_path),
        "site_key": config.site_key,
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
        # Names only; never the overridden values.
        "env_overrides": list(config.env_overrides),
        "gemini_key_set": bool(config.gemini_api_key),
        "is_free_testing_mode": all(
            config.is_free_model(m) for m in (config.research_model, config.draft_model)
        ) and not config.premium_enabled,
    }
