import type { Metadata } from "next";
import Link from "next/link";

/**
 * Advertiser / affiliate disclosure (FTC).
 *
 * The opening sentence is the EXACT footer string from SiteFooter.tsx — reused
 * verbatim, never paraphrased. The rest expands on it in plain language:
 *   - what affiliate links are
 *   - that commissions never influence rankings or recommendations
 *   - that we never accept payment for positive reviews
 *   - how a reader can identify affiliate links
 *
 * Static content only: no client-side fetching, no new dependencies.
 */

const LAST_UPDATED = "5 October 2026";

export const metadata: Metadata = {
  title: "Advertiser Disclosure",
  description:
    "How Nomadomics makes money: affiliate links, reader support, and why commissions never influence our rankings or recommendations.",
};

export default function DisclosurePage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="font-display text-3xl font-bold tracking-tight text-ink-950 sm:text-4xl">
        Advertiser Disclosure
      </h1>
      <p className="mt-3 text-sm text-ink-500">Last updated: {LAST_UPDATED}</p>

      <div className="article-body mt-8">
        <p>
          Nomadomics is reader-supported. When you buy through links on our
          site we may earn an affiliate commission at no extra cost to you.
          This never influences our rankings or recommendations.
        </p>

        <h2 id="what-are-affiliate-links">What affiliate links are</h2>
        <p>
          Some links on this site point to products and services we recommend
          — money-transfer and multi-currency accounts, VPNs, travel and health
          insurance, eSIMs, and similar — and are affiliate links. If you click
          one and make a purchase or sign up, we may earn a commission from the
          partner. It costs you nothing extra: the price you pay is exactly the
          same whether or not you use our link.
        </p>

        <h2 id="does-this-affect-our-recommendations">
          Does this affect our recommendations?
        </h2>
        <p>
          No. Affiliate commissions never influence our rankings or
          recommendations. Our rankings, scores, and recommendations are based
          on independent research, hands-on testing where possible, and
          analysis of fees, features, and real user outcomes. A partner cannot
          pay for a better placement, and we never accept payment in exchange
          for positive reviews. Partners never see content before it is
          published.
        </p>

        <h2 id="how-to-identify-affiliate-links">
          How to identify affiliate links
        </h2>
        <p>
          Affiliate links are marked as sponsored in the page&rsquo;s HTML —
          they carry{" "}
          <code className="rounded bg-ink-50 px-1 py-0.5 text-xs text-ink-700">
            rel=&quot;sponsored&quot;
          </code>{" "}
          — and open in a new tab. They typically appear as &ldquo;Visit
          site&rdquo; buttons in our comparison tables and &ldquo;best
          of&rdquo; guides. Some contain a referral code that identifies us as
          the source of the visit. If a link opens in a new tab and leads to a
          partner&rsquo;s site, assume it is an affiliate link.
        </p>

        <h2 id="more">More</h2>
        <p>
          Our standards, and how we research and rank the products we recommend,
          are set out in our{" "}
          <Link href="/about">About &amp; Editorial Policy</Link> page. What we
          collect about readers is covered in our{" "}
          <Link href="/privacy">Privacy Policy</Link>.
        </p>
      </div>
    </div>
  );
}