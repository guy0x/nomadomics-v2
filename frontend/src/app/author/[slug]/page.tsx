import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getArticlesByAuthor,
  getAuthorBySlug,
  getAuthors,
} from "@/lib/strapi";
import ArticleCard from "@/components/ArticleCard";
import AuthorAvatar from "@/components/AuthorAvatar";
import { ChevronRight } from "@/components/Icons";

export const revalidate = 300;
export const dynamicParams = true;

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export async function generateStaticParams() {
  const authors = await getAuthors();
  return authors.map((a) => ({ slug: a.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const author = await getAuthorBySlug(slug);
  if (!author) return {};

  // The root layout template appends "· Nomadomics" — do not repeat it here.
  const title = `${author.name}${author.role ? `, ${author.role}` : ""}`;
  const description =
    author.bio ??
    `Articles by ${author.name} on banking, taxes and logistics for people who earn in one currency and live in another.`;
  const url = `${SITE_URL}/author/${author.slug}`;

  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: { title: `${title} · Nomadomics`, description, url, type: "profile" },
  };
}

export default async function AuthorPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const author = await getAuthorBySlug(slug);
  if (!author) notFound();

  const articles = await getArticlesByAuthor(author.documentId);

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Person",
    name: author.name,
    url: `${SITE_URL}/author/${author.slug}`,
    ...(author.role ? { jobTitle: author.role } : {}),
    ...(author.bio ? { description: author.bio } : {}),
    ...(author.credentials ? { knowsAbout: author.credentials } : {}),
    worksFor: { "@type": "Organization", name: "Nomadomics", url: SITE_URL },
    ...(articles.length
      ? { mainEntityOfPage: articles.slice(0, 10).map((a) => `${SITE_URL}/${a.slug}`) }
      : {}),
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <nav aria-label="Breadcrumb" className="mb-6 flex items-center gap-1.5 text-sm text-ink-500">
          <Link href="/" className="hover:text-brand-700">
            Home
          </Link>
          <ChevronRight className="h-3.5 w-3.5" />
          <span className="text-ink-700">{author.name}</span>
        </nav>

        <header className="max-w-3xl">
          <div className="flex items-center gap-4">
            <AuthorAvatar name={author.name} size={56} className="text-lg" />
            <div>
              <h1 className="font-display text-3xl font-bold leading-tight tracking-tight text-ink-950 sm:text-4xl">
                {author.name}
              </h1>
              {author.role && (
                <p className="mt-1 text-sm font-bold uppercase tracking-wide text-brand-700">
                  {author.role}
                </p>
              )}
            </div>
          </div>
          {author.bio && (
            <p className="mt-4 text-lg leading-8 text-ink-600">{author.bio}</p>
          )}
          {author.credentials && (
            <p className="mt-3 text-sm text-ink-500">{author.credentials}</p>
          )}
        </header>

        <section className="mt-12">
          <h2 className="mb-6 font-display text-2xl font-bold text-ink-950">
            {articles.length} guide{articles.length === 1 ? "" : "s"} by {author.name}
          </h2>
          {articles.length ? (
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {articles.map((a) => (
                <ArticleCard key={a.documentId} article={a} />
              ))}
            </div>
          ) : (
            <p className="text-ink-600">
              Nothing published under this byline yet —{" "}
              <Link href="/" className="font-medium text-brand-700 hover:underline">
                browse the latest guides
              </Link>
              .
            </p>
          )}
        </section>
      </div>
    </>
  );
}
