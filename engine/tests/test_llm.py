"""Tests for the shared LLM dispatch (Gemini primary / OpenRouter fallback)."""
from config import Config
from llm import (
    endpoint_for,
    headers_for,
    is_gemini_model,
    provider_for_model,
    resolve,
    stage_chain,
)


def make_cfg(**over):
    kw = dict(
        strapi_url="http://localhost:1337",
        strapi_engine_token="tok",
        openrouter_api_key="or-key",
        gemini_api_key="g-key",
        research_provider="gemini",
        draft_provider="gemini",
        edit_provider="gemini",
    )
    kw.update(over)
    return Config(**kw)


def test_is_gemini_model():
    assert is_gemini_model("gemini-2.5-flash") is True
    assert is_gemini_model("google/gemma-4-26b-a4b-it:free") is False


def test_provider_for_model():
    assert provider_for_model("gemini-2.5-flash") == "gemini"
    assert provider_for_model("nvidia/nemotron:free") == "openrouter"


def test_stage_chain_gemini_primary_then_openrouter_fallback():
    cfg = make_cfg()
    chain = stage_chain(cfg, "research")
    assert chain[0] == ("gemini", "gemini-2.5-flash")
    # OpenRouter primary :free model + fallbacks follow, no duplicates
    assert ("openrouter", "google/gemma-4-26b-a4b-it:free") in chain
    providers = [p for p, _ in chain]
    assert providers[0] == "gemini"
    # de-duplicated
    assert len(chain) == len(set(chain))


def test_stage_chain_openrouter_only_when_no_gemini_key():
    cfg = make_cfg(gemini_api_key="")
    chain = stage_chain(cfg, "draft")
    # Gemini skipped (no key); first entry is the OpenRouter writer model
    assert chain[0][0] == "openrouter"
    assert all(p == "openrouter" for p, _ in chain)


def test_stage_chain_openrouter_provider_preference():
    cfg = make_cfg(research_provider="openrouter")
    chain = stage_chain(cfg, "research")
    assert chain[0][0] == "openrouter"


def test_resolve_tuple_and_plain_string():
    cfg = make_cfg()
    assert resolve(cfg, ("gemini", "gemini-2.5-flash")) == ("gemini", "gemini-2.5-flash")
    assert resolve(cfg, "gemini-2.5-flash") == ("gemini", "gemini-2.5-flash")
    assert resolve(cfg, "google/gemma-4-26b-a4b-it:free") == ("openrouter", "google/gemma-4-26b-a4b-it:free")


def test_endpoint_and_headers():
    cfg = make_cfg()
    assert endpoint_for(cfg, "gemini") == ("https://generativelanguage.googleapis.com/v1beta/openai", "g-key")
    assert endpoint_for(cfg, "openrouter") == ("https://openrouter.ai/api/v1", "or-key")
    g = headers_for(cfg, "gemini")
    o = headers_for(cfg, "openrouter")
    assert g["Authorization"] == "Bearer g-key"
    assert o["Authorization"] == "Bearer or-key"
    assert "HTTP-Referer" in o and "HTTP-Referer" not in g
