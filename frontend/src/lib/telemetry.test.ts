import { test } from "node:test";
import assert from "node:assert/strict";
import { trackAffiliateClick } from "./telemetry.ts";

type GtagArgs = [string, string, Record<string, string | number | boolean>?];

/**
 * Stub a browser-like `window` (gtag + fetch) for the duration of `run`,
 * capturing gtag calls and the outgoing fetch, then restore globals.
 */
function withBrowserGlobals(run: () => void): { gtagCalls: GtagArgs[]; posted?: { url: string; init?: RequestInit } } {
  const gtagCalls: GtagArgs[] = [];
  let posted: { url: string; init?: RequestInit } | undefined;
  const g = globalThis as Record<string, unknown>;
  const originalWindow = g.window;
  const originalFetch = g.fetch;
  g.window = {
    gtag: (...args: GtagArgs) => {
      gtagCalls.push(args);
    },
    fetch: (url: string, init?: RequestInit) => {
      posted = { url, init };
      return Promise.resolve({ ok: true } as Response);
    },
  };
  try {
    run();
  } finally {
    if (originalWindow === undefined) delete g.window;
    else g.window = originalWindow;
    if (originalFetch === undefined) delete g.fetch;
    else g.fetch = originalFetch;
  }
  return { gtagCalls, posted };
}

test("trackAffiliateClick fires a gtag affiliate_click event with offer + slug", () => {
  const { gtagCalls } = withBrowserGlobals(() => {
    trackAffiliateClick("Wise", "wise-vs-revolut");
  });
  assert.equal(gtagCalls.length, 1);
  assert.deepEqual(gtagCalls[0], [
    "event",
    "affiliate_click",
    { offer_name: "Wise", article_slug: "wise-vs-revolut" },
  ]);
});

test("trackAffiliateClick POSTs the click to /api/track with keepalive", () => {
  const { posted } = withBrowserGlobals(() => {
    trackAffiliateClick("Wise", "wise-vs-revolut");
  });
  assert.ok(posted, "fetch must be called");
  assert.equal(posted.url, "/api/track");
  assert.equal(posted.init?.method, "POST");
  assert.equal(posted.init?.keepalive, true);
  const body = JSON.parse(String(posted.init?.body));
  assert.equal(body.offer_name, "Wise");
  assert.equal(body.article_slug, "wise-vs-revolut");
  assert.equal(typeof body.ts, "number");
});

test("trackAffiliateClick is a no-op without a window (SSR)", () => {
  const g = globalThis as Record<string, unknown>;
  const originalWindow = g.window;
  delete g.window;
  try {
    assert.doesNotThrow(() => trackAffiliateClick("Wise", "no-ssr"));
  } finally {
    if (originalWindow === undefined) delete g.window;
    else g.window = originalWindow;
  }
});