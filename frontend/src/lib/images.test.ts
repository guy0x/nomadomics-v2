import { test } from "node:test";
import assert from "node:assert/strict";
import {
  canonicalImagePath,
  stableHash,
  resolveImage,
  cardImageFor,
  ogImageFor,
} from "./images.ts";

test("canonical path is kind-scoped and slug-keyed", () => {
  assert.equal(canonicalImagePath("best-vpns", "card"), "/cards/best-vpns.png");
  assert.equal(canonicalImagePath("best-vpns", "og"), "/og/best-vpns.png");
});

test("stableHash is deterministic across calls", () => {
  assert.equal(stableHash("foo"), stableHash("foo"));
  assert.notEqual(stableHash("foo"), stableHash("bar"));
  // Signed range is clamped to unsigned 32-bit
  assert.ok(stableHash("anything") >= 0);
  assert.ok(stableHash("anything") <= 0xffffffff);
});

test("resolveImage returns canonical path when no manifest is provided", () => {
  assert.equal(resolveImage("travel-hacks", "card"), "/cards/travel-hacks.png");
});

test("resolveImage prefers canonical path when present in available set", () => {
  const available = ["/cards/a.png", "/cards/travel-hacks.png"];
  assert.equal(resolveImage("travel-hacks", "card", available), "/cards/travel-hacks.png");
});

test("resolveImage falls back deterministically when canonical is missing", () => {
  const available = ["/cards/one.png", "/cards/two.png", "/cards/three.png"];
  const a = resolveImage("missing-art", "card", available);
  const b = resolveImage("missing-art", "card", available);
  // stable: same slug always picks the same fallback
  assert.equal(a, b);
  // and it always lands on a member of the available set
  assert.ok(available.includes(a));
});

test("resolveImage fallback is kind-scoped (card vs og can differ)", () => {
  const cards = ["/cards/x.png", "/cards/y.png"];
  const ogs = ["/og/x.png", "/og/y.png"];
  const card = resolveImage("nope", "card", cards);
  const og = resolveImage("nope", "og", ogs);
  // both are valid fallbacks within their own kind
  assert.ok(cards.includes(card));
  assert.ok(ogs.includes(og));
});

test("resolveImage with empty available returns canonical unchanged", () => {
  assert.equal(resolveImage("slug", "card", []), "/cards/slug.png");
});

test("convenience helpers match canonical paths", () => {
  assert.equal(cardImageFor("geoarbitrage"), "/cards/geoarbitrage.png");
  assert.equal(ogImageFor("geoarbitrage"), "/og/geoarbitrage.png");
});