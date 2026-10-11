#!/usr/bin/env python3
"""Count and, only with an explicit gate, backfill Strapi ``siteKey`` values.

The default is read-only. Articles are read and written in the Strapi draft layer;
no call in this script targets the published layer. A live run requires both
``--apply`` and the exact ``--site-key nomadomics`` acknowledgement.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

from config import load_config  # noqa: E402
from strapi import StrapiClient  # noqa: E402

PAGE_SIZE = 100
COLLECTIONS = ("topics", "articles")


def _fields(row: dict[str, Any]) -> dict[str, Any]:
    """Support Strapi v5 flat rows and older fixture-shaped rows."""
    nested = row.get("attributes")
    if isinstance(nested, dict):
        return {**row, **nested}
    return row


def _document_id(row: dict[str, Any]) -> str:
    return str(row.get("documentId") or _fields(row).get("documentId") or "")


def read_rows(client: StrapiClient, collection: str) -> list[dict[str, Any]]:
    """Read the complete collection using paginated Strapi REST reads."""
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        params: dict[str, Any] = {
            "pagination[page]": page,
            "pagination[pageSize]": PAGE_SIZE,
        }
        if collection == "articles":
            # Draft layer is required so draft-only articles are included and
            # every later write has the same explicit layer.
            params["status"] = "draft"
        response = client._request("GET", f"/api/{collection}", params=params)
        batch = response.get("data", [])
        if not isinstance(batch, list):
            raise RuntimeError(f"Strapi returned an invalid {collection} data payload")
        rows.extend(row for row in batch if isinstance(row, dict))
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    return rows


def inventory(rows: list[dict[str, Any]], site_key: str) -> dict[str, Any]:
    ids = [_document_id(row) for row in rows if _document_id(row)]
    counts = Counter(ids)
    duplicates = {doc_id: count for doc_id, count in sorted(counts.items()) if count > 1}
    missing = [row for row in rows if not str(_fields(row).get("siteKey") or "").strip()]
    return {
        "rows": len(rows),
        "missing_site_key": len(missing),
        "duplicate_document_ids": duplicates,
        "unaddressable_rows": sum(1 for row in missing if not _document_id(row)),
        "_missing_rows": missing,
        "_site_key": site_key,
    }


def _read_one(client: StrapiClient, collection: str, document_id: str) -> dict[str, Any]:
    params = {"status": "draft"} if collection == "articles" else None
    response = client._request("GET", f"/api/{collection}/{document_id}", params=params)
    row = response.get("data")
    if not isinstance(row, dict):
        raise RuntimeError(f"Strapi returned no {collection} row after update")
    return row


def apply_missing(
    client: StrapiClient,
    inventories: dict[str, dict[str, Any]],
    site_key: str,
) -> int:
    """Write each missing document once, then verify it with a draft read."""
    updated = 0
    for collection in COLLECTIONS:
        seen: set[str] = set()
        for row in inventories[collection]["_missing_rows"]:
            document_id = _document_id(row)
            if not document_id:
                raise RuntimeError(f"cannot update {collection} row without documentId")
            if document_id in seen:
                continue
            seen.add(document_id)
            if collection == "articles":
                client.update_article(document_id, {"siteKey": site_key}, status="draft")
            else:
                client.update_topic(document_id, {"siteKey": site_key})
            after = _read_one(client, collection, document_id)
            if str(_fields(after).get("siteKey") or "").strip() != site_key:
                raise RuntimeError(f"siteKey verification failed for {collection} update")
            updated += 1
    return updated


def _public_report(inventories: dict[str, dict[str, Any]], *, site_key: str, applied: bool, updated: int = 0) -> dict[str, Any]:
    return {
        "site_key": site_key,
        "mode": "apply" if applied else "dry-run",
        "updated": updated,
        "collections": {
            collection: {
                key: value
                for key, value in inventories[collection].items()
                if not key.startswith("_")
            }
            for collection in COLLECTIONS
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write missing siteKey values")
    parser.add_argument("--dry-run", action="store_true", help="explicitly select the read-only default")
    parser.add_argument("--site-key", help="site key to report/backfill (default: nomadomics)")
    args = parser.parse_args(argv)
    site_key = (args.site_key or "nomadomics").strip()
    if not site_key:
        parser.error("--site-key cannot be empty")
    if args.apply and (args.site_key != "nomadomics"):
        parser.error("live mode requires the exact acknowledgement --apply --site-key nomadomics")

    cfg = load_config()
    client = StrapiClient(cfg)
    try:
        inventories = {
            collection: inventory(read_rows(client, collection), site_key)
            for collection in COLLECTIONS
        }
        updated = apply_missing(client, inventories, site_key) if args.apply else 0
        print(json.dumps(_public_report(inventories, site_key=site_key, applied=args.apply, updated=updated), sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI must return non-zero on first write/read error
        print(f"backfill_site_key: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
