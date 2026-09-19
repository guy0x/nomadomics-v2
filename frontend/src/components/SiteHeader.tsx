"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CATEGORIES } from "@/lib/categories";
import { Globe, Menu, X } from "./Icons";

/**
 * Site header with a mobile menu.
 *
 * The desktop nav and the money CTA are both hidden below `md`, which used to
 * leave a phone with nothing but the logo — topic pages were reachable only by
 * scrolling to the footer. This is a client component purely for the toggle.
 */
export default function SiteHeader() {
  const pathname = usePathname();
  // The panel is open only while we are still on the path it was opened from, so
  // a navigation closes it without any effect resetting state. Do NOT close it
  // from the link's onClick: unmounting the anchor mid-click cancels the
  // browser's default navigation and the tap does nothing.
  const [openedFor, setOpenedFor] = useState<string | null>(null);
  const open = openedFor === pathname;
  const toggle = () => setOpenedFor(open ? null : pathname);

  // Escape closes the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenedFor(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

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

        <div className="flex items-center gap-2">
          <Link
            href="/category/banking"
            className="hidden rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-700 md:inline-block"
          >
            Best accounts
          </Link>
          <button
            type="button"
            onClick={toggle}
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            aria-controls="mobile-nav"
            className="-mr-1 flex h-11 w-11 items-center justify-center rounded-lg text-ink-700 transition-colors hover:bg-ink-50 md:hidden"
          >
            {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </button>
        </div>
      </div>

      {open && (
        <nav
          id="mobile-nav"
          aria-label="Primary (mobile)"
          className="border-t border-ink-100 bg-white md:hidden"
        >
          <ul className="mx-auto max-w-6xl px-4 py-1 sm:px-6">
            {CATEGORIES.map((c) => (
              <li key={c.slug} className="border-b border-ink-100">
                <Link
                  href={`/category/${c.slug}`}
                  className="flex min-h-[44px] items-center text-base font-medium text-ink-800 hover:text-brand-700"
                >
                  {c.name}
                </Link>
              </li>
            ))}
            <li className="py-3">
              <Link
                href="/category/banking"
                className="flex min-h-[44px] items-center justify-center rounded-lg bg-brand-600 px-4 text-sm font-semibold text-white"
              >
                Best accounts
              </Link>
            </li>
          </ul>
        </nav>
      )}
    </header>
  );
}
