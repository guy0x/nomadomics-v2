"use client";

import { useState } from "react";
import { Info, X } from "./Icons";

/**
 * FTC-compliant advertiser disclosure. Renders a subtle inline badge that
 * expands into a modal with the full policy — the MoneyMade/NerdWallet pattern.
 */
export default function AdvertiserDisclosure() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-full border border-ink-200 bg-ink-50 px-3 py-1 text-xs font-medium text-ink-600 transition-colors hover:border-ink-300 hover:text-ink-800"
      >
        <Info className="h-3.5 w-3.5" />
        Advertiser Disclosure
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[70] flex items-end justify-center bg-ink-950/50 p-4 sm:items-center"
          role="dialog"
          aria-modal="true"
          aria-label="Advertiser disclosure"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <h2 className="font-display text-lg font-bold text-ink-950">
                Advertiser Disclosure
              </h2>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="rounded-md p-1 text-ink-400 hover:bg-ink-50 hover:text-ink-700"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mt-3 space-y-3 text-sm leading-6 text-ink-700">
              <p>
                Nomadomics is reader-supported. When you click links to products
                and services we recommend and make a purchase, we may receive
                compensation from those partners at no additional cost to you.
              </p>
              <p>
                This compensation may influence which products we review and
                where they appear on the site, but it{" "}
                <strong className="font-semibold text-ink-900">
                  never influences our editorial judgment
                </strong>
                . Our rankings, scores, and recommendations are based on
                independent research, hands-on testing, and analysis.
              </p>
              <p>
                We do not accept payment in exchange for positive reviews, and
                partners never see content before it is published.
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
