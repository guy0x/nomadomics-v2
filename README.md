# Nomadomics — AI-assisted editorial operating system

Nomadomics is an operational MVP for researching, structuring, reviewing,
publishing, and refreshing practical guides for people who earn in one currency
and live in another.

## Employer-facing proof

- Live product: https://www.nomadomics.blog
- Public project case study: `/case-study/nomadomics` on the frontend
- Employer MVP brief: [`docs/EMPLOYER-MVP.md`](docs/EMPLOYER-MVP.md)
- Canonical evidence: [`docs/CASE-STUDY-NOMADOMICS.md`](docs/CASE-STUDY-NOMADOMICS.md)

## Stack

- Content engine: research, drafting, editorial QA, and workflow orchestration
- Strapi 5 + MCP: structured CMS content and review state
- Next.js 16 + Tailwind: public frontend, SEO, and sitemap surfaces
- PostgreSQL: CMS content store
- Vercel: frontend deployment target

## Operating loop

`research → brief → draft → edit → SEO/policy → CMS review → publish → QA/freshness`

The publish path includes citation/invariant checks, internal-link handling,
sensitive-topic quarantine, human review controls, and generated cover/Open Graph
assets. Search Console feedback is the next integration, not a current claim.

## Verification

```bash
cd frontend
npm test
npm run lint
npm run build
```

The Strapi backend has its own build and LaunchAgent lifecycle; see `RUNBOOK.md`
for operations.
