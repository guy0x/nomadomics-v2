# Nomadomics 2.0 — AI-powered nomad finance platform

A semi-automated content engine for digital nomads and travelers.

## Stack
- Hermes Agent (orchestrator)
- Strapi v5 + MCP (CMS, self-hosted on Hetzner VPS)
- Next.js 15 + Tailwind + shadcn/ui (frontend, Vercel)
- PostgreSQL (database)
- Notion (tracking: topic queue, costs, decisions, analytics)

## Status
Phase 0 in progress. See ~/.hermes/plans/2026-07-13_093000-nomadomics-superplan.md for full roadmap.

## Directory layout
- `reference/wp-articles/` — exported WordPress corpus (markdown)
- `scripts/` — conversion + automation scripts
- `engine/writer/prompts/` — voice exemplar + writer prompts
- Notion: "Nomadomics Project Hub - Master Knowledge Base" (workspace)