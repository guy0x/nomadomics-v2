/**
 * Monetization config — the affiliate/commercial layer.
 *
 * MoneyMade/NerdWallet separate editorial body copy from the commercial
 * components (verdict box, comparison table, sticky CTA). We do the same:
 * the article body comes from Strapi; the offers, verdicts, and comparison
 * data live here, keyed by article slug. When a slug has no entry, the
 * article renders editorial-only (no affiliate components).
 *
 * Swap the `href` values for real affiliate links when they're available.
 */

export interface Offer {
  name: string;
  tagline: string;
  rating: number; // 0–5
  href: string;
  ctaLabel: string;
  badge?: string; // e.g. "Our #1 pick"
}

export interface VerdictBullet {
  label: string;
  value: string;
}

export interface QuickVerdict {
  heading: string;
  score: number; // 0–10
  scoreLabel: string;
  bullets: string[];
  offer: Offer;
}

export interface ComparisonColumn {
  key: string;
  label: string;
  offer: Offer;
}

export interface ComparisonRow {
  label: string;
  /** value per column key — string, or boolean for check/cross */
  values: Record<string, string | boolean>;
}

export interface ComparisonTable {
  heading: string;
  columns: ComparisonColumn[];
  rows: ComparisonRow[];
}

export interface ArticleCommercial {
  quickVerdict?: QuickVerdict;
  comparison?: ComparisonTable;
  /** The #1 pick surfaced in the sticky bottom bar. */
  stickyOffer?: Offer;
  pros?: string[];
  cons?: string[];
}

const WISE: Offer = {
  name: "Wise",
  tagline: "Mid-market rate, transparent fees",
  rating: 4.8,
  href: "https://wise.com/invite/dic/guyo75",
  ctaLabel: "Open a Wise account",
  badge: "Our #1 pick",
};

const REVOLUT: Offer = {
  name: "Revolut",
  tagline: "All-in-one finance super-app",
  rating: 4.5,
  href: "https://revolut.com/referral/?referral-code=guy8777q!FEB1-25-AR-US-REFBLOCK",
  ctaLabel: "Try Revolut",
};

const NORDVPN: Offer = {
  name: "NordVPN",
  tagline: "Fastest all-round VPN for travel",
  rating: 4.7,
  href: "https://nordvpn.com",
  ctaLabel: "Get NordVPN",
  badge: "Our #1 pick",
};

const SURFSHARK: Offer = {
  name: "Surfshark",
  tagline: "Unlimited devices, budget price",
  rating: 4.4,
  href: "https://surfshark.com",
  ctaLabel: "Get Surfshark",
};

const SAFETYWING: Offer = {
  name: "SafetyWing",
  tagline: "Insurance built for nomads",
  rating: 4.6,
  href: "https://safetywing.com",
  ctaLabel: "Get covered",
  badge: "Our #1 pick",
};

const COMMERCIAL_BY_SLUG: Record<string, ArticleCommercial> = {
  "multi-currency-accounts": {
    quickVerdict: {
      heading: "Quick verdict",
      score: 9.2,
      scoreLabel: "Excellent",
      bullets: [
        "Wise wins on transparent, mid-market exchange rates",
        "Revolut wins on features — budgeting, crypto, and stock trading in one app",
        "Both beat a traditional bank on foreign transaction fees",
        "For pure currency exchange, Wise is almost always cheaper",
      ],
      offer: WISE,
    },
    comparison: {
      heading: "Wise vs Revolut at a glance",
      columns: [
        { key: "wise", label: "Wise", offer: WISE },
        { key: "revolut", label: "Revolut", offer: REVOLUT },
      ],
      rows: [
        { label: "Exchange rate", values: { wise: "Mid-market", revolut: "Mid-market (weekdays)" } },
        { label: "Free monthly exchange", values: { wise: "No cap (fee per conversion)", revolut: "$1,000" } },
        { label: "Weekend markup", values: { wise: false, revolut: true } },
        { label: "Multi-currency balances", values: { wise: "40+", revolut: "30+" } },
        { label: "Local account details", values: { wise: true, revolut: true } },
        { label: "Crypto & stocks", values: { wise: false, revolut: true } },
        { label: "Best for", values: { wise: "Cheap transfers", revolut: "All-in-one app" } },
      ],
    },
    stickyOffer: WISE,
    pros: ["Mid-market exchange rate", "Transparent low fees", "Local bank details in 9+ currencies"],
    cons: ["No interest on balances", "Weekend conversions cost slightly more on Revolut's free tier"],
  },

  "best-vpns-for-traveling": {
    quickVerdict: {
      heading: "Quick verdict",
      score: 9.0,
      scoreLabel: "Excellent",
      bullets: [
        "NordVPN is the fastest and most reliable for streaming and banking abroad",
        "Surfshark is the best value — unlimited devices on one plan",
        "A VPN is non-negotiable on public Wi-Fi (airports, cafés, hotels)",
        "Install and test before you leave — some countries block VPN sign-up pages",
      ],
      offer: NORDVPN,
    },
    comparison: {
      heading: "NordVPN vs Surfshark",
      columns: [
        { key: "nord", label: "NordVPN", offer: NORDVPN },
        { key: "surf", label: "Surfshark", offer: SURFSHARK },
      ],
      rows: [
        { label: "Simultaneous devices", values: { nord: "10", surf: "Unlimited" } },
        { label: "Server countries", values: { nord: "110+", surf: "100+" } },
        { label: "Audited no-logs policy", values: { nord: true, surf: true } },
        { label: "Kill switch", values: { nord: true, surf: true } },
        { label: "Works with Netflix", values: { nord: true, surf: true } },
        { label: "Starting price", values: { nord: "~$3/mo", surf: "~$2/mo" } },
      ],
    },
    stickyOffer: NORDVPN,
    pros: ["Blazing-fast NordLynx protocol", "Independently audited no-logs policy", "Reliable in restrictive countries"],
    cons: ["Slightly pricier than budget rivals", "10-device cap (Surfshark is unlimited)"],
  },

  "digital-nomad-taxes": {
    quickVerdict: {
      heading: "Quick verdict",
      score: 8.8,
      scoreLabel: "Essential reading",
      bullets: [
        "Tax residency — not citizenship — usually determines what you owe",
        "The 183-day rule is the most common residency test, but exceptions abound",
        "Nomad insurance (SafetyWing) and a clean paper trail are your first line of defense",
        "Get professional advice before renouncing residency anywhere",
      ],
      offer: SAFETYWING,
    },
    stickyOffer: SAFETYWING,
    pros: ["Purpose-built for location-independent workers", "Monthly subscription, cancel anytime", "Covers 180+ countries"],
    cons: ["Not a replacement for tax advice", "Limited coverage in your home country"],
  },
};

/** Commercial config for an article, or undefined for editorial-only posts. */
export function commercialForSlug(slug: string): ArticleCommercial | undefined {
  return COMMERCIAL_BY_SLUG[slug];
}

/**
 * A CTA href is "monetized" if it is NOT a bare homepage. Bare homepages
 * (e.g. `https://wise.com`, `https://nordvpn.com`) send readers traffic with
 * no tracking — those CTAs are suppressed until a real affiliate/referral link
 * exists. Anything with a path or query string counts as a tracked link.
 */
export function isMonetized(href: string): boolean {
  if (!href) return false;
  try {
    const url = new URL(href);
    const bare = (url.pathname === "" || url.pathname === "/") && url.search === "" && url.hash === "";
    return !bare;
  } catch {
    return false;
  }
}

/** A sensible default sticky offer per category for articles without a bespoke
 *  config — only when a monetized link exists (no free-traffic CTAs). */
export function defaultOfferForCategory(categorySlug: string): Offer | undefined {
  switch (categorySlug) {
    case "banking":
      return isMonetized(WISE.href) ? WISE : undefined;
    case "gear":
      return isMonetized(NORDVPN.href) ? NORDVPN : undefined;
    case "taxes":
      return isMonetized(SAFETYWING.href) ? SAFETYWING : undefined;
    default:
      return undefined;
  }
}
