import type { ComparisonTable as Table } from "@/lib/offers";
import { isMonetized } from "@/lib/offers";
import { Check, X, ArrowRight } from "./Icons";

function Cell({ value }: { value: string | boolean }) {
  if (value === true) return <Check className="mx-auto h-5 w-5 text-brand-600" aria-label="Yes" />;
  if (value === false) return <X className="mx-auto h-5 w-5 text-ink-300" aria-label="No" />;
  return <span className="text-sm text-ink-800">{value}</span>;
}

/** Responsive side-by-side comparison table with per-column affiliate CTAs. */
export default function ComparisonTable({ table }: { table: Table }) {
  // Guard: only render the table if every column's offer link is monetized —
  // otherwise we'd be sending free traffic to non-partner brands.
  if (!table.columns.every((col) => isMonetized(col.offer.href))) return null;
  return (
    <section aria-label={table.heading} className="my-10">
      <h2 className="mb-4 font-display text-2xl font-bold text-ink-950">{table.heading}</h2>
      <div className="overflow-x-auto rounded-2xl border border-ink-200">
        <table className="w-full min-w-[34rem] border-collapse bg-white text-left">
          <thead>
            <tr className="border-b border-ink-200 bg-ink-50">
              <th className="px-4 py-3 text-sm font-semibold text-ink-500" scope="col">
                <span className="sr-only">Feature</span>
              </th>
              {table.columns.map((col) => (
                <th key={col.key} scope="col" className="px-4 py-3">
                  <div className="flex flex-col items-center gap-1 text-center">
                    {col.offer.badge && (
                      <span className="rounded-full bg-brand-100 px-2 py-0.5 text-[0.65rem] font-bold uppercase tracking-wide text-brand-800">
                        {col.offer.badge}
                      </span>
                    )}
                    <span className="font-display text-base font-bold text-ink-950">{col.label}</span>
                    <span className="flex items-center gap-0.5 text-xs font-semibold text-amber-500">
                      {"★".repeat(Math.round(col.offer.rating))}
                      <span className="ml-1 text-ink-500">{col.offer.rating.toFixed(1)}</span>
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, i) => (
              <tr key={row.label} className={i % 2 === 0 ? "bg-white" : "bg-ink-50/60"}>
                <th scope="row" className="px-4 py-3 text-sm font-medium text-ink-700">
                  {row.label}
                </th>
                {table.columns.map((col) => (
                  <td key={col.key} className="px-4 py-3 text-center">
                    <Cell value={row.values[col.key]} />
                  </td>
                ))}
              </tr>
            ))}
            <tr className="border-t border-ink-200 bg-white">
              <td className="px-4 py-4" />
              {table.columns.map((col) => (
                <td key={col.key} className="px-4 py-4 text-center">
                  <a
                    href={col.offer.href}
                    target="_blank"
                    rel="noopener noreferrer sponsored"
                    className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-700"
                  >
                    {col.offer.ctaLabel}
                    <ArrowRight className="h-4 w-4" />
                  </a>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
