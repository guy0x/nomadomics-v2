"""Corpus-repetition gate + LLM style judge (kanban t_252b48e7, 2026-10-12).

Guy's MCQ verdict: BOTH mechanisms. Evidence base: "Picture this, you" opened
13 published articles identically and "vibrant" appears in 29 of 50 published
articles, while the retired regex bans only two named openers.

Pinned here:

* `invariants.corpus_repetition_issues` — the deterministic gate: any opener
  3-gram already used by >= 2 published bodies is a repeated opener template,
  and >= 2 distinct seeded cliché phrases fail on density.
* `article_invariant_errors(published_corpus=...)` — wiring; the gate is inert
  without a corpus (the draft lane has no body corpus in reach).
* `publish.style_judge_gate` / `publish._parse_style_judge` — the bounded LLM
  pass, strict-JSON verdict, FAIL CLOSED on transport/parse/ambiguity.

Run:  cd ~/nomadomics-v2 && env -u PYTHONPATH .venv/bin/python -m pytest \
          engine/tests/test_repetition_gate.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import invariants  # noqa: E402
from invariants import (  # noqa: E402
    article_invariant_errors,
    cliche_issues,
    corpus_repetition_issues,
)
import publish  # noqa: E402


def body_with_opener(opener: str) -> str:
    return (
        f"# A guide\n\n{opener}\n\n"
        "The fee is $10 and the threshold is $20.\n\n"
        "## Sources\n\n"
        "- [IRS A](https://irs.gov/a)\n"
        "- [State B](https://travel.state.gov/b)\n"
    )


CORPUS_OPENER = "Picture this: you land in Lisbon with"
CORPUS = [
    {"slug": "a", "bodyMarkdown": body_with_opener(CORPUS_OPENER + " one.")},
    {"slug": "b", "bodyMarkdown": body_with_opener(CORPUS_OPENER + " two.")},
    {"slug": "c", "bodyMarkdown": body_with_opener(CORPUS_OPENER + " three.")},
]


# --- n-gram gate ---------------------------------------------------------------

def test_duplicate_opener_3gram_fails():
    new = body_with_opener(CORPUS_OPENER + " again.")
    issues = corpus_repetition_issues(new, CORPUS)
    assert any(
        "opener 3-gram" in i and "already used by" in i for i in issues
    ), issues


def test_unique_opener_passes():
    new = body_with_opener("A $20 fee can erase a week of savings.")
    assert corpus_repetition_issues(new, CORPUS) == []


def test_opener_gate_needs_at_least_three_corpus_bodies():
    """Below OPENER_MIN_CORPUS a shared 3-gram proves nothing and stays inert."""
    new = body_with_opener(CORPUS_OPENER + " again.")
    two = CORPUS[:2]
    assert corpus_repetition_issues(new, two) == []
    assert corpus_repetition_issues(new, CORPUS)  # and three bodies flag it


def test_own_slug_is_excluded_from_corpus():
    """The article's own published row must not count toward the repetition census.

    The opener gram appears in the corpus ONLY in the article's own row and one
    other: with exclusion the count is 1 (inert), without it the self row makes
    2 and would falsely flag.
    """
    new = body_with_opener(CORPUS_OPENER + " again.")
    corpus = [
        {"slug": "new-slug", "bodyMarkdown": new},               # own row
        {"slug": "twin", "bodyMarkdown": body_with_opener(CORPUS_OPENER + " twin.")},
        {"slug": "filler-a", "bodyMarkdown": body_with_opener("A $20 fee can erase savings.")},
        {"slug": "filler-b", "bodyMarkdown": body_with_opener("Visa runs cost money.")},
    ]
    assert corpus_repetition_issues(new, corpus, own_slug="new-slug") == []
    # And the same corpus without exclusion flags it (count includes the self row).
    assert corpus_repetition_issues(new, corpus)


def test_corpus_rows_without_bodies_are_ignored():
    new = body_with_opener("A $20 fee can erase a week of savings.")
    rows = [{"slug": "x", "bodyMarkdown": ""}, {"slug": "y"}]
    assert corpus_repetition_issues(new, rows) == []


def test_gate_runs_case_insensitively():
    new = body_with_opener(CORPUS_OPENER.upper() + " again.")
    assert corpus_repetition_issues(new, CORPUS)


# --- cliche census ---------------------------------------------------------------

def test_cliche_threshold_one_phrase_passes():
    body = "The old town boasts a market and the fee is $10."
    assert cliche_issues(body) == []


def test_cliche_threshold_two_distinct_phrases_fail():
    body = "This vibrant city boasts a market and the fee is $10."
    issues = cliche_issues(body)
    assert len(issues) == 1
    assert "cliche density over threshold" in issues[0]


def test_cliche_repeat_hits_of_one_phrase_still_pass():
    """The threshold counts DISTINCT phrases, not raw hits."""
    body = "The market boasts space, boasts history, boasts prices."
    assert cliche_issues(body) == []


def test_cliche_gate_is_case_insensitive():
    body = "A Vibrant Hidden Gem — this city boasts a market."
    assert cliche_issues(body)


def test_cliche_seed_list_covers_the_evidence_terms():
    for phrase in ("vibrant", "boasts", "nestled", "hidden gem",
                   "look no further", "game-changer", "when it comes to"):
        assert phrase in invariants.CLICHE_PHRASES


# --- article_invariant_errors wiring ---------------------------------------------

def _clean_article(body: str) -> dict:
    return {
        "excerpt": "A real excerpt sentence.",
        "metaTitle": "A title",
        "metaDescription": (
            "Living costs, visa rules and internet speeds differ in every hub. "
            "This guide compares the practical numbers so you can pick a base "
            "before you book a flight."
        ),
        "slug": "new-slug",
        "bodyMarkdown": body,
    }


def test_article_gate_flags_duplicate_opener_only_with_corpus():
    new = body_with_opener(CORPUS_OPENER + " again.")
    # Without a corpus (draft lane) the gate is inert.
    assert not any(
        "opener 3-gram" in e
        for e in article_invariant_errors(_clean_article(new))
    )
    # With the corpus (publish lane) the named failure appears.
    errors = article_invariant_errors(
        _clean_article(new), published_corpus=CORPUS
    )
    assert any("opener 3-gram" in e and "already used by" in e for e in errors)


def test_article_gate_flags_cliche_overload_with_corpus():
    body = (
        "# Guide\n\nThis vibrant city boasts a market; the fee is $10.\n\n"
        "## Sources\n\n"
        "- [IRS A](https://irs.gov/a)\n"
        "- [State B](https://travel.state.gov/b)\n"
    )
    errors = article_invariant_errors(
        _clean_article(body), published_corpus=CORPUS
    )
    assert any("cliche density over threshold" in e for e in errors)


def test_article_gate_clean_article_still_passes_with_corpus():
    new = body_with_opener("A $20 fee can erase a week of savings.")
    assert article_invariant_errors(
        _clean_article(new), published_corpus=CORPUS
    ) == []


# --- LLM style judge ---------------------------------------------------------------

def test_parse_style_judge_accepts_strict_verdict():
    verdict = publish._parse_style_judge(
        '{"cliche_flags": ["vibrant"], "voice_match": "pass", "reasons": []}'
    )
    assert verdict == {"cliche_flags": ["vibrant"], "voice_match": "pass", "reasons": []}


def test_parse_style_judge_strips_markdown_fence():
    verdict = publish._parse_style_judge(
        '```json\n{"cliche_flags": [], "voice_match": "fail", "reasons": ["drift"]}\n```'
    )
    assert verdict is not None
    assert verdict["voice_match"] == "fail"


def test_parse_style_judge_malformed_json_is_none_fail_closed():
    assert publish._parse_style_judge("not json at all") is None
    assert publish._parse_style_judge('{"voice_match":}') is None
    assert publish._parse_style_judge("") is None


def test_parse_style_judge_missing_or_unknown_voice_match_is_none():
    assert publish._parse_style_judge('{"cliche_flags": [], "reasons": []}') is None
    assert publish._parse_style_judge(
        '{"cliche_flags": [], "voice_match": "uncertain", "reasons": []}'
    ) is None


class _CannedJudgeClient:
    """httpx.Client double returning a canned completion for every POST."""

    def __init__(self, content: str, calls: list | None = None):
        self.content = content
        self.calls = calls if calls is not None else []

    class _Response:
        status_code = 200
        _content: str = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": self._content}}]}

    def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "payload": json, "headers": headers})
        resp = self._Response()
        resp._content = self.content
        return resp

    def close(self):
        pass


def _gate_with_canned(monkeypatch, content: str) -> tuple[dict, _CannedJudgeClient]:
    client = _CannedJudgeClient(content)
    monkeypatch.setattr(publish.httpx, "Client", lambda *a, **k: client)
    out = publish.style_judge_gate(
        {"bodyMarkdown": body_with_opener("A $20 fee stings.")}, cfg=None
    )
    return out, client


def test_style_judge_gate_empty_body_fails_closed():
    out = publish.style_judge_gate({"bodyMarkdown": "  "}, cfg=None)
    assert out["ok"] is False
    assert "empty body" in out["errors"][0]


def test_style_judge_gate_passes_on_pass_verdict(monkeypatch):
    out, client = _gate_with_canned(
        monkeypatch,
        '{"cliche_flags": [], "voice_match": "pass", "reasons": []}',
    )
    assert out["ok"] is True
    assert out["verdict"]["voice_match"] == "pass"
    # One attempt, on the edit chain, auth header present but never printed.
    assert len(client.calls) == 1
    assert client.calls[0]["payload"]["response_format"] == {"type": "json_object"}
    auth = client.calls[0]["headers"].get("Authorization", "")
    assert auth.startswith("Bearer ") and len(auth) > len("Bearer ")


def test_style_judge_gate_fails_on_fail_verdict(monkeypatch):
    out, _client = _gate_with_canned(
        monkeypatch,
        '{"cliche_flags": ["vibrant"], "voice_match": "fail", '
        '"reasons": ["cliche opener", "corporate register"]}',
    )
    assert out["ok"] is False
    assert "voice_match=fail" in out["errors"][0]
    assert "cliche opener" in out["errors"][0]


def test_style_judge_gate_malformed_reply_fails_closed(monkeypatch):
    """A 200 whose body is not a parseable verdict is a block, not a pass.

    The walk gives ONE attempt per chain hop; the production Gemini edit chain
    is a single hop, so one unparseable 200 exhausts it and the gate blocks.
    """
    out, client = _gate_with_canned(monkeypatch, "I think it reads fine!")
    assert out["ok"] is False
    assert "fail closed" in out["errors"][0]
    assert len(client.calls) == 1


def test_style_judge_gate_no_verdict_fails_closed(monkeypatch):
    """Every hop dead/unparseable -> the gate blocks, never waves through."""
    monkeypatch.setattr(publish, "stage_chain", lambda cfg, stage: [("gemini", "gemini-flash-lite-latest")])

    class DeadClient:
        def post(self, *a, **k):
            raise publish.httpx.ConnectError("network down")

        def close(self):
            pass

    monkeypatch.setattr(publish.httpx, "Client", lambda *a, **k: DeadClient())
    out = publish.style_judge_gate(
        {"bodyMarkdown": body_with_opener("A $20 fee stings.")}, cfg=None
    )
    assert out["ok"] is False
    assert "fail closed" in out["errors"][0]


def test_style_judge_gate_uses_a_bounded_stage_budget():
    """The judge runs under its own StageBudget — never an unbounded walk."""
    assert publish.STYLE_JUDGE_BUDGET_SECONDS > 0
    budget = publish.StageBudget(
        publish.STYLE_JUDGE_STAGE,
        seconds=publish.STYLE_JUDGE_BUDGET_SECONDS,
        max_attempts=2,
    )
    assert budget.seconds == publish.STYLE_JUDGE_BUDGET_SECONDS
    assert budget.max_attempts == 2


def test_publish_one_refuses_when_style_judge_blocks(monkeypatch, tmp_path):
    """End to end: a judge fail verdict skips the publish and journals it."""
    from test_quarantine_gate import FakeClient, make_article  # reuse the fixture

    for attr in ("PUBLISH_STATE_FILE", "SHARED_LEDGER", "DRAFT_JOURNAL",
                 "RELEASE_APPROVALS", "SNAPSHOT", "PUBLIC_CARDS", "PUBLIC_OG"):
        monkeypatch.setattr(publish, attr, tmp_path / attr)
    monkeypatch.setattr(publish, "browser_asset_ready", lambda s: (True, "fixture receipt"))
    monkeypatch.setattr(publish, "_published_slugs", lambda *a, **k: set())
    monkeypatch.setattr(publish, "polish_article", lambda *a, **k: None)
    monkeypatch.setattr(publish, "list_published", lambda c, **k: [])
    monkeypatch.setattr(publish, "style_judge_gate", lambda a, cfg=None: {
        "ok": False, "errors": ["style judge: voice_match=fail — too corporate"],
    })

    client = FakeClient([make_article()])
    result = publish.publish_one(client, None, dry_run=False)

    assert result["event"] == "skip"
    assert "style judge" in result["reason"]
    assert client.updates == []  # nothing written to Strapi
