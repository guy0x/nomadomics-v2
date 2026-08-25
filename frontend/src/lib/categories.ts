/**
 * Category taxonomy.
 *
 * Articles don't carry a category field in Strapi yet, so we derive the
 * category from the slug. This map is the single source of truth — when a
 * `category` field is added to the schema, swap `categoryForSlug` to read it.
 */

export interface Category {
  slug: string;
  name: string;
  tagline: string;
  description: string;
}

export const CATEGORIES: Category[] = [
  {
    slug: "banking",
    name: "Banking",
    tagline: "Multi-currency accounts & cards",
    description:
      "Multi-currency accounts, travel credit cards, and ATMs — move money across borders without the fees.",
  },
  {
    slug: "taxes",
    name: "Taxes",
    tagline: "Nomad tax strategy",
    description:
      "Tax residency, geoarbitrage, and legal frameworks for keeping more of what you earn abroad.",
  },
  {
    slug: "travel",
    name: "Travel",
    tagline: "Flights, visas & rules",
    description:
      "Flight booking, entry rules, and the logistics of moving between countries cheaply and legally.",
  },
  {
    slug: "gear",
    name: "Gear & Tools",
    tagline: "VPNs, apps & software",
    description:
      "The software stack for working anywhere — VPNs, booking apps, and security tools.",
  },
  {
    slug: "cities",
    name: "Cities",
    tagline: "Where to base yourself",
    description:
      "Destinations and hubs ranked by cost, connectivity, and quality of life for remote workers.",
  },
];

/** slug substring -> category slug. Order matters: first match wins. */
const SLUG_CATEGORY_MAP: Array<[string, string]> = [
  ["multi-currency", "banking"],
  ["credit-card", "banking"],
  ["atm", "banking"],
  ["bank", "banking"],
  ["tax", "taxes"],
  ["geoarbitrage", "taxes"],
  ["crypto", "taxes"],
  ["flight", "travel"],
  ["visa", "travel"],
  ["travel-rules", "travel"],
  ["travel-hacks", "travel"],
  ["tax-free-shopping", "travel"],
  ["vpn", "gear"],
  ["apps", "gear"],
  ["nomad-destination", "cities"],
  ["rural", "cities"],
  ["cities", "cities"],
];

export function categoryForSlug(articleSlug: string): Category {
  for (const [needle, cat] of SLUG_CATEGORY_MAP) {
    if (articleSlug.includes(needle)) {
      return CATEGORIES.find((c) => c.slug === cat) ?? CATEGORIES[0];
    }
  }
  return CATEGORIES[2]; // default: travel
}

export function getCategory(slug: string): Category | undefined {
  return CATEGORIES.find((c) => c.slug === slug);
}
