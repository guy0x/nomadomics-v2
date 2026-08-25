import { Check, X } from "./Icons";

/** Two-column pros/cons box used on review and comparison posts. */
export default function ProsCons({ pros, cons }: { pros: string[]; cons: string[] }) {
  return (
    <section aria-label="Pros and cons" className="my-10 grid gap-4 sm:grid-cols-2">
      <div className="rounded-2xl border border-brand-200 bg-brand-50 p-5">
        <h3 className="mb-3 font-display text-base font-bold text-brand-900">Pros</h3>
        <ul className="space-y-2">
          {pros.map((p) => (
            <li key={p} className="flex items-start gap-2 text-sm leading-6 text-ink-800">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
              <span>{p}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded-2xl border border-ink-200 bg-ink-50 p-5">
        <h3 className="mb-3 font-display text-base font-bold text-ink-900">Cons</h3>
        <ul className="space-y-2">
          {cons.map((c) => (
            <li key={c} className="flex items-start gap-2 text-sm leading-6 text-ink-800">
              <X className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" />
              <span>{c}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
