"""One-off: re-polish an already-published article.

Writes the DRAFT layer only (t_60ad2c8e): without an explicit `?status=`, Strapi
v5 writes through to the published layer and re-stamps `publishedAt`, silently
republishing. An edit of a live article is a two-step: run this, then publish
deliberately (engine.cli publish / Strapi admin).
"""
import sys

sys.path.insert(0, "engine")

from config import load_config
from strapi import StrapiClient
from publish import polish_article, pick_link_targets, list_published

SLUG = "travel-insurance-for-digital-nomads"

cfg = load_config()
client = StrapiClient(cfg)

# Fetch the published article by slug.
data = client._request(
    "GET",
    "/api/articles",
    params={"filters[slug][$eq]": SLUG, "pagination[pageSize]": 1},
)
rows = data.get("data", [])
if not rows:
    raise SystemExit(f"article not found: {SLUG}")
a = rows[0]

related = pick_link_targets(list_published(client))
primary_kw = a.get("focusKeyword") or ""
polished = polish_article(a, primary_kw, related, cfg)
if not polished:
    raise SystemExit("polish failed even with fallback")

md = polished["markdown"]
meta_title = polished["metaTitle"][:57].rstrip() + "..." if len(polished["metaTitle"]) > 60 else polished["metaTitle"]
meta_desc = polished["metaDescription"][:157].rstrip() + "..." if len(polished["metaDescription"]) > 160 else polished["metaDescription"]

client.update_article(a["documentId"], {
    "bodyMarkdown": md,
    "metaTitle": meta_title,
    "metaDescription": meta_desc,
}, status="draft")

# Year hygiene guard (same as publish_one): force current year in meta fields.
import re as _re
CUR = "2026"
meta_title = _re.sub(r"\b20\d{2}\b", CUR, meta_title)
meta_desc = _re.sub(r"\b20\d{2}\b", CUR, meta_desc)
client.update_article(a["documentId"], {
    "metaTitle": meta_title,
    "metaDescription": meta_desc,
}, status="draft")
print("year-guard pass applied")
print("re-polished OK — DRAFT layer only; the live body is unchanged until a "
      "deliberate publish step (t_60ad2c8e).")
print("  TL;DR present:", "## TL;DR" in md)
print("  metaTitle len:", len(meta_title))
print("  metaDescription len:", len(meta_desc))
