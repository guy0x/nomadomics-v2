---
title: Nomadomics v2 — Progress Handoff (CORRECTED)
session_date: 2026-07-15
session_end_time: ~22:00 UTC+3
project: nomadomics-v2
status: phase_0_done, mvp_engine_done, strapi_src_missing
supersedes: docs/archive/nomadomics-handoff-2026-07-14.md (its "Strapi running /admin 200" claim is STALE — see Desync)
deliverable: MVP content engine works (drafts generating); Strapi app source not yet generated; GitHub push blocked on PAT
---

# Nomadomics v2 — Handoff (2026-07-15, corrected)

> ⚠️ **STALE (2026-08-25):** Both claims in this document are false now — `src/` exists and Strapi is UP (`/admin` → 200). Do not follow it. The canonical ops doc is `RUNBOOK.md`. Kept for historical reference only.

## ⚠️ Desync warning (read first)
The 2026-07-14 handoff (and the resume prompt derived from it) states Strapi is "running locally, /admin returns 200, /mcp mounted, Postgres up." That state is **NOT reproducible on 2026-07-15**. Verified directly this session:
- `curl http://localhost:1337/admin` → HTTP **000** (no server)
- `~/nomadomics-v2/src/` **does not exist** (Strapi app source never generated in the repo root)
- no background strapi process; `docker ps` empty
- `git log` shows only config-only commits (2582ad2, 4234bb9) — no app/boot commit

Root cause: the 07-14 session's "running Strapi" could not have persisted without `src/`. The app source is genuinely absent. **Do NOT trust the 07-14 boot-check assumption** — a next session that runs `curl /admin` expecting 200 will get 000.

## ✅ Real current state (2026-07-15, verified)
| Stream | State | Evidence |
|---|---|---|
| Phase 0 (Notion hub, voice exemplar, 71 ideas, brand) | ✅ done | cross-session verified |
| MVP content engine (Hermes skills + pipeline) | ✅ built this session | 6 skills in `~/.hermes/skills/nomadomics/`; `engine/pipeline.py`; 1 draft in `content/drafts/` |
| Local repo | ✅ 7 commits, dirty tree | `git rev-list --count`=7; status shows `content/`, `engine/`, `config/admin.js` |
| Postgres@16 | 🟢 running (brew services) | `pg_isready` → accepting on /tmp:5432 |
| Docker / Colima | 🟢 installed + running this session | `docker info` OK |
| Strapi app source (`src/`) | 🔴 **ABSENT** | `find` shows none in repo |
| Strapi server | 🔴 **NOT running** | `/admin` → 000 |
| GitHub remote | 🟠 set (`git@github.com:guy0x/nomadomics-v2`), 0 pushed | `git remote -v`; no commits on origin |
| PAT | 🔴 leaked ×3 (07-14), needs rotation + re-scope | issue_log 07-14 |
| `push_to_github_one_shot.py` | ✅ hardened (403 scope-error detection) | patched this session |

## 🧱 Dirty tree now (commit scope grew vs 07-14)
```
?? config/admin.js        (Strapi admin secrets — SAFE: runtime-generated, no literal secrets committed)
?? content/               (MVP drafts — REAL work, track)
?? engine/pipeline.py     (queue CLI — track)
?? engine/queue/          (approved.md topic queue — track)
?? engine/__pycache__/    (added __pycache__/ to .gitignore — do NOT commit)
M  (from 07-14) .env.example .gitignore config/database.js config/server.js favicon.png package.json
```
Note: the 07-14 handoff's planned commit listed only config files. This session added `content/` + `engine/` (the MVP engine) — include them.

## 🚧 The real blocker (NOT Docker — it's `src/` generation)
`create-strapi-app` v5.50.2 forces an interactive **Strapi Cloud login** before generating code. Headless/pipe attempts (3 variants this session) all abort at the prompt. The template-clone fallback needs git auth (absent — same root cause as the GitHub push block). So the Strapi app `src/` cannot be generated without Guy's hands.

## ▶️ Next-session actions (corrected order)
1. **Boot reality check**: `curl -s -o /dev/null -w "%{http_code}" http://localhost:1337/admin` → expect **000**. Do NOT assume 200.
2. **Generate Strapi `src/`** (pick one):
   - **A (recommended):** Guy clicks the Strapi Cloud login link when I re-run `npx create-strapi-app@latest /tmp/nomad-app --no-run ...`; on success I `rsync` the generated `src/ public/ database/ types/ package.json` into `~/nomadomics-v2` (merge with existing config/engine/content), then `npm install` + `npm run dev`.
   - **B:** Fix git auth (SSH key / credential helper) → `git clone --depth 1 https://github.com/strapi/quick-start-template` → merge.
   - **C:** Skip Strapi; keep the Markdown MVP (content production already unblocked).
3. **Boot Strapi**: `cd ~/nomadomics-v2 && npm run dev` (Postgres already up). Verify `/admin` → 200.
4. **Admin creation (Guy gate)**: open `/admin` → create first admin.
5. **API token (Guy gate)**: Settings → API Tokens → `schema-builder`, full access, 1–7d. Capture in terminal pane only: `read -rs HERMES_TOKEN && export HERMES_TOKEN`.
6. **Commit**: `git add .env.example .gitignore config/ content/ engine/pipeline.py engine/queue/ favicon.png package.json && git commit -m "feat: Strapi app + MVP content engine"`. (Confirm `__pycache__/` is ignored first.)
7. **Rotate + push**: new Fine-Grained PAT scoped to `guy0x/nomadomics-v2` + Contents R/W → `python3 ~/.hermes/scripts/push_to_github_one_shot.py` (env-var only, never chat).
8. **Schemas**: dispatch schema-builder subagent (Tasks 1.4–1.7: 5 content types + 9 components + 2 dynamic zones) using the API token.

## 📌 MVP engine note
The content engine already produces drafts as local Markdown — **no Strapi required**. `engine/pipeline.py list/next/scaffold/done` manages the queue; the `write-nomadomics-draft` skill writes voice-matched drafts to `content/drafts/<slug>.md`. Strapi is only the eventual publish target; content production is unblocked now. Keep shipping drafts this week while the Strapi src wall waits on Guy.

## 🔗 Handles
- GitHub: https://github.com/guy0x/nomadomics-v2 (public, empty)
- Notion Kanban: https://www.notion.so/39d8768ce635819c8f2bd1d89037ccaf
- Superplan (source of truth): `~/.hermes/plans/2026-07-13_093000-nomadomics-superplan.md`
- ROADMAP update: `~/.hermes/ROADMAP.md` (Phase 3 — MVP pivot + 07-15 correction)

This doc supersedes the 07-14 handoff's runtime claims. The 07-14 doc remains as forensic history in `docs/archive/`.
