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
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

from config import Config
import llm
from llm import (
    LLM_TIMEOUT,
    MIN_USABLE_STAGE_SECONDS,
    ProviderAuthError,
    StageBudget,
    StageDeadlineExceeded,
    _hop_benched,
    _record_429,
    _record_hang,
    _record_ok,
    attempt_deadline,
    deadline_post,
    endpoint_for,
    headers_for,
    is_auth_status,
    is_retryable_status,
    MalformedHopResponse,
    is_malformed_hop_response,
    is_transient_hop_error_body,
    resolve,
    should_retry_malformed_hop,
    stage_chain,
    usable_hops_after,
)

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
        client = httpx.Client(timeout=LLM_TIMEOUT)
        own_client = True

    # Explicit model -> single (provider, model). Otherwise the stage chain
    # (Gemini primary -> OpenRouter fallback).
    chain = [(None, model)] if model else stage_chain(cfg, "research")
    payload = {
        "model": None,  # set per attempt
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

    budget = StageBudget("research")
    last_err: Exception | None = None
    try:
        for index, entry in enumerate(chain):
            if budget.expired():
                break
            provider, model_id = resolve(cfg, entry)
            if _hop_benched(provider, model_id):
                # Benched for the rest of the run (see llm._hop_429_strikes):
                # this hop already struck out (429s or wedges) HOP_429_SKIP_THRESHOLD
                # times in a row.
                budget.note(provider, model_id, f"skip — hop benched after {llm.HOP_429_SKIP_THRESHOLD} strikes in a row", time.monotonic())
                continue
            base_url, _ = endpoint_for(cfg, provider)
            headers = headers_for(cfg, provider)
            payload["model"] = model_id
            hops_after = usable_hops_after(cfg, chain, index)
            for attempt in range(max_retries + 1):
                if not budget.take():
                    break
                started = time.monotonic()
                attempt_dl = attempt_deadline(budget, hops_after)
                budget.note(provider, model_id, "posting", started, extra=f"attempt-deadline {attempt_dl:.0f}s", pre=True)
                try:
                    resp = deadline_post(
                        client,
                        f"{base_url}/chat/completions",
                        headers=headers,
                        payload=payload,
                        deadline=attempt_dl,
                    )
                    if is_auth_status(resp.status_code):
                        # Credential rejection: one attempt, no retry, then the
                        # fallback hop. Typed error so callers can distinguish
                        # dead-key from transient failure.
                        _record_ok(provider, model_id)
                        budget.note(provider, model_id, f"{resp.status_code} auth rejected — skipping hop", started)
                        last_err = ProviderAuthError(provider, model_id, resp.status_code)
                        break
                    if resp.status_code == 429:
                        _record_429(provider, model_id)
                        budget.note(provider, model_id, "429 rate-limited — retrying", started)
                        time.sleep(min(1.5 * (attempt + 1), max(0.0, budget.remaining() - MIN_USABLE_STAGE_SECONDS)))
                        continue
                    _record_ok(provider, model_id)
                    if not is_retryable_status(resp.status_code):
                        budget.note(provider, model_id, f"{resp.status_code} non-retryable — skipping hop", started)
                        last_err = RuntimeError(f"{provider}/{model_id} -> HTTP {resp.status_code}")
                        break
                    resp.raise_for_status()
                    data = resp.json()
                    try:
                        content = data["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError) as e:
                        if not is_malformed_hop_response(e):
                            raise  # pragma: no cover — classifier is total over this tuple
                        # 200 without a usable completion — broken hop (invalid
                        # JSON/HTML, empty or streaming-shaped choices). Like a
                        # 404: retrying THIS hop cannot help — unless the body is
                        # a wrapped upstream error (transient), see below.
                        raise MalformedHopResponse(
                            provider, model_id, transient=is_transient_hop_error_body(data)
                        ) from e
                    parsed = _parse_json_response(content)
                    result = ResearchResult(
                        topic=topic,
                        facts=_parse_facts(parsed),
                        keywords=[str(k).strip() for k in parsed.get("keywords", []) or []],
                    )
                    budget.note(provider, model_id, "200 ok", started, extra=f" — {len(result.facts)} facts")
                    return result
                except StageDeadlineExceeded as e:
                    # Wedged hop: it spent its whole attempt share (see
                    # llm.attempt_deadline) without answering. Move to the NEXT
                    # hop — a peer that just hung will not answer sooner on a
                    # retry, and a retry would re-pay the share — and let the
                    # run-wide memo bench it if it repeats (llm._record_hang).
                    # Before this clause the exception escaped the hop loop, so
                    # the fallbacks were never tried and the topic died with
                    # most of its stage budget unspent (2026-09-28: topic 2 died
                    # on hop 1 of 4 with 238s left, t_afaa4c2f).
                    budget.note(provider, model_id, f"error {type(e).__name__}", started, extra=f" — {e}")
                    last_err = e
                    _record_hang(provider, model_id)
                    break
                except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError, MalformedHopResponse) as e:
                    budget.note(provider, model_id, f"error {type(e).__name__}", started, extra=f" — {e}")
                    last_err = e
                    if isinstance(e, MalformedHopResponse):
                        if should_retry_malformed_hop(e, attempt) and not budget.expired():
                            # HTTP 200 wrapping a TRANSIENT upstream error
                            # ("provider_overloaded" 503): the same hop usually
                            # answers a second later (09-22 evidence, t_22a3bbdc).
                            budget.note(provider, model_id, "retrying same hop (transient upstream error in 200)", started)
                            time.sleep(min(1.0, max(0.0, budget.remaining() - MIN_USABLE_STAGE_SECONDS)))
                            continue
                        break  # dead hop (200 sans 'choices') — next hop, no retry
                    time.sleep(min(1.0 * (attempt + 1), max(0.0, budget.remaining() - MIN_USABLE_STAGE_SECONDS)))
            # Tried all retries on this model; move to fallback
        if budget.expired():
            reason = budget.exhaustion_reason()
            print(f"  [research] {reason}", file=sys.stderr, flush=True)
            if last_err is not None:
                raise StageDeadlineExceeded(reason) from last_err
            raise StageDeadlineExceeded(reason)
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