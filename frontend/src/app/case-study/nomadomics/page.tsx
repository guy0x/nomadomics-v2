import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Nomadomics Project Case Study",
  description:
    "How Nomadomics turned a travel-finance content idea into an operational, auditable publishing MVP.",
  openGraph: {
    title: "Nomadomics Project Case Study",
    description:
      "An employer-facing case study of the Nomadomics content product and publishing system.",
    type: "article",
  },
};

export const revalidate = 3600;

const metrics = [
  ["5", "editorial pillars", "Banking, taxes, travel, work, and logistics"],
  ["47", "article-like URLs", "Verified in the 9 October 2026 sitemap snapshot"],
  ["47/47", "asset coverage", "Cards and Open Graph images present in the audit snapshot"],
  ["1", "operating loop", "Research → brief → CMS draft → QA → publish → refresh"],
];

const capabilities = [
  "Structured content in Strapi rather than a pile of hand-edited pages",
  "A Next.js frontend with category, article, author, policy, and sitemap surfaces",
  "Editorial and affiliate-disclosure boundaries visible to the reader",
  "Repeatable research, drafting, asset, and freshness checks instead of one-off publishing",
  "A public proof surface that can be inspected by a reader or hiring team",
];

export default function NomadomicsCaseStudyPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16">
      <section className="max-w-4xl">
        <p className="text-sm font-bold uppercase tracking-[0.16em] text-brand-700">
          Independent product case study · verified 9 October 2026
        </p>
        <h1 className="mt-5 max-w-4xl font-display text-4xl font-bold tracking-tight text-ink-950 sm:text-6xl">
          Nomadomics: from content idea to operating publishing MVP
        </h1>
        <p className="mt-6 max-w-3xl text-xl leading-8 text-ink-600">
          Nomadomics is a working editorial product for people who earn in one
          currency and live in another. I built the public experience, the CMS
          workflow, the content model, and the quality loop as one system rather
          than treating the website as a collection of articles.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <a
            href="https://www.nomadomics.blog"
            className="rounded-lg bg-brand-600 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-brand-700"
          >
            Visit the live product
          </a>
          <Link
            href="/about"
            className="rounded-lg border border-ink-300 px-5 py-3 text-sm font-semibold text-ink-800 transition-colors hover:border-brand-500 hover:text-brand-700"
          >
            Read the editorial policy
          </Link>
        </div>
      </section>

      <section className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Project metrics">
        {metrics.map(([value, label, detail]) => (
          <div key={label} className="rounded-2xl border border-ink-200 bg-white p-5 shadow-sm">
            <p className="font-display text-4xl font-bold text-brand-700">{value}</p>
            <p className="mt-2 font-semibold text-ink-950">{label}</p>
            <p className="mt-2 text-sm leading-6 text-ink-600">{detail}</p>
          </div>
        ))}
      </section>

      <div className="mt-16 grid gap-12 lg:grid-cols-[1.15fr_0.85fr]">
        <article className="article-body">
          <h2 id="brief">The brief</h2>
          <p>
            Build a credible niche publication that can earn trust before it
            earns scale. The product needed to make cross-border financial and
            relocation topics understandable, while keeping the underlying
            publishing process repeatable enough to operate week after week.
          </p>
          <p>
            The hard part was not putting a logo on a homepage. It was creating
            the connective tissue: a content model, an editorial voice, a
            research workflow, reusable page surfaces, image coverage, and
            verification checks that expose gaps instead of hiding them.
          </p>

          <h2 id="what-shipped">What shipped</h2>
          <ul>
            {capabilities.map((capability) => (
              <li key={capability}>{capability}</li>
            ))}
          </ul>

          <h2 id="operating-loop">The operating loop</h2>
          <ol>
            <li>
              <strong>Research:</strong> turn a reader problem into a bounded,
              evidence-led brief.
            </li>
            <li>
              <strong>Structure:</strong> store the brief and article in the CMS
              so the content is queryable and reusable.
            </li>
            <li>
              <strong>Publish:</strong> render the article, category, author, and
              discovery surfaces through the frontend.
            </li>
            <li>
              <strong>Audit:</strong> check links, metadata, image coverage,
              sourcing, and reader-facing policy disclosures.
            </li>
            <li>
              <strong>Refresh:</strong> treat freshness as an operating task,
              not a vague promise in the footer.
            </li>
          </ol>

          <h2 id="quality-audit">What the audit changed</h2>
          <p>
            The October snapshot found strong technical coverage: all 47
            article-like URLs had card and Open Graph assets. It also exposed
            content-system debt: 44 of 47 pages repeated the same “Picture
            this” opening pattern, and only 17 of 47 pages surfaced a visible
            sources section. That distinction is the point of the audit — a
            product can be operational while still showing exactly where the
            next quality pass belongs.
          </p>

          <h2 id="why-it-matters">Why this is an employer-facing project</h2>
          <p>
            Nomadomics demonstrates product thinking across the full loop: I
            translated an audience problem into an information architecture,
            connected structured data to a public interface, designed a
            repeatable editorial workflow, and used an audit to prioritize the
            next improvements. The result is both a visible product and a
            maintainable system behind it.
          </p>
        </article>

        <aside className="self-start rounded-2xl border border-brand-200 bg-brand-50 p-6 lg:sticky lg:top-24">
          <p className="text-sm font-bold uppercase tracking-[0.14em] text-brand-700">
            Project card
          </p>
          <dl className="mt-5 space-y-5 text-sm">
            <div>
              <dt className="font-semibold text-ink-950">Role</dt>
              <dd className="mt-1 leading-6 text-ink-700">Product, content systems, editorial QA, and frontend delivery</dd>
            </div>
            <div>
              <dt className="font-semibold text-ink-950">Stack</dt>
              <dd className="mt-1 leading-6 text-ink-700">Next.js frontend · Strapi CMS · PostgreSQL content store</dd>
            </div>
            <div>
              <dt className="font-semibold text-ink-950">Proof</dt>
              <dd className="mt-1 leading-6 text-ink-700">Public site, sitemap, article surfaces, policy pages, and a dated quality snapshot</dd>
            </div>
            <div>
              <dt className="font-semibold text-ink-950">Next pass</dt>
              <dd className="mt-1 leading-6 text-ink-700">Diversify article openings and make source coverage systematic</dd>
            </div>
          </dl>
          <div className="mt-7 border-t border-brand-200 pt-5">
            <p className="text-sm leading-6 text-ink-700">
              The honest claim is “operational MVP,” not “finished media company.”
              The remaining gaps are documented, measurable, and actionable.
            </p>
          </div>
        </aside>
      </div>

      <section className="mt-16 rounded-2xl bg-ink-950 p-8 text-white sm:p-10">
        <p className="text-sm font-bold uppercase tracking-[0.14em] text-brand-300">
          Continue exploring
        </p>
        <div className="mt-4 flex flex-col justify-between gap-6 sm:flex-row sm:items-end">
          <div>
            <h2 className="font-display text-3xl font-bold">See the product in context</h2>
            <p className="mt-3 max-w-2xl leading-7 text-ink-200">
              Browse the public site, then inspect the editorial policy to see how
              the product communicates trust, monetization, and corrections.
            </p>
          </div>
          <a
            href="https://www.nomadomics.blog"
            className="shrink-0 rounded-lg bg-white px-5 py-3 text-center text-sm font-semibold text-ink-950 transition-colors hover:bg-brand-50"
          >
            Open nomadomics.blog
          </a>
        </div>
      </section>
    </main>
  );
}
