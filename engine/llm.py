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

from config import Config

GEMINI_PREFIX = "gemini-"


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
