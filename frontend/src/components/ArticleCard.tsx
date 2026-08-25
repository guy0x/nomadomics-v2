import Link from "next/link";
import type { StrapiArticle } from "@/lib/strapi";
import { readingTimeMinutes } from "@/lib/strapi";
import { categoryForSlug } from "@/lib/categories";
import { Clock, ArrowRight } from "./Icons";

const CATEGORY_GRADIENT: Record<string, string> = {
  banking: "from-brand-500 to-brand-700",
  taxes: "from-emerald-500 to-teal-700",
  travel: "from-sky-500 to-indigo-600",
  gear: "from-violet-500 to-purple-700",
  cities: "from-amber-500 to-orange-600",
};

export default function ArticleCard({ article, priority = false }: { article: StrapiArticle; priority?: boolean }) {
  const category = categoryForSlug(article.slug);
  const mins = readingTimeMinutes(article.bodyMarkdown);
  const gradient = CATEGORY_GRADIENT[category.slug] ?? "from-brand-500 to-brand-700";

  return (
    <Link
      href={`/${article.slug}`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-ink-200 bg-white transition-shadow hover:shadow-lg"
    >
      <div className={`relative flex h-44 items-end bg-gradient-to-br ${gradient} p-4`}>
        <span className="rounded-full bg-white/90 px-2.5 py-1 text-[0.7rem] font-bold uppercase tracking-wide text-ink-800">
          {category.name}
        </span>
      </div>
      <div className="flex flex-1 flex-col p-5">
        <h3 className="font-display text-lg font-bold leading-snug text-ink-950 group-hover:text-brand-700">
          {article.title}
        </h3>
        {article.excerpt && (
          <p className="mt-2 line-clamp-3 flex-1 text-sm leading-6 text-ink-600">{article.excerpt}</p>
        )}
        <div className="mt-4 flex items-center justify-between text-xs text-ink-500">
          <span className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            {mins} min read
          </span>
          <span className="flex items-center gap-1 font-semibold text-brand-700">
            Read
            <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
          </span>
        </div>
      </div>
    </Link>
  );
}
