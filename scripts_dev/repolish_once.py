"""One-off: re-polish an already-published article in place (keeps status/publishedAt)."""
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
})
print("re-polished OK")
print("  TL;DR present:", "## TL;DR" in md)
print("  metaTitle len:", len(meta_title))
print("  metaDescription len:", len(meta_desc))
