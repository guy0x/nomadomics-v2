import type { Metadata } from "next";
import Link from "next/link";
import { CONTACT_EMAIL, CONTACT_MAILTO } from "@/lib/contact";

/**
 * Privacy policy.
 *
 * Every claim here describes something this site actually does — verify against
 * the code before editing, because a policy that overstates or understates our
 * processing is worse than none:
 *   - no cookies / no client storage: nothing in `src/` touches document.cookie,
 *     localStorage or sessionStorage, and live responses send no Set-Cookie.
 *   - analytics: `@vercel/analytics` ONLY (`<Analytics />` mounted in
 *     `src/app/layout.tsx`, server-side proxied so no third-party script is
 *     loaded) — cookie-less and aggregate-only. Vercel Speed Insights is NOT
 *     installed and no page references it, so it must not be named as a
 *     processor: re-add it here only once `@vercel/speed-insights` is a
 *     dependency AND its component is mounted (launch-checklist L5).
 *   - fonts are self-hosted at build time by `next/font/google` — no request to
 *     Google is made from a reader's browser.
 *   - affiliate links live in `src/lib/offers.ts` and render with
 *     `rel="sponsored"`.
 * If a processor, cookie, form, or ad network is ever added, update this page in
 * the same change.
 */

const LAST_UPDATED = "19 September 2026";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "What Nomadomics collects, why, and who processes it — hosting, cookie-less aggregate analytics, affiliate links, and how to reach us about your data.",
};

export default function PrivacyPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="font-display text-3xl font-bold tracking-tight text-ink-950 sm:text-4xl">
        Privacy Policy
      </h1>
      <p className="mt-3 text-sm text-ink-500">Last updated: {LAST_UPDATED}</p>

      <div className="article-body mt-8">
        <p>
          Nomadomics publishes practical guides for people who earn in one
          currency and live in another. This page explains what data we collect
          when you read it, what we do with that data, and what you can ask us to
          do about it. It is written to be read.
        </p>

        <h2 id="in-short">In short</h2>
        <ul>
          <li>
            There are <strong>no accounts, no newsletter, no comments and no
            forms</strong> on this site. We do not ask you for personal data in
            order to read anything.
          </li>
          <li>
            We use <strong>no advertising cookies and no third-party ad
            trackers</strong>. We do not sell or share personal information.
          </li>
          <li>
            We use <strong>cookie-less, aggregate analytics</strong> (Vercel Web
            Analytics) so we know which guides are read and roughly where from.
            We see totals, not you.
          </li>
          <li>
            Some outbound links are <strong>affiliate links</strong> that earn us
            a commission. Once you click one you are on the partner&rsquo;s site
            and their privacy policy applies — not ours.
          </li>
          <li>
            If you email us, we have your address and your message. We use it to
            reply, and we do not add you to any list.
          </li>
        </ul>

        <h2 id="who-we-are">Who we are</h2>
        <p>
          Nomadomics (&ldquo;we&rdquo;, &ldquo;us&rdquo;) is an independently
          published editorial site at{" "}
          <a href="https://nomadomics.blog">nomadomics.blog</a>. For anything on
          this page — including any request about your data — write to{" "}
          <a href={CONTACT_MAILTO}>{CONTACT_EMAIL}</a>. Our editorial standards,
          and how we make money, are set out on the{" "}
          <Link href="/about">About &amp; Editorial Policy</Link> page.
        </p>

        <h2 id="what-we-collect">What we collect</h2>
        <h3 id="reading">When you read a page</h3>
        <p>
          Serving a page requires a small amount of technical data. Our hosting
          provider, <strong>Vercel</strong>, processes your IP address, browser
          user agent, the URL requested and a timestamp in order to deliver the
          page, cache it and block abusive traffic. We do not use this to build
          a profile of you, and we do not attempt to identify individual
          readers. Vercel retains and protects this data under its own privacy
          policy as our processor.
        </p>
        <h3 id="analytics">Aggregate analytics</h3>
        <p>
          We use <strong>Vercel Web Analytics</strong>, our host&rsquo;s own
          cookie-less analytics product. It is designed around aggregate
          measurement rather than individual tracking. A visitor is identified
          only by a temporary hash derived from the incoming request, and that
          session is discarded after 24 hours. The data points recorded for a
          page view are:
        </p>
        <ul>
          <li>the page URL and its route pattern, and the referring page;</li>
          <li>
            the query parameters of the URL, with personal data filtered out;
          </li>
          <li>
            approximate location (country, region, city), device type,
            operating system and browser version.
          </li>
        </ul>
        <p>
          What we ever see is aggregated: how many people read a guide, roughly
          where from, and on what kind of device. No
          cross-site profile is built, nothing is tied to an identity, and
          nothing is sold. If you have JavaScript disabled, no analytics data is
          collected at all.
        </p>
        <h3 id="search-console">Search performance</h3>
        <p>
          We use <strong>Google Search Console</strong> to see which search
          queries send readers to the site. That reporting is aggregated by
          Google; it tells us that a phrase was searched and how many times the
          site appeared, not who searched it.
        </p>
        <h3 id="what-we-dont">What we never do</h3>
        <ul>
          <li>We do not run an advertising network, and we do not serve ads.</li>
          <li>
            We do not sell, rent or share personal information with data
            brokers, and we do not use personal information for cross-context
            behavioural advertising.
          </li>
          <li>
            We do not ask for financial details, and we never want them: if a
            page ever asks you for card or bank details, it is not us.
          </li>
          <li>We do not knowingly collect data from children (see below).</li>
        </ul>

        <h2 id="cookies">Cookies</h2>
        <p>
          This site sets no cookies of its own and stores nothing in your
          browser&rsquo;s local storage. Because we use no tracking cookies and
          no advertising identifiers, there is nothing for a cookie banner to
          ask you to consent to — and you will not see one. If that changes (for
          example, if we ever add an ad network or a newsletter), this page will
          be updated before the change goes live.
        </p>

        <h2 id="email">Email</h2>
        <p>
          If you write to us, we receive your email address and whatever you send
          with it. We use it to answer you, and we keep it only as long as the
          correspondence needs it. We do not add you to a mailing list, and we
          do not pass your address to anyone else. Our email is handled by{" "}
          {/* CONTACT-PROVIDER: name the mail host here once L4 is decided. */}
          our email provider acting as a processor on our behalf.
        </p>

        <h2 id="affiliate-links">Affiliate links, and how we make money</h2>
        <p>
          Nomadomics is reader-supported. Some links to products and services we
          recommend — money-transfer and multi-currency accounts, VPNs, travel
          and health insurance, eSIMs and similar — are affiliate links. If you
          click one and sign up, we may earn a commission. It costs you nothing
          extra and it never influences our rankings or recommendations, as set
          out in our <Link href="/about">editorial policy</Link>.
        </p>
        <p>
          Affiliate links are marked as sponsored in the page&rsquo;s HTML and
          open in a new tab. Some contain a referral code that identifies us as
          the source of the visit. When you click through, the partner&rsquo;s
          site may set its own cookies and process your data under its own
          privacy policy — we have no control over that, and we recommend
          reading their policy before signing up.
        </p>
        <p>
          What we receive from partners is a commission report: an amount
          attributed to our referrer code. We do not receive your name, address,
          or account details.
        </p>

        <h2 id="third-parties">Links to other sites</h2>
        <p>
          Articles link to external sources, tools and partners. Those sites are
          governed by their own privacy policies, and this one stops at our
          domain.
        </p>

        <h2 id="your-rights">Your rights</h2>
        <p>
          If you are in the European Economic Area, the United Kingdom or
          Switzerland, we process the limited data described above on the basis
          of our <strong>legitimate interests</strong> in running and protecting
          a working website, and (for correspondence) on the basis of your
          enquiry. You have the right to request access to personal data we hold
          about you, to have it corrected or erased, to object to or restrict
          its processing, and to receive it in a portable form. You also have
          the right to complain to your national data protection authority.
        </p>
        <p>
          If you are a California resident, we do not sell or share your
          personal information as those terms are defined by the CCPA/CPRA, and
          we do not use it for cross-context behavioural advertising. You may
          ask what we hold and ask us to delete it.
        </p>
        <p>
          To make any of these requests, email{" "}
          <a href={CONTACT_MAILTO}>{CONTACT_EMAIL}</a>. In most cases we hold no
          personal data that identifies you, and we will tell you so plainly
          rather than stall.
        </p>

        <h2 id="transfers">Where your data is processed</h2>
        <p>
          Our hosting and analytics providers are based in the United States,
          so technical data may be processed there. Where personal data leaves
          the EEA or the UK, our providers rely on the transfer safeguards
          described in their own terms (standard contractual clauses and the
          EU&ndash;US Data Privacy Framework, as applicable).
        </p>

        <h2 id="children">Children</h2>
        <p>
          Nomadomics is written for adults managing their own money and
          residency. It is not directed at children, and we do not knowingly
          collect personal data from anyone under 16. If you believe a child has
          provided us with personal data, write to us and we will delete it.
        </p>

        <h2 id="security">Security</h2>
        <p>
          The site is served over HTTPS, and access to our publishing systems is
          limited to the editorial team. No website can promise perfect
          security, but we keep the amount of data we hold — which, by design, is
          very little — as small as it can be.
        </p>

        <h2 id="changes">Changes to this policy</h2>
        <p>
          When this policy changes, the date at the top of the page changes with
          it. If a change is material — a new processor, a new kind of data —
          we will say so on the site rather than quietly editing this page.
        </p>

        <h2 id="contact">Contact</h2>
        <p>
          Questions about this policy, or about anything we publish:{" "}
          <a href={CONTACT_MAILTO}>{CONTACT_EMAIL}</a>.
        </p>
      </div>
    </div>
  );
}
