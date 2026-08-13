"""Research module — gathers cited facts for a topic via OpenRouter :free models.

Per Guy's 2026-08-11 rule, this stage uses a FREE model (default
`qwen/qwen3-32b:free`). No paid models in this stage. On :free rate-limit (429)
we retry with backoff then walk the fallback chain; on total failure we return
an empty result (the pipeline marks the Topic failed, never silently proceeds).

The model is instructed to return STRICT JSON:
{
  "topic": "...",
  "facts": [
    {"claim": "...", "why_it_matters": "...", "source_title": "...",
     "source_url": "https://...", "published_date": "YYYY-MM-DD", "confidence": "high|medium|low"}
  ],
  "keywords": ["..."]
}
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from config import Config

RESEARCH_SYSTEM_PROMPT = """You are a travel-finance research assistant for a money-savvy travel blog (Nomadomics).

Given a topic and target keyword, find 3-6 recent, credible facts relevant to budget travel,
digital nomad finance, or money-saving for travelers. Prefer primary or high-quality secondary
sources. Return STRICT JSON only, no prose, no markdown, matching exactly:

{
  "topic": "string",
  "facts": [
    {
      "claim": "Concise quotable claim (1-2 sentences)",
      "why_it_matters": "Why this matters for budget travelers/nomads (1 sentence)",
      "source_title": "Publisher or article title",
      "source_url": "Direct https URL",
      "published_date": "YYYY-MM-DD if visible else null",
      "confidence": "high|medium|low"
    }
  ],
  "keywords": ["3-7 short keywords"]
}

Rules:
- At least 3 facts. Each fact MUST have a real source_url.
- Prefer items published within the last 24 months when possible.
- No speculation, no invented URLs. If you cannot verify, say so in a fact with confidence low.
"""


@dataclass
class Fact:
    claim: str
    why_it_matters: str = ""
    source_title: str = ""
    source_url: str = ""
    published_date: Optional[str] = None
    confidence: str = "medium"


@dataclass
class ResearchResult:
    topic: str = ""
    facts: list[Fact] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    @property
    def has_valid_research(self) -> bool:
        return len(self.facts) >= 3 and all(f.source_url for f in self.facts)


def _parse_json_response(content: str) -> dict:
    """Tolerant JSON extraction from an LLM response (strip fences, handle arrays/
    prose-wrapped output). Returns a dict with at least the keys the caller needs.
    """
    text = (content or "").strip()
    # Strip markdown code fences
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fence:
        text = fence.group(1).strip()

    parsed = None
    # Try direct parse (object or array)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try first {...} block
    if parsed is None:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = None
    # Free models sometimes wrap the object in an array [{...}]
    if parsed is None:
        m = re.search(r"\[.*\]", text, flags=re.S)
        if m:
            try:
                arr = json.loads(m.group(0))
                if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                    parsed = arr[0]
            except json.JSONDecodeError:
                parsed = None

    if not isinstance(parsed, dict):
        return {}
    return parsed


def _parse_facts(raw: dict) -> list[Fact]:
    facts: list[Fact] = []
    for f in raw.get("facts", []) or []:
        facts.append(
            Fact(
                claim=str(f.get("claim", "")).strip(),
                why_it_matters=str(f.get("why_it_matters", "")).strip(),
                source_title=str(f.get("source_title", "")).strip(),
                source_url=str(f.get("source_url", "")).strip(),
                published_date=f.get("published_date"),
                confidence=str(f.get("confidence", "medium")),
            )
        )
    return facts


def _check_freshness(result: ResearchResult, max_months: int = 24) -> list[str]:
    """Warnings for stale facts (> max_months old). Does not reject by default."""
    warnings: list[str] = []
    cutoff = date.today() - timedelta(days=max_months * 30)
    for f in result.facts:
        if not f.published_date:
            continue
        try:
            d = datetime.fromisoformat(f.published_date).date()
            if d < cutoff:
                warnings.append(f"stale source ({f.published_date}): {f.source_title}")
        except ValueError:
            warnings.append(f"unparseable date '{f.published_date}': {f.source_title}")
    return warnings


def _fallback_models(cfg: Config) -> list[str]:
    seen = []
    for m in (cfg.research_model,) + cfg.fallback_models:
        if m not in seen:
            seen.append(m)
    return seen


def research_topic(
    topic: str,
    primary_keyword: str = "",
    *,
    config: Optional[Config] = None,
    http_client: Optional[httpx.Client] = None,
    model: Optional[str] = None,
    max_retries: int = 2,
) -> ResearchResult:
    """Fetch research for a topic via OpenRouter :free model.

    If `http_client` is provided (tests inject a mock), use it. Otherwise create
    a real client from config.
    """
    cfg = config or __import__("config", fromlist=["load_config"]).load_config()
    client = http_client
    own_client = False
    if client is None:
        client = httpx.Client(timeout=60)
        own_client = True

    models_to_try = [model] if model else _fallback_models(cfg)
    payload = {
        "model": models_to_try[0],
        "messages": [
            {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n"
                    f"Target keyword: {primary_keyword}\n\n"
                    "Return the strict JSON research result now."
                ),
            },
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {cfg.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://nomadomics.local",
        "X-Title": "Nomadomics Engine",
    }

    last_err: Exception | None = None
    try:
        for model_id in models_to_try:
            payload["model"] = model_id
            for attempt in range(max_retries + 1):
                try:
                    resp = client.post(f"{cfg.openrouter_base_url}/chat/completions", json=payload, headers=headers)
                    if resp.status_code == 429:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = _parse_json_response(content)
                    result = ResearchResult(
                        topic=topic,
                        facts=_parse_facts(parsed),
                        keywords=[str(k).strip() for k in parsed.get("keywords", []) or []],
                    )
                    return result
                except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                    last_err = e
                    time.sleep(1.0 * (attempt + 1))
            # Tried all retries on this model; move to fallback
        if last_err:
            raise last_err
    finally:
        if own_client:
            client.close()

    return ResearchResult(topic=topic)


def validate_research(result: ResearchResult, min_facts: int = 3) -> tuple[bool, list[str], list[str]]:
    """Quality gate. Returns (is_valid, errors, warnings).

    Valid requires >= min_facts facts, all with source_url. Freshness issues
    become warnings, not rejections (older evergreen data can still be useful).
    """
    errors: list[str] = []
    if len(result.facts) < min_facts:
        errors.append(f"only {len(result.facts)} facts (need >= {min_facts})")
    for i, f in enumerate(result.facts):
        if not f.source_url:
            errors.append(f"fact[{i}] missing source_url")
        if not f.claim:
            errors.append(f"fact[{i}] missing claim")
    warnings = _check_freshness(result)
    return (not errors, errors, warnings)