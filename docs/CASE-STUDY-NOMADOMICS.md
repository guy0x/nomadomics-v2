# Nomadomics case study — canonical evidence

**Case-study handle:** `20261009_111004_bb2a52ce`
**Snapshot:** 2026-10-09
**Audience:** hiring managers, founders, and marketing/operations leaders evaluating AI workflow, content systems, automation, and quality-control work.

## Thesis

I built a content operating system, not a content factory.

Nomadomics is an AI-assisted editorial product for people who earn in one currency and live in another. The work connects audience strategy, research, structured content, editorial control, publishing, and a future performance-feedback loop.

## The problem

Content teams can publish before they know what is useful, trustworthy, or worth refreshing. The MVP makes the test cheaper and more controlled: define the reader problem, research it, draft into a structured system, apply explicit checks, publish, and inspect what happened.

## System

```text
Reader problem
    ↓
Research → brief → draft → edit → SEO/policy checks → Strapi review → Next.js publish
    ↓
QA: citations · structure · links · policy · human control
    ↓
Refresh queue (Search Console integration is the next step)
```

- **Content engine:** research, drafting, editorial QA, and workflow orchestration.
- **Strapi CMS:** structured drafts, review, and publishing state.
- **Next.js frontend:** article/category/author/policy surfaces, SEO, and sitemap.
- **PostgreSQL:** CMS content store.

## Guardrails

The publish path includes citation/invariant checks, internal-link handling, sensitive-topic quarantine, human review controls, and generated cover/Open Graph assets. The point is not to automate judgment away; it is to make the handoffs and failure modes visible.

## Verified snapshot

The following facts were checked against the public product on 2026-10-09:

| Evidence | Result | Interpretation |
| --- | ---: | --- |
| Topic categories | 5 | Banking, Taxes, Travel, Gear & Tools, Cities |
| Article-like URLs in live sitemap | 47 | Sitemap count; not the same definition as homepage guides |
| Guides displayed on homepage | 44 | Count-definition discrepancy is preserved |
| Card + Open Graph asset coverage | 47/47 | Technical asset coverage was complete in the snapshot |
| Repetitive “Picture this” opening | 44/47 | Content-pattern debt is measurable |
| Visible Sources section | 17/47 | Source presentation is the next editorial quality pass |

No Search Console results, rankings, traffic, revenue, or cost-savings claims are included. Search Console is not yet integrated into the editorial workflow; the system is designed to close that loop next.

## What I would say in an interview

> “The interesting part of Nomadomics was not generating articles. It was turning AI-assisted content into an operating system with explicit handoffs, quality gates, and evidence. The first audit proved the infrastructure was real and also showed the next work: diversify repetitive openings, make source coverage systematic, then connect performance data to a refresh queue.”

## Transferable skills demonstrated

- Turning an ambiguous content idea into a product and operating model.
- Designing an information architecture around user problems rather than tools.
- Connecting structured CMS data to a public frontend.
- Building verification around automated workflows.
- Reporting weaknesses as product requirements instead of hiding them.
- Keeping claims bounded by evidence.

## Next iteration

1. Integrate Search Console signals into a refresh queue.
2. Add systematic source-section coverage to the editorial QA gate.
3. Replace repeated opening patterns with a small set of reader-appropriate structures.
4. Add a cost ledger so the system can evaluate output quality against operating effort.

## Assets

- Public project case study: `/case-study/nomadomics`
- Existing carousel PDF: `/Users/guy/Documents/Portfolio/Nomadomics/2026-10-09_Nomadomics_LinkedIn_Carousel.pdf`
- Carousel brief: `/Users/guy/Documents/Portfolio/Nomadomics/2026-10-09_Gamma_Carousel_Brief.md`
- LinkedIn publication draft: `/Users/guy/Documents/Portfolio/Nomadomics/2026-10-10_Nomadomics_LinkedIn_Post.md`
- Employer MVP brief: `/Users/guy/nomadomics-v2/docs/EMPLOYER-MVP.md`
