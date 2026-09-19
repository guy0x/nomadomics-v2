import type { Metadata } from "next";
import Link from "next/link";
import { getAuthors } from "@/lib/strapi";
import AuthorAvatar from "@/components/AuthorAvatar";
import { CONTACT_EMAIL, CONTACT_MAILTO } from "@/lib/contact";

export const metadata: Metadata = {
  title: "About & Editorial Policy",
  description:
    "Who writes Nomadomics, how we research, test, and rank the products we recommend — and how we make money.",
};

export const revalidate = 3600;

export default async function AboutPage() {
  const authors = await getAuthors();

  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="font-display text-3xl font-bold tracking-tight text-ink-950 sm:text-4xl">
        About &amp; Editorial Policy
      </h1>
      <div className="article-body mt-8">
        <p>
          Nomadomics publishes practical guides for people who earn in one
          currency and live in another — digital nomads, expats, and
          location-independent earners using geoarbitrage to get ahead.
        </p>
        <h2 id="who-writes-this">Who writes this</h2>
        {authors.length ? (
          <ul className="not-prose mt-4 grid gap-4 sm:grid-cols-2">
            {authors.map((a) => (
              <li key={a.documentId} className="rounded-xl border border-ink-200 p-4">
                <div className="flex items-center gap-3">
                  <AuthorAvatar name={a.name} size={36} className="text-xs" />
                  <div>
                    <Link
                      href={`/author/${a.slug}`}
                      className="font-display text-lg font-bold text-ink-950 hover:text-brand-700"
                    >
                      {a.name}
                    </Link>
                    {a.role && (
                      <p className="text-xs font-bold uppercase tracking-wide text-brand-700">
                        {a.role}
                      </p>
                    )}
                  </div>
                </div>
                {a.bio && <p className="mt-2 text-sm leading-6 text-ink-600">{a.bio}</p>}
              </li>
            ))}
          </ul>
        ) : (
          <p>
            Nomadomics is written by a small editorial team. Every guide carries a
            byline linking to the writer&rsquo;s page.
          </p>
        )}
        <h2 id="how-we-make-money">How we make money</h2>
        <p>
          Nomadomics is reader-supported. When you click links to products and
          services we recommend and make a purchase, we may receive compensation
          from those partners at no additional cost to you.
        </p>
        <p>
          This compensation may influence which products we review and where
          they appear on the site, but it never influences our editorial
          judgment. We do not accept payment in exchange for positive reviews,
          and partners never see content before it is published.
        </p>
        <h2 id="how-we-rank">How we rank products</h2>
        <p>
          Our rankings, scores, and recommendations are based on independent
          research, hands-on testing where possible, and analysis of fees,
          features, and real user outcomes. We weight the factors that matter
          most to internationally mobile readers: total cost, cross-border
          reliability, and ease of use across jurisdictions.
        </p>
        <h2 id="corrections">Corrections</h2>
        <p>
          Financial products change frequently. We work to keep every guide
          current, but if you spot an error or an out-of-date figure, contact us
          and we will correct it promptly.
        </p>
        <h2 id="contact">Contact</h2>
        <p>
          Corrections, tips, and questions:{" "}
          <a href={CONTACT_MAILTO}>{CONTACT_EMAIL}</a>. We read
          everything and reply to corrections first. What we collect, and what we
          do with it, is set out in our{" "}
          <Link href="/privacy">privacy policy</Link>.
        </p>
      </div>
    </div>
  );
}
