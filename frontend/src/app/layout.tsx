import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import { Analytics } from "@vercel/analytics/react";
import "./globals.css";
import SiteHeader from "@/components/SiteHeader";
import SiteFooter from "@/components/SiteFooter";
import { HOMEPAGE_COPY, HOMEPAGE_HERO_IMAGE } from "@/lib/homepage";

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
  "Independent guides for choosing a base, planning the move, and setting up money across borders.";
const SITE_TITLE = "Nomadomics — Travel Guides for Living Well Abroad";

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
    default: SITE_TITLE,
    template: "%s · Nomadomics",
  },
  description: SITE_DESCRIPTION,
  alternates: { canonical: "/" },
  openGraph: {
    siteName: SITE_NAME,
    type: "website",
    url: "/",
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    images: [
      {
        url: HOMEPAGE_HERO_IMAGE,
        width: 1024,
        height: 572,
        alt: HOMEPAGE_COPY.heroAlt,
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    images: [HOMEPAGE_HERO_IMAGE],
  },
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
          // Static, locally constructed site identity only; no CMS or user content enters this JSON.
          dangerouslySetInnerHTML={{ __html: JSON.stringify(siteJsonLd) }}
        />
        {/* RSS autodiscovery stays relative so it survives host changes. */}
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
