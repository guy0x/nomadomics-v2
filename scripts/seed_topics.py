#!/usr/bin/env python3
"""
Seed the Strapi `Topic` content-type from the Nomadomics Airtable CSV export.

Usage:
    STRAPI_URL=http://localhost:1337 STRAPI_ENGINE_TOKEN=<token> python3 scripts/seed_topics.py [path/to/topics.csv]

Reads a CSV with columns: Topic, Target Keywords (comma-separated).
Creates a Topic per row. Idempotent: skips slugs that already exist.
"""
import csv
import json
import os
import re
import sys

import httpx

DEFAULT_CSV = os.path.expanduser("~/Downloads/simplified_nomadomics_airtable.csv")
BASE_URL = os.environ.get("STRAPI_URL", "http://localhost:1337").rstrip("/")
TOKEN = os.environ.get("STRAPI_ENGINE_TOKEN", "")

CATEGORY_MAP = {
    "taxes": ["tax", "feie", "income tax"],
    "banking": ["bank", "credit card", "bank ac"],
    "visas": ["visa"],
    "geoarbitrage": ["cost of living", "bali", "geo arbitrage", "geoarbitrage"],
    "digital-nomad": ["digital nomad", "nomad", "remote work", "location independence"],
    "backpacking": ["backpack", "accommodation", "travel hacks"],
    "gear": ["vpn", "apps", "coworking"],
}


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:80].rstrip("-")


def infer_category(keywords: str) -> str:
    kw = keywords.lower()
    for cat, terms in CATEGORY_MAP.items():
        if any(t in kw for t in terms):
            return cat
    return "budgeting"


def primary_keyword(keywords: str) -> str:
    parts = [p.strip() for p in keywords.split(",") if p.strip()]
    return parts[0] if parts else ""


def build_topic(row: dict) -> dict:
    title = row.get("Topic", "").strip()
    keywords = row.get("Target Keywords", "").strip()
    return {
        "data": {
            "title": title,
            "slug": slugify(title),
            "primaryKeyword": primary_keyword(keywords),
            "targetKeywords": [p.strip() for p in keywords.split(",") if p.strip()],
            "category": infer_category(keywords),
            "targetWordCount": 1800,
            "priority": 5,
            "status": "pending",
        }
    }


def headers() -> dict:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }


def main() -> int:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    if not TOKEN:
        print("ERROR: STRAPI_ENGINE_TOKEN not set")
        return 1
    if not os.path.exists(csv_path):
        print(f"ERROR: CSV not found: {csv_path}")
        return 1

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    with httpx.Client(base_url=BASE_URL, headers=headers(), timeout=30) as client:
        # Fetch existing slugs to keep idempotent
        existing = set()
        try:
            r = client.get("/api/topics", params={"pagination[pageSize]": 100})
            r.raise_for_status()
            existing = {t["slug"] for t in r.json()["data"]}
        except Exception as e:
            print(f"WARN: could not list existing topics: {e}")

        created, skipped, failed = 0, 0, 0
        for row in rows:
            if not row.get("Topic", "").strip():
                continue
            topic = build_topic(row)
            slug = topic["data"]["slug"]
            if slug in existing:
                skipped += 1
                continue
            try:
                r = client.post("/api/topics", json=topic)
                if r.status_code in (200, 201):
                    created += 1
                    existing.add(slug)
                else:
                    failed += 1
                    print(f"  FAIL {slug}: {r.status_code} {r.text[:120]}")
            except Exception as e:
                failed += 1
                print(f"  ERR  {slug}: {e}")

    print(f"Seeded: {created} created, {skipped} skipped (existing), {failed} failed")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
