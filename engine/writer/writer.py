"""Draft writer — produces a full voice-matched markdown article via OpenRouter :free.

Per Guy's 2026-08-11 rule, drafting uses a FREE model (default
`google/gemma-4-26b-a4b-it:free`, verified working live). The article must match
the Nomadomics voice (voice_exemplar.md) and cite every research fact.

The prompt instructs STRICT JSON output (article + word_count + cited facts),
which the tolerant parser then extracts (free models rarely honor json_object).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from config import Config
from research.research import Fact, ResearchResult

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass
class ArticleDraft:
    markdown: str = ""
    word_count: int = 0
    used_facts: list[str] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return len(self.markdown.strip()) >= 500


def _load_prompt(name: str) -> str:
    p = PROMPTS_DIR / name
    return p.read_text() if p.exists() else ""


def _build_system_prompt() -> str:
    voice = _load_prompt("voice_exemplar.md")
    return (
        "You are the Nomadomics senior travel-finance writer. Write a long-form SEO "
        "guide in the house voice defined below. Follow the voice exemplar strictly.\n\n"
        "=== VOICE EXEMPLAR ===\n"
        f"{voice}\n"
        "=== END VOICE EXEMPLAR ===\n\n"
        "Return STRICT JSON only: "
        '{"title":"...","markdown":"...","word_count":N,"used_facts":["claim1",...]}\n'
        "The markdown is the full article (H1, H2 sections, H3 items, FAQ, bottom-line). "
        "Every research fact you use must appear in used_facts verbatim."
    )


def _build_user_prompt(topic: str, primary_keyword: str, research: ResearchResult, target_words: int) -> str:
    facts = "\n".join(
        f"- {f.claim}  (source: {f.source_url})"
        for f in research.facts
    )
    return (
        f"TOPIC: {topic}\n"
        f"PRIMARY KEYWORD: {primary_keyword}\n"
        f"TARGET WORD COUNT: ~{target_words}\n\n"
        "RESEARCH FACTS (cite these, all are verified):\n"
        f"{facts}\n\n"
        "Write the article now in the Nomadomics voice, incorporate the research facts "
        "naturally (fold into prose, parenthetical year), and return the strict JSON."
    )


def _extract_draft(content: str) -> ArticleDraft:
    """Tolerant extraction of the article JSON (mirrors research parser)."""
    text = (content or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fence:
        text = fence.group(1).strip()
    parsed = None
    for attempt in (lambda: json.loads(text),):
        try:
            parsed = attempt()
            break
        except json.JSONDecodeError:
            pass
    if parsed is None:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict):
        return ArticleDraft()

    md = str(parsed.get("markdown", "")).strip()
    wc = int(parsed.get("word_count") or 0)
    if wc <= 0:
        wc = len(md.split())
    used = [str(x) for x in parsed.get("used_facts", []) or []]
    return ArticleDraft(markdown=md, word_count=wc, used_facts=used)


def _fallback_models(cfg: Config) -> list[str]:
    seen = []
    for m in (cfg.draft_model,) + cfg.fallback_models:
        if m not in seen:
            seen.append(m)
    return seen


def draft_article(
    topic: str,
    primary_keyword: str,
    research: ResearchResult,
    *,
    target_words: int = 1800,
    config: Optional[Config] = None,
    http_client: Optional[httpx.Client] = None,
    model: Optional[str] = None,
    max_retries: int = 2,
) -> ArticleDraft:
    cfg = config or __import__("config", fromlist=["load_config"]).load_config()
    client = http_client
    own = False
    if client is None:
        client = httpx.Client(timeout=180)
        own = True

    payload = {
        "model": None,  # set per attempt
        "messages": [
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": _build_user_prompt(topic, primary_keyword, research, target_words)},
        ],
        "temperature": 0.7,
    }
    headers = {
        "Authorization": f"Bearer {cfg.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://nomadomics.local",
        "X-Title": "Nomadomics Engine",
    }

    models = [model] if model else _fallback_models(cfg)
    last_err: Exception | None = None
    try:
        for model_id in models:
            payload["model"] = model_id
            for attempt in range(max_retries + 1):
                try:
                    resp = client.post(f"{cfg.openrouter_base_url}/chat/completions", json=payload, headers=headers)
                    if resp.status_code == 429:
                        time.sleep(2.0 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    draft = _extract_draft(content)
                    if draft.has_content:
                        return draft
                    last_err = ValueError("draft parsed to no content")
                except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                    last_err = e
                    time.sleep(1.5 * (attempt + 1))
        if last_err:
            raise last_err
    finally:
        if own:
            client.close()

    return ArticleDraft()


def ensure_research_cited(draft: ArticleDraft, research: ResearchResult, min_cited: int = 2) -> tuple[bool, list[str]]:
    """Verify at least `min_cited` distinct research facts appear in the draft.

    Compares each fact's claim (first ~40 chars, normalized) against the draft body.
    Returns (ok, cited_claims).
    """
    body = draft.markdown.lower()
    cited = []
    for f in research.facts:
        norm = f.claim.strip().lower().replace("\n", " ")[:60]
        if norm[:40] in body:
            cited.append(f.claim)
    return (len(cited) >= min_cited, cited)