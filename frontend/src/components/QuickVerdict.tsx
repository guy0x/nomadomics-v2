import type { QuickVerdict as Verdict } from "@/lib/offers";
import { isMonetized } from "@/lib/offers";
import { Star, Check, ArrowRight, Award } from "./Icons";

/** MoneyMade-style above-the-fold verdict box with score + primary CTA. */
export default function QuickVerdict({ verdict }: { verdict: Verdict }) {
  const { offer } = verdict;
  // Guard: no CTA unless the offer link is actually monetized (no free traffic).
  if (!isMonetized(offer.href)) return null;
  return (
    <aside
      aria-label="Quick verdict"
      className="my-8 overflow-hidden rounded-2xl border-2 border-brand-200 bg-brand-50"
    >
      <div className="flex items-center justify-between gap-4 border-b border-brand-200 bg-white px-5 py-3">
        <div className="flex items-center gap-2">
          <Award className="h-5 w-5 text-brand-600" />
          <h2 className="font-display text-base font-bold text-ink-950">
            {verdict.heading}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 rounded-full bg-brand-600 px-2.5 py-1 text-sm font-bold text-white">
            <Star className="h-3.5 w-3.5 fill-white" />
            {verdict.score.toFixed(1)}
          </span>
          <span className="hidden text-xs font-semibold uppercase tracking-wide text-brand-700 sm:inline">
            {verdict.scoreLabel}
          </span>
        </div>
      </div>

      <div className="px-5 py-4">
        <ul className="space-y-2.5">
          {verdict.bullets.map((b) => (
            <li key={b} className="flex items-start gap-2.5 text-[0.95rem] leading-6 text-ink-800">
              <Check className="mt-1 h-4 w-4 shrink-0 text-brand-600" />
              <span>{b}</span>
            </li>
          ))}
        </ul>

        <div className="mt-5 flex flex-col gap-3 rounded-xl border border-brand-200 bg-white p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            {offer.badge && (
              <span className="mb-1 inline-block rounded-full bg-brand-100 px-2 py-0.5 text-[0.7rem] font-bold uppercase tracking-wide text-brand-800">
                {offer.badge}
              </span>
            )}
            <p className="font-display text-lg font-bold text-ink-950">{offer.name}</p>
            <p className="text-sm text-ink-600">{offer.tagline}</p>
          </div>
          <a
            href={offer.href}
            target="_blank"
            rel="noopener noreferrer sponsored"
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-brand-600 px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-brand-700"
          >
            {offer.ctaLabel}
            <ArrowRight className="h-4 w-4" />
          </a>
        </div>
      </div>
    </aside>
  );
}
