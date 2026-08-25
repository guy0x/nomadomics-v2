import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-4 py-24 text-center sm:px-6">
      <p className="font-display text-6xl font-bold text-brand-600">404</p>
      <h1 className="mt-4 font-display text-2xl font-bold text-ink-950">Page not found</h1>
      <p className="mt-3 text-ink-600">
        The guide you&apos;re looking for doesn&apos;t exist or isn&apos;t published yet.
      </p>
      <Link
        href="/"
        className="mt-8 rounded-lg bg-brand-600 px-5 py-3 text-sm font-semibold text-white hover:bg-brand-700"
      >
        Back to the homepage
      </Link>
    </div>
  );
}
