/**
 * Image path resolution with deterministic fallback.
 *
 * Card and OG images live under /public/cards and /public/og keyed by article
 * slug. Not every article has art yet, so resolution is pure and deterministic:
 * the same (slug, kind, available) always yields the same path — a given slug
 * never flips between two different fallbacks across renders or builds.
 *
 * This module is dependency-free and side-effect-free so it can be unit-tested
 * with Node's built-in runner (`node --test`) without a bundler.
 */

export type ImageKind = "card" | "og";

const DIRS: Record<ImageKind, string> = {
  card: "/cards",
  og: "/og",
};

/** Canonical image path for an article slug (may not exist on disk yet). */
export function canonicalImagePath(slug: string, kind: ImageKind): string {
  return `${DIRS[kind]}/${slug}.png`;
}

/** Stable FNV-1a 32-bit hash of a string. Pure JS, no crypto dependency. */
export function stableHash(input: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * Resolve the image path for a slug.
 *
 * - If `available` is omitted or empty, returns the canonical path unchanged
 *   (caller is responsible for a 404/placeholder when the file is missing).
 * - If the canonical path is present in `available`, it wins.
 * - Otherwise a stable, hash-bucketed member of `available` is returned, so a
 *   missing image degrades to a predictable existing one rather than a broken
 *   <img>.
 */
export function resolveImage(
  slug: string,
  kind: ImageKind,
  available?: readonly string[],
): string {
  const canonical = canonicalImagePath(slug, kind);
  if (!available || available.length === 0) {
    return canonical;
  }
  if (available.includes(canonical)) {
    return canonical;
  }
  const idx = stableHash(`${kind}:${slug}`) % available.length;
  return available[idx];
}

/** Convenience: canonical card image path for a slug. */
export function cardImageFor(slug: string): string {
  return canonicalImagePath(slug, "card");
}

/** Convenience: canonical OG image path for a slug. */
export function ogImageFor(slug: string): string {
  return canonicalImagePath(slug, "og");
}