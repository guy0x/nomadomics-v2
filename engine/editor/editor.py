"""Editor stage — voice/structure/grounding QA pass.

Pipeline position (2b): research -> draft -> **edit** -> SEO/confidence -> policy.

The editor runs on the edit model (Gemini flash primary, OpenRouter fallback) and
must, without inventing new facts:
  1. Check voice adherence vs `voice_exemplar.md` + `brand_system.md` (2nd person,
     punchline-first open, concrete $/% numbers early, no weasel words, no filler
     intro, snark at institutions never the reader);
  2. Tighten structure (single H1, 4+ H2, H3 items, FAQ, "Bottom line" close);
  3. Confirm every research fact used stays grounded (no new unsourced claims);
  4. Return EditedDraft(markdown, word_count, edit_report) — the SEO/confidence
     scorer then scores the EDITED draft.
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
from llm import endpoint_for, headers_for, resolve, stage_chain
from research.research import ResearchResult
from writer.writer import ArticleDraft, _load_prompt

EDIT_SYSTEM_PROMPT = """You are the Nomadomics senior editor. Polish an article draft into publish shape
while preserving its facts. You are the final QA gate before a deterministic SEO
scorer and a confidence-based publish policy run on the result.

Hard rules:
- Keep 2nd person ("you/your"). Confident, witty, mildly snarky at institutions —
  NEVER at the reader.
- Lead with the punchline (a concrete $/€/% saving, benefit, or counterintuitive truth).
- Keep at least 3 specific dollar/euro/percent numbers in the first 500 words.
- No "In this article…" / "Let's explore…" filler. No hedging weasel words
  ("might", "could possibly", "some say").
- Single H1 = title. 4+ H2 sections. Use H3 sub-headings for list items.
- STRUCTURE CONTRACT (enforce, add where missing): every H3 and list-style H2 must be
  followed by a bullet list of 3-6 concrete items; add a Markdown comparison table
  (| col | col | + |---| row) wherever 2+ alternatives exist; add Pros/Cons bullet
  lists where a product/service is compared; close with "## Bottom Line" (3-5 bullets)
  and a "## FAQ" with 3+ "### question?" entries.
- DO NOT invent new facts, stats, prices, or URLs. Only use what is already in the
  draft or the provided research facts. If a claim is unsupported, soften or drop it.
- Fix only: structure, voice, flow, clarity, and factual grounding. Keep every
  substantive fact the draft already cites.

Return STRICT JSON only:
{"markdown": "<full corrected article>", "edit_report": "<2-4 bullets: what you changed and why>"}
"""


@dataclass
class EditedDraft:
    markdown: str = ""
    word_count: int = 0
    used_facts: list[str] = field(default_factory=list)
    edit_report: str = ""

    @property
    def has_content(self) -> bool:
        return len(self.markdown.strip()) >= 500


def _build_edit_prompt(topic: str, primary_keyword: str, draft: ArticleDraft, research: ResearchResult) -> str:
    facts = "\n".join(f"- {f.claim}  (source: {f.source_url})" for f in research.facts)
    return (
        f"TOPIC: {topic}\n"
        f"PRIMARY KEYWORD: {primary_keyword}\n\n"
        "=== GROUND-TRUTH RESEARCH FACTS (the ONLY facts allowed) ===\n"
        f"{facts}\n\n"
        "=== DRAFT TO EDIT ===\n"
        f"{draft.markdown}\n\n"
        "Polish the draft now per the rules and return the strict JSON."
    )


def _extract_edit(content: str, original: ArticleDraft) -> EditedDraft:
    """Tolerant JSON extraction (mirrors writer/research parsers). Falls back to
    the original draft unchanged if the edit output is unparseable."""
    text = (content or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fence:
        text = fence.group(1).strip()
    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        pass
    if not isinstance(parsed, dict):
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict):
        return EditedDraft(
            markdown=original.markdown,
            word_count=original.word_count,
            used_facts=list(original.used_facts),
            edit_report="edit output unparseable — kept original draft",
        )
    md = str(parsed.get("markdown", "")).strip()
    if len(md) < 500:
        md = original.markdown
    wc = len(md.split()) or original.word_count
    report = str(parsed.get("edit_report", "")).strip()
    return EditedDraft(
        markdown=md,
        word_count=wc,
        used_facts=list(original.used_facts),
        edit_report=report or "no report",
    )


def edit_draft(
    draft: ArticleDraft,
    topic: str,
    primary_keyword: str,
    research: ResearchResult,
    *,
    config: Optional[Config] = None,
    http_client: Optional[httpx.Client] = None,
    model: Optional[str] = None,
    max_retries: int = 1,
) -> EditedDraft:
    cfg = config or __import__("config", fromlist=["load_config"]).load_config()
    client = http_client
    own = False
    if client is None:
        client = httpx.Client(timeout=180)
        own = True

    chain = [(None, model)] if model else stage_chain(cfg, "edit")
    payload = {
        "model": None,
        "messages": [
            {"role": "system", "content": EDIT_SYSTEM_PROMPT},
            {"role": "user", "content": _build_edit_prompt(topic, primary_keyword, draft, research)},
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }

    last_err: Exception | None = None
    try:
        for entry in chain:
            provider, model_id = resolve(cfg, entry)
            base_url, _ = endpoint_for(cfg, provider)
            headers = headers_for(cfg, provider)
            payload["model"] = model_id
            for attempt in range(max_retries + 1):
                try:
                    resp = client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
                    if resp.status_code == 429:
                        time.sleep(2.0 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    edited = _extract_edit(content, draft)
                    if edited.has_content:
                        return edited
                    last_err = ValueError("edit parsed to no content")
                except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError, KeyError) as e:
                    last_err = e
                    time.sleep(1.5 * (attempt + 1))
    finally:
        if own:
            client.close()

    # Degrade gracefully: if the editor fails entirely, keep the writer's draft
    # rather than dropping the article. Record the failure in the report.
    return EditedDraft(
        markdown=draft.markdown,
        word_count=draft.word_count,
        used_facts=list(draft.used_facts),
        edit_report=f"editor unavailable ({last_err}) — kept original draft",
    )
