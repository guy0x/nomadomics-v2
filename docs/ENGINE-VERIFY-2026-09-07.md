# ENGINE VERIFY — Nomadomics content engine (2026-09-07)

> Goal: prove functional / live / as-designed with live evidence. One real topic consumed:
> `budget-travel-accommodation-hacks` (digital-nomad, non-sensitive). Companion to
> `docs/RECON-2026-09-07.md`.

## FUNCTIONAL — PASS (evidence)

Real run `draft-one budget-travel-accommodation-hacks`, exit 0, 3 live Gemini calls:

| Check | Evidence |
|---|---|
| Real article in Strapi | documentId `j5dd717tobi4hmxhi0hyt25h` (real long ID), slug match ×1 |
| Status | `in_review` — v1 gate held despite conf **92** > threshold 80, decision `auto_publish`, `published: false` (`AUTO_PUBLISH_ENABLED=false`) |
| CLI reads live data | `engine.cli drafts` lists it: `[in_review] Budget Travel Accommodation Hacks (conf=92)` |
| State log appended | `article_created` entry with real docId, conf 92, decision auto_publish, published False |

## LIVE — PASS

Strapi `/admin` 200 · Gemini billed+returned (real 2,372-word draft + edit report) ·
state log appends (98→106 lines across pytest + real run) · `engine.cli info`: gemini-2.5-flash
×3, premium off, auto_publish off, key set.

## AS-DESIGNED ledger

| # | Invariant | Verdict | Evidence |
|---|---|---|---|
| I1 | v1 human gate holds | **PASS** | status `in_review` at conf 92; only `published` assignment in pipeline is inside the flag-gated branch |
| I2 | Structure gate | **PASS** | 1 table, 26 bullets, 7 H2, 16 H3, Pros/Cons — not wall-of-prose (structure scorer rewards this) |
| I3 | Voice anchors | **PASS** | opens scene-setter: "Picture this: You're halfway across the world…" |
| I4 | Meta complete | **PASS** | metaTitle 59 ≤60; metaDesc 102 ≤155; focusKeyword + targetKeywords set |
| I5 | Topic transition | **PASS** | topic `pending → in_review` (not stuck drafting) |
| I6 | State-log integrity | **DEFECT (J1)** | **63 of 106 entries are mock** (`article-1` docIds / `esim-plans` test slug) — worse than the 37/92 stated in the goal prompt; pytest re-contaminates on every run |
| I7 | Test isolation | **DEFECT (J1, same root)** | `pytest` run grew the log 100→106 (6 new mock entries during verification) |
| I8 | Confidence recorded | **PASS** | article conf 92 / seoScore 67; state log `decision: auto_publish`, `published: False` |

## J1 — state-log contamination (awaiting Guy green light)

Root cause: `engine/tests/test_pipeline.py` calls the real `draft_one()` without patching
`pipeline_cli.STATE_FILE` → `_append_state` writes the production audit log. Fix (prepared):
1. Tests monkeypatch `STATE_FILE` to `tmp_path` (I6/I7 become PASS).
2. Backup-then-prune the 63 mock entries to `engine/state/pipeline.mock-archive.jsonl`.
3. Commit local-only: `FIX(engine): isolate test state writes — stop polluting production pipeline.jsonl`.
Cost of report-only: every pytest run re-poisons the audit trail; 9 fake
`published:true/auto_publish` records make the log lie about what was actually published.

## Topic-consumption accounting

1 topic consumed this session (`budget-travel-accommodation-hacks`, now in_review with its
article — intentionally NOT reset; the draft is a real deliverable). Note: prior verify-run
topics (geoarbitrage, remote-workers) were found back at `pending` with their articles still
in_review — topic/article status can drift independently; harmless but worth knowing.
