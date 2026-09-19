import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import { Analytics } from "@vercel/analytics/react";
import "./globals.css";
import SiteHeader from "@/components/SiteHeader";
import SiteFooter from "@/components/SiteFooter";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const display = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

const SITE_NAME = "Nomadomics";
const SITE_DESCRIPTION =
  "Practical guides to multi-currency banking, nomad taxes, and geoarbitrage — earn in one currency, live in another.";

/**
 * Site-level identity for crawlers. Article pages emit their own BlogPosting;
 * this is the publisher behind every one of them. There is deliberately no
 * SearchAction — the site has no search route, and pointing Google at a
 * non-existent search URL is worse than omitting it.
 */
const siteJsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": `${SITE_URL}/#organization`,
      name: SITE_NAME,
      url: SITE_URL,
      description: SITE_DESCRIPTION,
      logo: {
        "@type": "ImageObject",
        url: `${SITE_URL}/apple-icon`,
        width: 180,
        height: 180,
      },
    },
    {
      "@type": "WebSite",
      "@id": `${SITE_URL}/#website`,
      url: SITE_URL,
      name: SITE_NAME,
      description: SITE_DESCRIPTION,
      inLanguage: "en",
      publisher: { "@id": `${SITE_URL}/#organization` },
    },
  ],
};

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Nomadomics - Money Tips for Travelers",
    template: "%s · Nomadomics",
  },
  description: SITE_DESCRIPTION,
  openGraph: {
    siteName: SITE_NAME,
    type: "website",
  },
  twitter: { card: "summary_large_image" },
  robots: { index: true, follow: true },
  verification: {
    google: process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION,
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${display.variable} h-full`}>
      <body className="min-h-full flex flex-col bg-white">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(siteJsonLd) }}
        />
        {/* RSS autodiscovery. Rendered as a hoisted <link> rather than
            `metadata.alternates.types`: a page that sets its own `alternates`
            (every article sets `canonical`) replaces the parent's object and
            silently drops the feed link. Relative href on purpose — the apex
            host is still a launch item, and this must not inherit it. */}
        <link
          rel="alternate"
          type="application/rss+xml"
          title={`${SITE_NAME} — RSS`}
          href="/feed.xml"
        />
        <SiteHeader />
        <main className="flex-1">{children}</main>
        <SiteFooter />
        <Analytics />
      </body>
    </html>
  );
}
