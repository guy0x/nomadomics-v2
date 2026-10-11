"""Draft writer — produces a full voice-matched markdown article.

The active low-cost lane is Gemini Flash Lite, with the configured OpenRouter
free chain as fallback. The article must match the Nomadomics voice
(voice_exemplar.md) and cite every research fact.

The prompt instructs STRICT JSON output (article + word_count + cited facts),
which the tolerant parser then extracts (free models rarely honor json_object).
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
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
        "=== STRUCTURE CONTRACT (non-negotiable) ===\n"
        "- PREFER THE TOP-N LISTICLE when the topic is a list: the WordPress originals "
        "are dominated by 'Top 10 X' / '14 Hacks' formats — use that shape whenever it "
        "fits, with each pick as an H3 + a short paragraph + bullets.\n"
        "- Single H1 = the title. No second H1.\n"
        "- 4+ H2 sections, each a distinct subtopic.\n"
        "- Use H3 sub-headings for list items (products, countries, steps).\n"
        "- UNDER EVERY H3 (and every H2 that lists things), include a bullet list of "
        "3-6 concrete items (- item). No heading should be followed by a bare wall of "
        "prose with no list.\n"
        "- When 2+ alternatives exist (banks, VPNs, cards, cities, plans), include a "
        "Markdown comparison TABLE (| column | column |) with a header row and a "
        "|---| separator row.\n"
        "- Include a 'Pros' and 'Cons' section as bullet lists where a product/service "
        "is compared.\n"
        "- End with a '## Bottom Line' of 3-5 bullet takeaways, then a '## FAQ' with "
        "3+ '### question?' entries.\n"
        "- Concrete numbers: aim 1 specific $/EUR/% figure per H2 section.\n\n"
        "=== VOICE ANCHORS (mirror the WordPress originals) ===\n"
        "- OPEN with a topic-specific money-frame, counterintuitive claim, decision, or "
        "concrete consequence. NEVER begin with 'Picture this', 'Imagine this', or a "
        "generic travel vignette; never copy an exemplar opener.\n"
        "- 2nd person throughout; contractions; em-dashes; parenthetical asides.\n"
        "- Snark at institutions (airlines, banks, the taxman), never at the reader.\n"
        "- Brand names appear naturally in prose (Wise, Revolut, Chase Sapphire) — no "
        "forced lists.\n"
        "- Close with a Bottom Line or an actionable next step, never 'Hope this helps'.\n\n"
        "Return STRICT JSON only: "
        '{"title":"...","markdown":"...","word_count":N,"used_facts":["claim1",...]}\n'
        "The markdown is the full article. Every research fact you use must appear in "
        "used_facts verbatim.\n"
        "CITATIONS (required): the research facts arrive with their source URLs — link "
        "at least two of them inline in the body as markdown links, "
        "[source title](https://...), and end the article with a visible `## Sources` "
        "section containing at least two of those real markdown links. An article "
        "without two real inline citations and two visible source links is not publishable."
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
        client = httpx.Client(timeout=LLM_TIMEOUT)
        own = True

    chain = [(None, model)] if model else stage_chain(cfg, "draft")
    payload = {
        "model": None,  # set per attempt
        "messages": [
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": _build_user_prompt(topic, primary_keyword, research, target_words)},
        ],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
        # Gemini can return HTTP 200 with an empty structured response when the
        # provider's implicit output cap is too small for the 1,800-word JSON
        # article. Bound it explicitly; an empty 200 is then treated as a dead
        # hop and is not retried blindly.
        "max_tokens": 6000,
    }

    budget = StageBudget("draft")
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
                        time.sleep(min(2.0 * (attempt + 1), max(0.0, budget.remaining() - MIN_USABLE_STAGE_SECONDS)))
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
                    draft = _extract_draft(content)
                    if draft.has_content:
                        budget.note(provider, model_id, "200 ok", started, extra=f" — {draft.word_count} words")
                        return draft
                    budget.note(provider, model_id, "200 but empty draft", started)
                    last_err = ValueError("draft parsed to no content")
                    break  # malformed/empty 200: skip this hop, do not burn retries
                except StageDeadlineExceeded as e:
                    # Wedged hop: it spent its whole attempt share (see
                    # llm.attempt_deadline) without answering. Move to the NEXT
                    # hop — a peer that just hung will not answer sooner on a
                    # retry, and a retry would re-pay the share — and let the
                    # run-wide memo bench it if it repeats (llm._record_hang).
                    # Before this clause the exception escaped the hop loop, so
                    # the fallbacks were never tried and the topic died with
                    # most of its stage budget unspent.
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
                    time.sleep(min(1.5 * (attempt + 1), max(0.0, budget.remaining() - MIN_USABLE_STAGE_SECONDS)))
        if budget.expired():
            reason = budget.exhaustion_reason()
            print(f"  [draft] {reason}", file=sys.stderr, flush=True)
            # Chained: the budget message tells the operator the stage was
            # wall-clock-capped; __cause__ keeps the last real error visible.
            if last_err is not None:
                raise StageDeadlineExceeded(reason) from last_err
            raise StageDeadlineExceeded(reason)
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