import Link from "next/link";
import { CATEGORIES } from "@/lib/categories";
import { Globe } from "./Icons";

export default function SiteHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-ink-100 bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
            <Globe className="h-5 w-5" />
          </span>
          <span className="font-display text-xl font-bold tracking-tight text-ink-950">
            Nomad<span className="text-brand-600">omics</span>
          </span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex" aria-label="Primary">
          {CATEGORIES.map((c) => (
            <Link
              key={c.slug}
              href={`/category/${c.slug}`}
              className="rounded-md px-3 py-2 text-sm font-medium text-ink-700 transition-colors hover:bg-ink-50 hover:text-ink-950"
            >
              {c.name}
            </Link>
          ))}
        </nav>

        <Link
          href="/category/banking"
          className="hidden rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-700 md:inline-block"
        >
          Best accounts
        </Link>
      </div>
    </header>
  );
}
