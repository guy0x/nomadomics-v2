"use client";

import { useEffect, useState } from "react";
import { List } from "./Icons";

export interface TocItem {
  id: string;
  text: string;
}

/** Desktop sticky TOC with scroll-spy active highlighting. */
export default function TableOfContents({ items }: { items: TocItem[] }) {
  const [active, setActive] = useState<string>(items[0]?.id ?? "");

  useEffect(() => {
    const headings = items
      .map((i) => document.getElementById(i.id))
      .filter((el): el is HTMLElement => el !== null);
    if (headings.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(entry.target.id);
        }
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: 0 }
    );
    headings.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, [items]);

  if (items.length === 0) return null;

  return (
    <nav aria-label="Table of contents" className="rounded-2xl border border-ink-200 bg-white p-5">
      <p className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-ink-500">
        <List className="h-4 w-4" />
        On this page
      </p>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.id}>
            <a
              href={`#${item.id}`}
              className={`block rounded-md border-l-2 px-3 py-1.5 text-sm transition-colors ${
                active === item.id
                  ? "border-brand-600 bg-brand-50 font-semibold text-brand-800"
                  : "border-transparent text-ink-600 hover:border-ink-200 hover:text-ink-950"
              }`}
            >
              {item.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
