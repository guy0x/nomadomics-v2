# Nomadomics employer-facing MVP

Status: operational MVP package · 2026-10-10

## One-line pitch

Nomadomics is an AI-assisted editorial operating system: it turns a reader problem into researched, structured, reviewed, published, and refreshable content instead of treating AI as a bulk text generator.

## Public proof

- Product: https://www.nomadomics.blog
- Project case study: `/case-study/nomadomics` on the public site after deployment
- Editorial policy: https://www.nomadomics.blog/about
- Case-study source and LinkedIn package: `/Users/guy/Documents/Portfolio/Nomadomics/`

## What the MVP demonstrates

1. **Product framing** — a clear audience (people who earn in one currency and live in another) and five editorial pillars: Banking, Taxes, Travel, Gear & Tools, and Cities.
2. **Content infrastructure** — Strapi CMS and PostgreSQL-backed content model behind a Next.js frontend.
3. **Operating workflow** — research → brief → draft → edit → SEO/policy → publish → QA/freshness.
4. **Quality control** — citation/invariant checks, internal-link handling, sensitive-topic quarantine, human review controls, and generated cover/OG assets.
5. **Honest measurement** — the October snapshot records what is verified and names the next gap: Search Console is not yet integrated into the editorial loop.

## Verified product snapshot

Snapshot checked 2026-10-09; counts use their stated definitions.

- 5 topic categories.
- 47 article-like URLs in the live sitemap.
- 44 guides displayed on the homepage; this is a definition discrepancy, not a silently reconciled total.
- 47/47 sitemap article URLs had card and Open Graph image assets.
- 44/47 live article pages contained the repetitive “Picture this” opening pattern.
- 17/47 live article pages exposed a visible Sources section.

These are audit findings, not traffic, ranking, revenue, or cost-saving claims. Search Console results and performance learning are not claimed because that integration is not live yet.

## Employer presentation order

Use this sequence in a portfolio review:

1. **Problem:** publishing volume without a feedback and quality loop creates noise.
2. **System:** the engine owns process, the CMS owns content, and the frontend owns the public experience.
3. **Guardrails:** publishing can stop when evidence, policy, structure, or human-review requirements fail.
4. **Evidence:** show the dated sitemap/homepage/asset/content audit rather than invented growth numbers.
5. **Next step:** connect Search Console to a refresh queue and cost ledger.

## Local verification

From the repository root:

```bash
cd /Users/guy/nomadomics-v2/frontend
npm test
npm run lint
npm run build
```

The build is the release gate for the case-study route and navigation links. The Strapi service is a separate backend and remains managed by its LaunchAgent/runbook.

## Deliberate limits

- This package does not claim that Nomadomics has Search Console-driven learning, revenue, traffic, rankings, or cost savings.
- The case-study page is static and employer-facing; it does not expose CMS credentials, private analytics, or local career files.
- Deployment to the existing public host is a separate release action. Verify the final URL after promotion; a local build alone is not proof of production deployment.
