import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About & Editorial Policy",
  description:
    "How Nomadomics researches, tests, and ranks the products we recommend — and how we make money.",
};

export default function AboutPage() {
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
      </div>
    </div>
  );
}
