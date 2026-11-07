/** Route-level fallback shown while a streamed route is resolving. */
export default function Loading() {
  return (
    <div
      className="mx-auto max-w-6xl animate-pulse px-4 py-12 sm:px-6"
      role="status"
      aria-live="polite"
      aria-label="Loading page"
    >
      <div className="h-5 w-28 rounded bg-ink-100" />
      <div className="mt-6 h-12 max-w-3xl rounded bg-ink-100" />
      <div className="mt-4 h-6 max-w-2xl rounded bg-ink-100" />
      <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((card) => (
          <div key={card} className="overflow-hidden rounded-2xl border border-ink-200 bg-white">
            <div className="aspect-[16/9] bg-ink-100" />
            <div className="space-y-3 p-5">
              <div className="h-4 w-20 rounded bg-ink-100" />
              <div className="h-6 w-full rounded bg-ink-100" />
              <div className="h-4 w-4/5 rounded bg-ink-100" />
            </div>
          </div>
        ))}
      </div>
      <span className="sr-only">Loading page</span>
    </div>
  );
}