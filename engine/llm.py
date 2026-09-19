"""Shared LLM dispatch — Gemini (primary, OpenAI-compatible) + OpenRouter fallback.

Both providers speak OpenAI's chat/completions wire format, so the research /
writer / editor stages post identical payloads and only switch endpoint, key,
and model id. Gemini is the primary provider (cheap flash-class models, better
structured-output adherence); OpenRouter ``:free`` models are the fallback chain
so a provider outage degrades instead of stopping the pipeline.

Model ids are prefixed: ``gemini-*`` routes to the Gemini endpoint, everything
else routes to OpenRouter.
"""

from __future__ import annotations

import sys
import time

import httpx

from config import Config

GEMINI_PREFIX = "gemini-"

# --- wall-clock safety (2026-09-18) -----------------------------------------
# httpx's `timeout=` is PER OPERATION (connect/read/write/pool), not a total
# deadline: a peer that dribbles bytes resets the read timer, so one request can
# outlive it by minutes, and a stage multiplies that across every hop x retry.
# The 2026-09-18 draft batch stalled 3506s that way and was tree-killed by cron's
# 3600s cap (scheduler.py _DEFAULT_SCRIPT_TIMEOUT). So: give every stage an
# explicit wall-clock budget (StageBudget), tighten the per-operation envelope,
# and treat hopeless statuses as non-retryable.
#
# read=120s: a non-streamed completion sends no bytes until the model finishes, so
# this also bounds generation time. Measured healthy stage = 43s for the real
# 1800-word payload; free tiers can be several times slower, so 120s keeps healthy
# headroom while halving the old 180s stall budget. A generation cut here is logged
# per attempt and the topic simply stays pending for the next run — never a hang.
LLM_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
# Auth/permission/gone: retrying cannot help inside a run — skip the hop.
NON_RETRYABLE_STATUS = frozenset({400, 401, 402, 403, 404, 422})
# Belt-and-braces cap on sequential attempts per stage. Deliberately high enough
# that every hop in the chain still gets one attempt (a low cap would starve the
# only live hop behind two 429 hops); the wall-clock budget binds first.
MAX_TOTAL_ATTEMPTS = 12
# Per-stage wall-clock budgets: 5x+ the measured healthy stage, and enough for a
# slow (100s) hop plus several dead hops. A wedged stage cannot exceed
# budget + one read timeout; the three budgets sum to the per-topic budget.
STAGE_BUDGET_SECONDS = {"research": 240.0, "draft": 360.0, "edit": 300.0}
DEFAULT_STAGE_BUDGET_SECONDS = 360.0


class StageDeadlineExceeded(RuntimeError):
    """A stage spent its whole wall-clock budget without a usable result."""


class StageBudget:
    """Wall-clock + attempt budget for one stage of one topic.

    Usage:
        budget = StageBudget("draft")
        for ...:
            if not budget.take():      # reserves one attempt, False once spent
                break
            started = time.monotonic()
            ... call ...
            budget.note(provider, model_id, "200 ok", started)
    """

    def __init__(
        self,
        stage: str,
        *,
        seconds: float | None = None,
        max_attempts: int = MAX_TOTAL_ATTEMPTS,
    ) -> None:
        self.stage = stage
        self.seconds = (
            STAGE_BUDGET_SECONDS.get(stage, DEFAULT_STAGE_BUDGET_SECONDS)
            if seconds is None
            else seconds
        )
        self.max_attempts = max_attempts
        self._t0 = time.monotonic()
        self.attempts = 0

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def expired(self) -> bool:
        return self.elapsed >= self.seconds or self.attempts >= self.max_attempts

    def take(self) -> bool:
        """Reserve one attempt; False once the budget or attempt cap is spent."""
        if self.expired():
            return False
        self.attempts += 1
        return True

    def note(self, provider: str, model_id: str, status: str, started_at: float, extra: str = "") -> None:
        """One stderr line per attempt — before this the stages left no trail."""
        print(
            f"  [{self.stage}] {provider}/{model_id} attempt {self.attempts} -> "
            f"{status} in {time.monotonic() - started_at:.1f}s{extra}",
            file=sys.stderr,
            flush=True,
        )

    def exhaustion_reason(self) -> str:
        return (
            f"budget {self.seconds:.0f}s (or {self.max_attempts} attempts) exhausted "
            f"after {self.elapsed:.1f}s and {self.attempts} attempt(s)"
        )


def is_retryable_status(status: int) -> bool:
    """False for statuses that will not clear within a run (401/404/402/...)."""
    return status not in NON_RETRYABLE_STATUS


def is_gemini_model(model: str) -> bool:
    return model.startswith(GEMINI_PREFIX)


def provider_for_model(model: str) -> str:
    return "gemini" if is_gemini_model(model) else "openrouter"


def endpoint_for(cfg: Config, provider: str) -> tuple[str, str]:
    """Return (base_url, api_key) for a provider name."""
    if provider == "gemini":
        return cfg.gemini_base_url, cfg.gemini_api_key
    return cfg.openrouter_base_url, cfg.openrouter_api_key


def headers_for(cfg: Config, provider: str) -> dict[str, str]:
    """HTTP headers for a provider. Never logs key values."""
    h: dict[str, str] = {"Content-Type": "application/json"}
    if provider == "gemini":
        h["Authorization"] = f"Bearer {cfg.gemini_api_key}"
    else:
        h["Authorization"] = f"Bearer {cfg.openrouter_api_key}"
        h["HTTP-Referer"] = "https://nomadomics.local"
        h["X-Title"] = "Nomadomics Engine"
    return h


def stage_chain(cfg: Config, stage: str) -> list[tuple[str, str]]:
    """Ordered [(provider, model_id)] chain for a pipeline stage.

    stage ∈ {"research", "draft", "edit"}. Gemini primary model first (if the
    per-stage provider is ``gemini`` and a key is set), then the OpenRouter
    fallback chain, de-duplicated and order-preserving.
    """
    stage = stage.lower()
    provider = {
        "research": cfg.research_provider,
        "draft": cfg.draft_provider,
        "edit": cfg.edit_provider,
    }.get(stage, cfg.draft_provider)

    primary_model = {
        "research": cfg.gemini_research_model,
        "draft": cfg.gemini_draft_model,
        "edit": cfg.gemini_edit_model,
    }.get(stage, cfg.gemini_draft_model)

    or_model = {
        "research": cfg.research_model,
        "draft": cfg.draft_model,
        "edit": cfg.draft_model,  # editor falls back to the writer model
    }.get(stage, cfg.draft_model)

    chain: list[tuple[str, str]] = []
    if provider == "gemini" and cfg.gemini_api_key:
        chain.append(("gemini", primary_model))
    chain.append(("openrouter", or_model))
    for m in cfg.fallback_models:
        chain.append(("openrouter", m))

    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for item in chain:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def resolve(cfg: Config, entry) -> tuple[str, str]:
    """Normalize a chain entry to (provider, model_id).

    Accepts either a plain model string (provider inferred from the ``gemini-``
    prefix) or a ``(provider, model_id)`` tuple. A tuple with ``provider=None``
    infers the provider from the model id.
    """
    if isinstance(entry, tuple):
        provider, model_id = entry
        if provider is None:
            provider = provider_for_model(model_id)
        return provider, model_id
    return provider_for_model(entry), entry
