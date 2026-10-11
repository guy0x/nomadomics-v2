/**
 * Affiliate click telemetry.
 *
 * Fires a GA4 event (via the `gtag` global, when the GA snippet is present)
 * and a fire-and-forget POST to Mission Control's /api/track ingest, which
 * appends the click to engine/clicks.jsonl for revenue attribution.
 *
 * Deliberately defensive: never throws, never blocks the outbound click.
 * In an SSR/server context there is no `window`, so this is a no-op.
 */

declare global {
  interface Window {
    gtag?: (
      command: string,
      eventName: string,
      params?: Record<string, string | number | boolean>
    ) => void;
  }
}

export function trackAffiliateClick(offerName: string, slug: string): void {
  if (typeof window === "undefined") return;
  try {
    // GA4 event — reachable whenever the site GA snippet defines window.gtag.
    window.gtag?.("event", "affiliate_click", {
      offer_name: offerName,
      article_slug: slug,
    });

    // Fire-and-forget to Mission Control ingest. keepalive lets the request
    // survive page navigation; failures are swallowed so telemetry never
    // breaks the user's click out to the partner site.
    void window
      .fetch("/api/track", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          offer_name: offerName,
          article_slug: slug,
          ts: Date.now(),
        }),
        keepalive: true,
      })
      .catch(() => {});
  } catch {
    // Telemetry must never interfere with the outbound click.
  }
}