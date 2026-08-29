"use client";

import { useEffect, useState } from "react";
import type { Offer } from "@/lib/offers";
import { isMonetized } from "@/lib/offers";
import { ArrowRight, Star, X } from "./Icons";

/**
 * Mobile-first sticky bottom bar highlighting the #1 pick. Appears after the
 * user scrolls past the hero, dismissible for the session.
 */
export default function StickyOfferBar({ offer }: { offer: Offer }) {
  const [visible, setVisible] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 480);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  if (dismissed) return null;

  // Guard: no sticky CTA unless the offer link is monetized (no free traffic).
  if (!isMonetized(offer.href)) return null;

  return (
    <div
      className={`fixed inset-x-0 bottom-0 z-50 transition-transform duration-300 ${
        visible ? "translate-y-0" : "translate-y-full"
      }`}
      role="complementary"
      aria-label="Top recommendation"
    >
      <div className="mx-auto max-w-6xl px-3 pb-3 sm:px-6 sm:pb-4">
        <div className="flex items-center gap-3 rounded-xl border border-ink-200 bg-white p-3 shadow-[0_-4px_24px_rgba(0,0,0,0.12)]">
          <div className="hidden h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-brand-600 font-display text-lg font-bold text-white sm:flex">
            {offer.name.charAt(0)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate text-sm font-bold text-ink-950">{offer.name}</p>
              {offer.badge && (
                <span className="hidden rounded-full bg-brand-100 px-2 py-0.5 text-[0.65rem] font-bold uppercase tracking-wide text-brand-800 sm:inline">
                  {offer.badge}
                </span>
              )}
            </div>
            <p className="flex items-center gap-1 text-xs text-ink-500">
              <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
              {offer.rating.toFixed(1)} · {offer.tagline}
            </p>
          </div>
          <a
            href={offer.href}
            target="_blank"
            rel="noopener noreferrer sponsored"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-700"
          >
            <span className="hidden sm:inline">{offer.ctaLabel}</span>
            <span className="sm:hidden">Visit</span>
            <ArrowRight className="h-4 w-4" />
          </a>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            aria-label="Dismiss"
            className="shrink-0 rounded-md p-1.5 text-ink-400 hover:bg-ink-50 hover:text-ink-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
