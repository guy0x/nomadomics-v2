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
    auth_failure_record,
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
    # Populated only when the hop degraded on a credential rejection (401/403):
    # the structured, key-material-free failure record that lands in the pipeline
    # journal. None on the healthy path.
    failure_record: Optional[dict] = None

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
        client = httpx.Client(timeout=LLM_TIMEOUT)
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

    budget = StageBudget("edit")
    last_err: Exception | None = None
    auth_failures: list[dict] = []  # structured records for degraded-hop reporting
    try:
        for index, entry in enumerate(chain):
            if budget.expired():
                break
            provider, model_id = resolve(cfg, entry)
            if _hop_benched(provider, model_id):
                # Benched for the rest of the run: this hop already struck out
                # (429s or wedges) HOP_429_SKIP_THRESHOLD times in a row in
                # earlier stages (the 09-21 run paid ~8 attempts to the same
                # dead gemma:free hops across stages). No attempt, no sleep.
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
                        # Credential rejection: one attempt, no retry, no key
                        # material in any message — then the fallback hop.
                        _record_ok(provider, model_id)
                        budget.note(provider, model_id, f"{resp.status_code} auth rejected — skipping hop", started)
                        rec = auth_failure_record(provider, model_id, resp.status_code, "edit")
                        auth_failures.append(rec)
                        # Crisp, single-line alarm at detection time — the cron
                        # surface greps this even if a fallback hop saves the run.
                        print(f"  [edit] ALARM: {rec['alarm']} ({rec['provider']}/{rec['model']} HTTP {rec['status']})", file=sys.stderr, flush=True)
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
                    edited = _extract_edit(content, draft)
                    if edited.has_content:
                        budget.note(provider, model_id, "200 ok", started, extra=f" — {edited.word_count} words")
                        return edited
                    budget.note(provider, model_id, "200 but empty edit", started)
                    last_err = ValueError("edit parsed to no content")
                except StageDeadlineExceeded as e:
                    # Wedged hop: it spent its whole attempt share (see
                    # llm.attempt_deadline) without answering. Move to the NEXT
                    # hop — a peer that just hung will not answer sooner on a
                    # retry, and a retry would re-pay the share — and let the
                    # run-wide memo bench it if it repeats (llm._record_hang).
                    # Before this clause the exception escaped the hop loop and
                    # the remaining hops were never tried.
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
            print(f"  [edit] {budget.exhaustion_reason()}", file=sys.stderr, flush=True)
            last_err = last_err or StageDeadlineExceeded(f"edit: {budget.exhaustion_reason()}")
    finally:
        if own:
            client.close()

    # Degrade gracefully: if the editor fails entirely, keep the writer's draft
    # rather than dropping the article. Record the failure in the report.
    report = f"editor unavailable ({last_err}) — kept original draft"
    failure_record: dict | None = None
    if auth_failures:
        # Structured, key-material-free degradation record for the pipeline journal;
        # the rotation alarm line itself was already emitted when the hop was rejected.
        failure_record = {
            "kind": "stage_degraded_auth",
            "stage": "edit",
            "outcome": "kept_original_draft",
            "hops": auth_failures,
            "error": str(last_err),
        }
        report = f"{report} | auth_failure: {json.dumps(failure_record)}"
    return EditedDraft(
        markdown=draft.markdown,
        word_count=draft.word_count,
        used_facts=list(draft.used_facts),
        edit_report=report,
        failure_record=failure_record,
    )
