"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CATEGORIES } from "@/lib/categories";
import { Globe, Menu, X } from "./Icons";

/**
 * Site header with a mobile menu. The homepage owns the single intent bridge;
 * header and menu remain navigation-only so readers do not see duplicate CTAs.
 */
export default function SiteHeader() {
  const pathname = usePathname();
  const [openedFor, setOpenedFor] = useState<string | null>(null);
  const open = openedFor === pathname;
  const toggle = () => setOpenedFor(open ? null : pathname);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenedFor(null);
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
          {CATEGORIES.map((category) => (
            <Link
              key={category.slug}
              href={`/category/${category.slug}`}
              className="rounded-md px-3 py-2 text-sm font-medium text-ink-700 transition-colors hover:bg-ink-50 hover:text-ink-950"
            >
              {category.name}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <Link
            href="/editorial"
            className="hidden rounded-md px-3 py-2 text-sm font-medium text-ink-700 transition-colors hover:bg-ink-50 hover:text-ink-950 lg:inline-block"
          >
            About
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
            {CATEGORIES.map((category) => (
              <li key={category.slug} className="border-b border-ink-100">
                <Link
                  href={`/category/${category.slug}`}
                  className="flex min-h-[44px] items-center text-base font-medium text-ink-800 hover:text-brand-700"
                >
                  {category.name}
                </Link>
              </li>
            ))}
            <li>
              <Link
                href="/editorial"
                className="flex min-h-[44px] items-center text-base font-medium text-ink-800 hover:text-brand-700"
              >
                About
              </Link>
            </li>
          </ul>
        </nav>
      )}
    </header>
  );
}
