#!/usr/bin/env python3
"""Link-hygiene repair for Nomadomics article bodies (Guy, 2026-10-05).

Repairs the four violation shapes `invariants.link_hygiene_issues` flags:

  1. WRONG-DOMAIN slug anchors   `[digital-nomad-communities-every-major-hub](https://nomadlist.com)`
       -> repoint to the internal `/slug` page (the slug names a Nomadomics
          article, so an external `nomadlist.com` href is a copy-paste bug).
  2. SLUG-ANCHOR links           `[best-esim-plans-for-digital-nomads](/best-esim-plans-for-digital-nomads)`
       -> natural anchor text from the target article's title map.
  3. RAW URLs in prose           `(source: https://www.irs.gov/publications/p54)`
       -> `([source](url))` so the URL becomes a real hyperlink.
  4. FULL-WIDTH bracket URLs     `€1,200【https://.../Barcelona】`
       -> `([Numbeo](url))` so the URL becomes a real hyperlink, anchored on
          the site name.

Run (dry-run):   env -u PYTHONPATH .venv/bin/python scripts/link_hygiene_repair.py --dry-run
Apply:           env -u PYTHONPATH .venv/bin/python scripts/link_hygiene_repair.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from config import load_config  # noqa: E402
from invariants import ensure_internal_links, link_hygiene_issues  # noqa: E402
from strapi import StrapiClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# slug -> natural anchor text (drawn from the target article titles, 2026-10-05)
ANCHORS = {
    "best-esim-plans-for-digital-nomads": "best eSIM plans for digital nomads",
    "how-to-legally-pay-less-tax-as-a-digital-nomad": "how to legally pay less tax as a digital nomad",
    "crypto-taxes-for-digital-nomads": "crypto taxes for digital nomads",
    "coliving-vs-apartment-rental-digital-nomads": "coliving vs apartment rental",
    "coffee-shop-work-etiquette-digital-nomads": "coffee shop work etiquette",
    "cost-of-living-chiang-mai": "the cost of living in Chiang Mai",
    "slow-travel-budget-digital-nomad": "a slow travel budget",
    "digital-nomad-communities-every-major-hub": "digital nomad communities",
    "essential-apps-for-digital-nomads": "essential apps for digital nomads",
    "travel-insurance-exclusions": "travel insurance exclusions",
}

# full-width bracket URL site-name anchors (from surrounding prose)
FW_SITES = {
    "numbeo.com": "Numbeo",
    "expatistan.com": "Expatistan",
    "nomadlist.com": "Nomad List",
}

MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
# full-width bracket __url__ e.g. 【https://x/Barcelona】
FW_URL = re.compile(r"\u3010(https?://[^\s\u3011]+)\u3011")
# raw URL already split from md-link targets
RAW_URL = re.compile(r"(?<![\]\w.])https?://[^\s\)\]\u3011\u300d\u3000\"'<>]+")


def _site(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def repair_body(body: str) -> tuple[str, list[str]]:
    """Return (repaired_body, changes). Idempotent on a clean body."""
    out = body
    changes: list[str] = []

    # 1 & 2: fix markdown-link anchors (slug -> natural, wrong-domain -> internal)
    def fix_link(m: re.Match) -> str:
        anchor, url = m.group(1).strip(), m.group(2).strip()
        slug_re = re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)+$", anchor)
        new_url = url
        # wrong-domain: slug anchor aimed at external host -> internal /slug
        if slug_re and re.match(r"https?://", url):
            dom = _site(url)
            if not re.match(r"(?:www\.)?nomadomics\.(?:com|blog)$", dom) and anchor in ANCHORS:
                new_url = f"/{anchor}"
        text = ANCHORS.get(anchor, anchor) if slug_re else anchor
        return f"[{text}]({new_url})"

    pre = out
    out = MD_LINK.sub(fix_link, out)
    if out != pre:
        changes.append("md-link anchors rewritten")

    # 3: full-width bracket URLs -> ([SiteName](url))
    def fix_fw(m: re.Match) -> str:
        url = m.group(1)
        site = FW_SITES.get(_site(url), _site(url))
        return f" ([{site}]({url}))"
    pre = out
    out = FW_URL.sub(fix_fw, out)
    if out != pre:
        changes.append("full-width bracket URLs wrapped as links")

    # 4: remaining raw URLs in prose. Wrap the "(source: URL)" pattern.
    def fix_raw(m: re.Match) -> str:
        url = m.group(0)
        return f"[source]({url})"
    pre = out
    # only hit URLs preceded by "source: " (the known corpus shape)
    out, n = re.subn(r"source:\s*(" + RAW_URL.pattern + r")", r"[source](\1)", out)
    if n:
        changes.append(f"{n} raw '(source: url)' prose URLs wrapped as links")
    return out, changes


def load_articles(client: httpx.Client, base: str, headers: dict) -> list[dict]:
    arts, page = [], 1
    while True:
        r = client.get(f"{base}/api/articles", params={
            "pagination[page]": page, "pagination[pageSize]": 50,
            "fields": ["slug", "bodyMarkdown"],
        }, headers=headers, timeout=30)
        d = r.json()["data"]
        arts.extend(d)
        if len(d) < 50:
            break
        page += 1
    return arts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slug", help="repair only this slug")
    args = ap.parse_args()

    env = dict(os.environ)
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env.setdefault(k, v)
    base = env.get("STRAPI_URL", "http://localhost:1337").rstrip("/")
    headers = {"Authorization": f"Bearer {env['STRAPI_ENGINE_TOKEN']}"}

    with httpx.Client(timeout=30) as client:
        # Internal-link corpus, same source the write path uses (t_9cdd1df7):
        # StrapiClient.list_published_titles() -> [{slug, title}], [] on any
        # failure. list_published_titles is failure-safe by contract, so the
        # backstop degrades to a no-op when the corpus is unavailable, exactly
        # like engine/pipeline_cli.py's write-path backstop.
        strapi = StrapiClient(load_config(environ=env))
        corpus = strapi.list_published_titles()
        arts = load_articles(client, base, headers)
        touched: list[dict] = []
        for a in arts:
            slug = a.get("slug")
            body = a.get("bodyMarkdown") or ""
            if not body or link_hygiene_issues(body) == []:
                continue
            if args.slug and slug != args.slug:
                continue
            new_body, changes = repair_body(body)
            # Backstop before the PUT (t_9cdd1df7): this path writes
            # bodyMarkdown directly, so without the same ensure_internal_links
            # call engine/pipeline_cli.py runs on its write path, a repair PUT
            # could re-lower an article below the link floor (the
            # best-coworking-spaces-for-digital-nomads 0-link recurrence).
            # Idempotent, never self-links (own_slug), adds only missing links
            # — the anchor-reformatting above is untouched.
            backstopped = ensure_internal_links(new_body, corpus, own_slug=slug)
            if backstopped != new_body:
                changes.append("internal-link backstop applied")
            new_body = backstopped
            touched.append({"slug": slug, "changes": changes,
                            "before_len": len(body), "after_len": len(new_body),
                            "issues_before": link_hygiene_issues(body),
                            "issues_after": link_hygiene_issues(new_body)})
            if args.dry_run:
                continue
            # PUT update via Strapi v5 documentId API
            doc = a.get("documentId")
            if doc:
                r = client.put(f"{base}/api/articles/{doc}",
                               json={"data": {"bodyMarkdown": new_body}},
                               headers=headers, timeout=30)
                touched[-1]["status"] = r.status_code
            else:
                touched[-1]["status"] = "NO_DOCUMENT_ID"

        print(json.dumps(touched, indent=1))
        print(f"\nTOTAL TOUCHED: {len(touched)} ({'dry-run' if args.dry_run else 'applied'})")
        if not args.dry_run:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            (ROOT / "logs" / f"link-hygiene-repair-{stamp}.json").write_text(
                json.dumps(touched, indent=1))


if __name__ == "__main__":
    main()