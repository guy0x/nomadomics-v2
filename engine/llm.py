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

import datetime as _dt
import json
import os
import sys
import threading
import time
from pathlib import Path

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
# Below this much remaining stage budget, another attempt is pointless (even the
# 10s connect envelope cannot fit) and backoff sleeps are zeroed: the stage is
# treated as spent and its failure wraps into StageDeadlineExceeded with the
# underlying error as __cause__ (t_02673f32).
MIN_USABLE_STAGE_SECONDS = 5.0
# --- per-attempt share of the stage budget (2026-09-28, t_afaa4c2f) ----------
# `deadline_post` used to be handed `budget.remaining()`, so ONE attempt could
# consume the whole remaining stage — and its StageDeadlineExceeded (a
# RuntimeError, absent from the stages' handler tuples) escaped the hop loop
# entirely, so the fallback hops were never tried. The 09-28 batch died exactly
# that way: topic 1 on hop 4 with 207s unspent, topic 2 on hop 1 of 4 with 238s
# unspent. Each attempt now gets at most this FRACTION of the stage, so at least
# two hops always get a real window — measured healthy hops answer the real
# payload in 39-72s against a 240s research budget.
#
# EXCEPT the last usable hop, which keeps the WHOLE remainder: nothing follows
# it, so a smaller cap could only turn a would-be success into a failure — the
# 09-22 draft stage won through nemotron-3.5-lightning at 315.6s of a 360s
# budget. See attempt_deadline().
ATTEMPT_DEADLINE_FRACTION = 0.5

# --- hop-health memo (2026-09-21, t_02673f32) ---------------------------------
# The 09-21 run burned ~8 attempts on gemma-4:free hops that 429 all day, and a
# dead gemini 401 hop opened every stage. After HOP_429_SKIP_THRESHOLD
# consecutive strikes a hop is benched for the REST OF THE PROCESS (one batch
# run) and later stages skip it instead of re-paying the same dead hop.
# Consecutive (not cumulative): a hop that answers resets its count.
# A "strike" is a 429 OR a wedge — a POST abandoned at its attempt deadline
# (2026-09-28). A wedge costs a whole attempt share of a stage, so it earns the
# same bench: without it one hanging hop re-earns its share in every stage of
# every topic (the 09-28 run paid 207s and 185s to the same hop that way).
HOP_429_SKIP_THRESHOLD = 2
_hop_429_strikes: dict[tuple[str, str], int] = {}


def _hop_path() -> Path:
    """engine/state/hop-health.json — the guard diagnostic's `last journal event`."""
    return Path(__file__).resolve().parent / "state" / "hop-health.json"


def _strike(provider: str, model_id: str, event: str, detail_key: str) -> int:
    """Count a strike; bench the hop process-wide once the threshold trips.

    Best-effort on both the file write and the count: a read-only state dir must
    never break dispatch.
    """
    key = (provider, model_id)
    strikes = _hop_429_strikes.get(key, 0) + 1
    _hop_429_strikes[key] = strikes
    if strikes >= HOP_429_SKIP_THRESHOLD:
        try:
            path = _hop_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                        "event": event,
                        "provider": provider,
                        "model": model_id,
                        detail_key: strikes,
                    }
                )
                + "\n"
            )
        except OSError:
            pass
    return strikes


def _record_429(provider: str, model_id: str) -> int:
    """A 429 strike — retrying the same hop inside a run will not help."""
    return _strike(provider, model_id, "hop_benched_429", "consecutive429")


def _record_hang(provider: str, model_id: str) -> int:
    """A wedge strike — an attempt abandoned at its per-attempt deadline.

    The hop was given a real window (half the stage, or the whole remainder when
    it is the last hop) and spent it without answering, so the stage moves to the
    next hop rather than re-paying it. Two in a row bench it for the run.
    """
    return _strike(provider, model_id, "hop_benched_wedged", "consecutiveWedges")


def _hop_benched(provider: str, model_id: str) -> bool:
    return _hop_429_strikes.get((provider, model_id), 0) >= HOP_429_SKIP_THRESHOLD


def _record_ok(provider: str, model_id: str) -> None:
    """Any non-429 answer ends the hop's consecutive-429 streak."""
    _hop_429_strikes.pop((provider, model_id), None)


def _clear_hop_health() -> None:
    """Test isolation only: reset the process-wide memo."""
    _hop_429_strikes.clear()
    try:
        _hop_path().unlink(missing_ok=True)
    except OSError:
        pass


def _op(value: float | None, default: float) -> float:
    """httpx.Timeout attrs are `float | None` (None = unbounded); coerce."""
    return default if value is None else float(value)


def deadline_post(
    client: httpx.Client,
    url: str,
    *,
    headers: dict,
    payload: dict,
    deadline: float,
) -> httpx.Response:
    """POST with a HARD total deadline bound to the stage budget (t_02673f32).

    httpx's per-operation timeouts cannot preempt an in-flight request (a peer
    that dribbles bytes resets the read timer) — the 09-21 edit stage hung ~33
    minutes inside ONE nemotron:free POST that way, past every engine budget,
    until the shell guard SIGKILLed the batch. This helper joins the worker
    thread with `deadline` seconds and, on expiry, abandons it (daemon threads
    cannot be killed; the socket just stops being waited on) and raises
    StageDeadlineExceeded so the stage falls through to its existing
    budget-exhausted handling.

    `deadline` is the REMAINING stage seconds for this attempt (caller computes
    `budget.seconds - budget.elapsed`). The transport envelope still applies
    within the attempt: the smaller of LLM_TIMEOUT and the remaining time is
    sent per-operation, so a hung peer can never outlive the stage budget.
    """
    if deadline <= 0:
        raise StageDeadlineExceeded("no stage budget left for another attempt")

    # Bound the per-operation envelope by what is actually left, floor 1s so a
    # hairline remaining budget still gets a connect/read attempt.
    inner = httpx.Timeout(
        connect=min(_op(LLM_TIMEOUT.connect, 10.0), deadline),
        read=min(_op(LLM_TIMEOUT.read, 120.0), deadline),
        write=min(_op(LLM_TIMEOUT.write, 10.0), deadline),
        pool=min(_op(LLM_TIMEOUT.pool, 10.0), deadline),
    )

    box: dict = {}
    started = time.monotonic()

    def _run() -> None:
        op_client = client
        try:
            op_client.timeout = inner
        except (AttributeError, ValueError):
            op_client = None  # exotic client: fall back to outer timeout below
        try:
            if op_client is not None:
                box["resp"] = op_client.post(url, json=payload, headers=headers)
            else:
                with httpx.Client(timeout=inner) as c:
                    box["resp"] = c.post(url, json=payload, headers=headers)
        except Exception as e:  # noqa: BLE001 - re-raised on the caller thread
            box["err"] = e

    worker = threading.Thread(target=_run, daemon=True, name="deadline-post")
    worker.start()
    worker.join(deadline)
    if worker.is_alive():
        raise StageDeadlineExceeded(
            f"request exceeded its remaining stage deadline ({deadline:.0f}s) — abandoned in-flight"
        )
    elapsed = time.monotonic() - started
    if "err" in box:
        raise box["err"]
    resp: httpx.Response = box["resp"]
    if elapsed >= deadline - 0.25:
        # Raced the deadline: the response raced back just under the wire.
        # Treat it as a timeout — trusting a response that consumed the whole
        # stage budget would leave nothing for parsing/fallbacks anyway.
        raise StageDeadlineExceeded(f"request consumed its whole {deadline:.0f}s stage deadline")
    return resp


class StageDeadlineExceeded(RuntimeError):
    """A stage spent its whole wall-clock budget without a usable result."""


class ProviderAuthError(RuntimeError):
    """A hop rejected its credentials (HTTP 401/403) — retrying cannot help.

    Carries only the provider/model name and the status code; never key
    material. The structured failure record built from it (see
    auth_failure_record) is what the cron surface greps for rotation alarms.
    """

    def __init__(self, provider: str, model_id: str, status: int) -> None:
        self.provider = provider
        self.model_id = model_id
        self.status = status
        super().__init__(f"{provider}/{model_id} -> HTTP {status} (auth rejected)")


class MalformedHopResponse(RuntimeError):
    """A hop answered HTTP 200 with no OpenAI-shaped 'choices' payload.

    The 09-21 draft batch re-POSTed nemotron-3-super 11 times across the
    edit/writer/research stages: every attempt bought the identical broken
    body (invalid JSON, no 'choices' key), and the old catch-all treated the
    extraction KeyError as transient. Like a 404, retrying the SAME hop
    cannot help — skip to the next one. Carries only provider/model, never
    response bytes.

    `transient` (2026-09-22, t_22a3bbdc) is the one exception: when the 200 body
    is a WRAPPED upstream error (``{"error": {"code": 503, ...}}``) the same hop
    usually answers a second later, so the stage spends one retry on it
    (MALFORMED_HOP_RETRIES) before moving on.
    """

    def __init__(self, provider: str, model_id: str, *, transient: bool = False) -> None:
        self.provider = provider
        self.model_id = model_id
        self.transient = transient
        super().__init__(
            f"{provider}/{model_id} -> 200 body without 'choices' (malformed"
            f"{', transient upstream error' if transient else ''})"
        )


# --- wrapped upstream errors inside a 200 (2026-09-22, t_22a3bbdc) ------------
# OpenRouter serves a provider failure INSIDE an HTTP 200 envelope, e.g.
#   {"error": {"code": 503, "message": "provider_overloaded"}}
# The shape extraction raises MalformedHopResponse and the hop used to be written
# off for the rest of the run — even though the same hop answers a second later
# (evidence: the 09-22 research/draft stages saw nemotron-3-super wrap upstream
# 503s this way). These codes/markers classify such a body as TRANSIENT: exactly
# MALFORMED_HOP_RETRIES same-hop retries, then the next hop. Anything else
# malformed (HTML error page, non-JSON, streaming-shaped choices) keeps the 09-21
# rule — one attempt per hop — because re-POSTing a genuinely dead hop is the
# budget burn that rule exists to stop (t_e4077c91).
TRANSIENT_HOP_ERROR_STATUS = frozenset({408, 429, 500, 502, 503, 504, 520, 522, 524, 529})
TRANSIENT_HOP_ERROR_MARKERS = (
    "overload",
    "temporarily unavailable",
    "try again",
    "timed out",
    "timeout",
    "server error",
)
MALFORMED_HOP_RETRIES = 1


def is_transient_hop_error_body(data) -> bool:
    """True when a 200-shaped body is really a wrapped TRANSIENT upstream error.

    Only the documented OpenRouter error envelope counts: a dict with an
    ``error`` member whose status/code is a transient HTTP status, or whose
    message carries a transient marker. A 200 body that is merely broken shape
    (or carries a non-transient error such as a 401/404) is False — retrying it
    is the 09-21 budget burn.
    """
    if not isinstance(data, dict):
        return False
    err = data.get("error")
    if err is None or isinstance(err, (str,)) and not err.strip():
        return False
    if isinstance(err, dict):
        code = err.get("code", err.get("status"))
        message = err.get("message") or ""
    else:
        code, message = None, err
    if isinstance(code, str) and code.strip().isdigit():
        code = int(code.strip())
    if code in TRANSIENT_HOP_ERROR_STATUS:
        return True
    low = str(message).lower()
    return any(marker in low for marker in TRANSIENT_HOP_ERROR_MARKERS)


def should_retry_malformed_hop(e: BaseException, attempt: int) -> bool:
    """True when a malformed-200 hop deserves one more attempt on the SAME hop.

    `attempt` is the 0-based attempt index inside the hop's retry loop, so
    ``attempt < MALFORMED_HOP_RETRIES`` caps the retries at exactly one.
    """
    return isinstance(e, MalformedHopResponse) and e.transient and attempt < MALFORMED_HOP_RETRIES


def is_malformed_hop_response(e: BaseException) -> bool:
    """True for shape-failures raised on the guarded OpenAI-shape extraction
    line `data["choices"][0]["message"]["content"]`:
      - KeyError("choices") — 200 body without completions (the 09-21
        nemotron-3-super loop, t_e4077c91);
      - KeyError("message") — streaming-shaped body (`choices[0].delta`),
        a real free-provider bug;
      - IndexError          — `choices: []`, empty completions array;
      - TypeError           — non-subscriptable shape (e.g. `choices: 0`).
    The stage guard wraps exactly that one line, so a KeyError/IndexError/
    TypeError raised inside it can only be the response-shape extraction
    failing — never an unrelated bug: those raise elsewhere, unguarded, and
    keep their old behavior.
    """
    return isinstance(e, KeyError | IndexError | TypeError)


AUTH_STATUS = frozenset({401, 403})
GEMINI_KEY_ALARM = "Gemini key invalid - rotation needed"


def is_auth_status(status: int) -> bool:
    """True for credential-rejection statuses (401/403)."""
    return status in AUTH_STATUS


def auth_failure_record(provider: str, model_id: str, status: int, stage: str) -> dict:
    """Structured failure record for an auth-rejected hop.

    Key names only, status codes only — a key value can never land in the
    pipeline journal through this path.
    """
    return {
        "kind": "provider_auth_failure",
        "stage": stage,
        "provider": provider,
        "model": model_id,
        "status": status,
        "alarm": GEMINI_KEY_ALARM if provider == "gemini" else f"{provider} key invalid - rotation needed",
    }


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

    def remaining(self) -> float:
        """Stage seconds left — the hard per-POST deadline for the next attempt."""
        return max(0.0, self.seconds - self.elapsed)

    def expired(self) -> bool:
        spent = self.elapsed >= self.seconds or self.attempts >= self.max_attempts
        if spent:
            return True
        if self.attempts == 0:
            # The stage always gets its first shot; deadline_post hard-caps the
            # POST at whatever remains, even a hairline budget.
            return False
        # Too little left to fit even a connect: another attempt is pointless
        # and backoff would be zeroed anyway — treat the stage as spent so its
        # error surfaces as a budget exhaustion (with the last error as cause).
        return self.remaining() < MIN_USABLE_STAGE_SECONDS

    def take(self) -> bool:
        """Reserve one attempt; False once the budget or attempt cap is spent."""
        if self.expired():
            return False
        self.attempts += 1
        return True

    def note(self, provider: str, model_id: str, status: str, started_at: float, extra: str = "", *, pre: bool = False) -> None:
        """One stderr line per attempt — before this the stages left no trail.

        pre=True journals the attempt BEFORE its POST opens (t_02673f32): the
        09-21 guard diagnostic could only ever see the last COMPLETED attempt,
        so a stage that went silent inside one in-flight request (nemotron:free,
        ~33 min) left no trace of which hop was in-flight. The OPEN line is
        timestamped and flushed so it survives a SIGKILL.
        """
        if pre:
            # `extra` carries the attempt's OWN deadline (llm.attempt_deadline),
            # which is now smaller than the stage remainder — the 09-28 batch's
            # post-mortem could only see the stage budget and misread which bound
            # fired, so both are printed.
            tail = f" [{extra}]" if extra else ""
            print(
                f"  [{self.stage}] {provider}/{model_id} attempt {self.attempts} -> OPEN "
                f"(stage {self.remaining():.0f}s left) {status}{tail} "
                f"@ {_dt.datetime.now(_dt.timezone.utc).isoformat()}",
                file=sys.stderr,
                flush=True,
            )
            return
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


def usable_hops_after(cfg: Config, chain: list, index: int) -> int:
    """How many hops AFTER ``chain[index]`` can still serve this run.

    Fed to attempt_deadline(). A hop already benched (see _hop_benched) will be
    skipped, so it must not make the current attempt look like it has a fallback
    behind it — otherwise a stage would hand its whole remainder to a hop that is
    in fact the last one it can still use.
    """
    return sum(1 for entry in chain[index + 1 :] if not _hop_benched(*resolve(cfg, entry)))


def attempt_deadline(budget: StageBudget, hops_after: int) -> float:
    """Seconds to grant ONE POST out of the stage's remaining wall clock.

    ``min(remaining, budget.seconds * ATTEMPT_DEADLINE_FRACTION)`` while another
    usable hop follows; the WHOLE remainder when this is the last one (nothing
    can be saved for a hop that does not exist, and capping the last hop could
    only convert a slow success into a failure).

    The cap is what stops one wedged hop from consuming a stage: its
    StageDeadlineExceeded is caught by the stage, which moves to the next hop.
    """
    remaining = budget.remaining()
    if hops_after <= 0:
        return remaining
    return min(remaining, budget.seconds * ATTEMPT_DEADLINE_FRACTION)


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
