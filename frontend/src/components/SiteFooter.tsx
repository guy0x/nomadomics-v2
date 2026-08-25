import Link from "next/link";
import { CATEGORIES } from "@/lib/categories";
import { Globe } from "./Icons";

export default function SiteFooter() {
  return (
    <footer className="border-t border-ink-100 bg-ink-50">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <div className="grid gap-10 md:grid-cols-4">
          <div className="md:col-span-2">
            <Link href="/" className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
                <Globe className="h-5 w-5" />
              </span>
              <span className="font-display text-xl font-bold tracking-tight text-ink-950">
                Nomad<span className="text-brand-600">omics</span>
              </span>
            </Link>
            <p className="mt-4 max-w-sm text-sm leading-6 text-ink-600">
              Practical guides to banking, taxes, and logistics for people who
              earn in one currency and live in another.
            </p>
          </div>

          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-ink-900">
              Topics
            </h3>
            <ul className="mt-4 space-y-2">
              {CATEGORIES.map((c) => (
                <li key={c.slug}>
                  <Link
                    href={`/category/${c.slug}`}
                    className="text-sm text-ink-600 hover:text-brand-700"
                  >
                    {c.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-ink-900">
              Site
            </h3>
            <ul className="mt-4 space-y-2">
              <li>
                <Link href="/" className="text-sm text-ink-600 hover:text-brand-700">
                  Latest articles
                </Link>
              </li>
              <li>
                <Link href="/about" className="text-sm text-ink-600 hover:text-brand-700">
                  About &amp; editorial policy
                </Link>
              </li>
            </ul>
          </div>
        </div>

        <div className="mt-10 border-t border-ink-200 pt-6">
          <p className="text-xs leading-5 text-ink-500">
            <strong className="font-semibold text-ink-700">Advertiser Disclosure:</strong>{" "}
            Nomadomics is reader-supported. When you buy through links on our
            site we may earn an affiliate commission at no extra cost to you.
            This never influences our rankings or recommendations.{" "}
            <Link href="/about" className="underline hover:text-ink-700">
              Read our editorial policy
            </Link>
            .
          </p>
          <p className="mt-3 text-xs text-ink-400">
            © {new Date().getFullYear()} Nomadomics. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}
