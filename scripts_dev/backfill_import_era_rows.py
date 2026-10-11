#!/usr/bin/env python3
"""Backfill excerpt + real citations for the 8 import-era `in_review` rows.

Kanban t_c34b93eb (from the t_e7d03242 ruling, Guy 2026-09-25: ship the publish
union as-is, then card the repair). The union made 25 documents visible to the
13:00 publish lane, but every non-quarantined conf>=75 row was still rejected by
the pre-existing ratified-E invariants (`engine/invariants.py`): empty excerpt
and/or fewer than two real citations, both imported before the writer emitted
inline citations. Eligible to auto-publish was therefore 0.

This script repairs those rows in place — excerpt, de-templated metaDescription,
and a `## Sources` section built from real, live-checked URLs — and leaves every
gate alone. Only fields a row is actually missing are written:

  excerpt          written only when the row's excerpt is empty
  metaDescription  written only when it still carries the WordPress-migration
                   template tail ("Learn how to save money on ..."), which the
                   content-invariants monitor flags as a NEW issue once live
  bodyMarkdown     `ensure_body_citations` appends `## Sources` only when the
                   body has fewer than two citations that resolve live

Writes use `StrapiClient.update_article(status="draft")` — the WORKING layer
only. The published layer and `publishedAt` are never touched (all eight rows
have `publishedAt: None`; none is live).

Usage:
    backfill_import_era_rows.py                     # dry run: report the plan
    backfill_import_era_rows.py --apply             # write, then re-verify
    backfill_import_era_rows.py --apply --report r.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

import publish  # noqa: E402,F401 — engine import path anchor
from config import load_config  # noqa: E402
from invariants import article_invariant_errors, body_citation_urls, ensure_body_citations  # noqa: E402
from strapi import StrapiClient  # noqa: E402

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
# The migration template the content-invariants monitor rejects:
# `nomadomics_content_invariants.py` TEMPLATE_RE, duplicated here on purpose so
# this one-off repair does not depend on that module's import side effects.
TEMPLATE_RE = re.compile(r"(^[a-z][a-z ]{0,40} Guide$)|(Learn how to save money on )", re.I)

# ---------------------------------------------------------------------------
# The repair plan. Every URL below was checked live (HTTP 200, browser UA,
# redirects followed) on 2026-09-25 before being written into an article.
# ---------------------------------------------------------------------------
REPAIRS: dict[str, dict] = {
    "cost-of-living-mexico-city": {
        "documentId": "koqr3w8hze1nezbi33vk6e9c",
        "excerpt": None,  # already present and card-ready
        "metaDescription": None,
        "sources": [
            ("Numbeo — Cost of Living in Mexico City", "https://www.numbeo.com/cost-of-living/in/Mexico-City"),
            ("Numbeo — Mexico City cost-of-living estimator", "https://www.numbeo.com/cost-of-living/city-estimator/in/Mexico-City"),
            ("Mexico City — official visitor guide (CDMX government)", "https://mexicocity.cdmx.gob.mx/"),
            ("Ecobici — Mexico City bike-share (official)", "https://ecobici.cdmx.gob.mx/"),
        ],
    },
    "best-vpn-for-digital-nomads": {
        "documentId": "yckd27md4jktxyekslclirde",
        "excerpt": (
            "A few dollars a month buys encrypted Wi-Fi, a hidden location and safe banking "
            "abroad. How ExpressVPN, NordVPN and Surfshark compare for nomads."
        ),
        "metaDescription": None,  # migration template -> TEMPLATE_META_REPLACEMENTS
        "sources": [
            ("ExpressVPN — official site", "https://www.expressvpn.com/"),
            ("Surfshark — official site", "https://surfshark.com/"),
            ("CNET — Best VPN Services", "https://www.cnet.com/tech/services-and-software/best-vpn/"),
        ],
    },
    "essential-apps-for-digital-nomads": {
        "documentId": "pd1ju89q1jnh9s38l15ptgqb",
        "excerpt": (
            "Roaming fees drop by up to 90% with an eSIM, a solid VPN costs under $3.50 a "
            "month, and an offline map is free. Ten apps nomads actually keep."
        ),
        "metaDescription": None,  # migration template -> TEMPLATE_META_REPLACEMENTS
        "sources": [
            ("Wise — multi-currency accounts", "https://wise.com/"),
            ("Notion — official site", "https://www.notion.com/"),
            ("Trello — official site", "https://trello.com/"),
            ("Asana — official site", "https://asana.com/"),
            ("Citymapper — official site", "https://citymapper.com/"),
            ("Maps.me — offline maps", "https://maps.me/"),
            ("XE — currency converter", "https://www.xe.com/currencyconverter/"),
            ("Holafly — travel eSIM plans", "https://esim.holafly.com/"),
            ("ExpressVPN — official site", "https://www.expressvpn.com/"),
            ("Surfshark — official site", "https://surfshark.com/"),
        ],
    },
    "cost-of-living-in-bali-for-digital-nomads": {
        "documentId": "ro2jdx8sw9rzjdtonre9rr5i",
        "excerpt": None,  # already present and card-ready
        "metaDescription": None,  # 160c, no template tail
        "sources": [
            ("Numbeo — Cost of Living in Bali", "https://www.numbeo.com/cost-of-living/in/Bali"),
            ("Numbeo — Cost of Living in Denpasar", "https://www.numbeo.com/cost-of-living/in/Denpasar"),
            ("Hubud — coworking space in Ubud, Bali", "https://hubud.org/"),
            ("Government of Bali Province — official site", "https://baliprov.go.id/"),
            ("Ministry of Foreign Affairs of Indonesia — visas (official)", "https://kemlu.go.id/portal/en"),
        ],
    },
    "crypto-wallets-for-travelers-hot-vs-cold": {
        "documentId": "a7mqwqjzaos9dk11lxaw1gmr",
        "excerpt": (
            "Keep $200 to $500 of crypto in a hot wallet for daily spend and park the rest in "
            "a $69 to $219 hardware wallet."
        ),
        "metaDescription": None,  # migration template -> TEMPLATE_META_REPLACEMENTS
        "sources": [
            ("MetaMask — official site", "https://metamask.io/"),
            ("Ledger — hardware wallets", "https://www.ledger.com/"),
            ("Ledger Academy — self-custody guides", "https://www.ledger.com/academy"),
            ("Trezor — hardware wallets", "https://trezor.io/"),
            ("KeepKey — hardware wallets", "https://keepkey.com/"),
            ("Exodus — software wallet", "https://www.exodus.com/"),
            ("Edge — self-custody wallet", "https://edge.app/"),
            ("FTC — What To Know About Cryptocurrency and Scams", "https://consumer.ftc.gov/articles/what-know-about-cryptocurrency-and-scams"),
            ("FBI Internet Crime Complaint Center (IC3)", "https://www.ic3.gov/"),
        ],
    },
    "best-coworking-spaces-for-digital-nomads": {
        "documentId": "pzkbhx7aei5fahr7vvvubyvs",
        "excerpt": (
            "From Hubud in Ubud to Rebel Base in Cape Town: what ten top coworking spaces cost "
            "per month, and how to pick one that fits your workflow."
        ),
        "metaDescription": None,  # carries the migration template -> replaced below
        "sources": [
            ("Hubud — coworking space in Ubud, Bali", "https://hubud.org/"),
            ("Impact Hub — global coworking network", "https://impacthub.net/"),
            ("Outsite — coliving and coworking for remote workers", "https://www.outsite.co/"),
        ],
    },
    "14-travel-hacks-that-ll-save-you-money": {
        "documentId": "f7kvh6fupdv4wob9svido1vm",
        "excerpt": (
            "Weekly Airbnb discounts, shoulder-season flights and a no-foreign-transaction-fee "
            "card can cut a trip's cost. Fourteen hacks that save real money."
        ),
        "metaDescription": None,  # migration template -> TEMPLATE_META_REPLACEMENTS
        "sources": [
            ("Airbnb Help — Weekly and monthly discounts for home stays", "https://www.airbnb.com/help/article/1233/how-do-i-set-custom-weekly-or-monthly-pricing"),
            ("GuruWalk — free walking tours worldwide", "https://www.guruwalk.com/"),
            ("Delta Air Lines — checked baggage overview", "https://www.delta.com/us/en/baggage/overview"),
            ("Apple Support — using eSIM with your iPhone", "https://support.apple.com/en-us/118669"),
            ("Google Flights — fare tracking", "https://www.google.com/travel/flights"),
            ("Hopper — fare predictions", "https://www.hopper.com/"),
        ],
    },
    "how-to-live-in-thailand-as-a-digital-nomad": {
        "documentId": "xy3ggmhszcxyadw2qa14oqse",
        "excerpt": (
            "Thailand's LTR visa allows a ten-year stay with a flat 17% tax on foreign income, "
            "and Chiang Mai runs about US$550 a month excluding rent."
        ),
        "metaDescription": None,  # migration template -> TEMPLATE_META_REPLACEMENTS
        "sources": [
            ("Thailand Board of Investment — LTR Visa (official)", "https://ltr.boi.go.th/"),
            ("Numbeo — Cost of Living in Chiang Mai", "https://www.numbeo.com/cost-of-living/in/Chiang-Mai"),
            ("Speedtest Global Index — Thailand", "https://www.speedtest.net/global-index/thailand"),
            ("Wise — multi-currency accounts", "https://wise.com/"),
            ("Bumrungrad International Hospital, Bangkok", "https://www.bumrungrad.com/"),
            ("The Hive Thonglor — coworking, Bangkok", "https://thehive.co.th/"),
        ],
    },
}

# metaDescriptions written in place of the migration template, per slug. The
# Strapi `excerpt`/`metaDescription` fields cap at 160 characters (schema
# validation, hit live on 2026-09-25), which also satisfies the content-invariants
# monitor's 120-170c SERP budget.
TEMPLATE_META_REPLACEMENTS = {
    "best-vpn-for-digital-nomads": (
        "Work from any café without exposing your logins: what to check in a VPN, how "
        "ExpressVPN, NordVPN and Surfshark compare, and why free VPNs cost more."
    ),
    "essential-apps-for-digital-nomads": (
        "Ten apps that earn their place on a nomad's phone: VPNs for public Wi-Fi, offline "
        "maps, multi-currency accounts, project tools and eSIM data plans."
    ),
    "crypto-wallets-for-travelers-hot-vs-cold": (
        "Keep $200 to $500 in a hot wallet for daily spend and the rest in a $69 to $219 "
        "hardware wallet. Where MetaMask, Ledger and Trezor fit."
    ),
    "best-coworking-spaces-for-digital-nomads": (
        "Ten coworking spaces nomads actually use, from Hubud in Ubud to Rebel Base in Cape "
        "Town: desk rates, day passes and how to pick the right one."
    ),
    "cost-of-living-in-bali-for-digital-nomads": (
        "Live in Bali for as little as US$1,200 a month: rent from US$250, groceries "
        "and transport around US$600, plus coworking, banking and visa costs explained."
    ),
    "14-travel-hacks-that-ll-save-you-money": (
        "Fourteen travel hacks with the numbers behind them: weekly Airbnb discounts, "
        "shoulder-season pricing, no-foreign-transaction-fee cards and eSIM data."
    ),
    "how-to-live-in-thailand-as-a-digital-nomad": (
        "Ten tips for basing in Thailand: the LTR visa's ten-year stay and flat 17% tax, "
        "Chiang Mai costs near US$550 a month excluding rent, and fast fiber."
    ),
}


def network_fetch(url: str):
    """Real HTTP fetch for `citation_is_real`: (status, body, final_url)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(4096).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception:  # noqa: BLE001 — unreachable is a dropped citation, not a crash
        return 0, "", url


def real_citation_count(body: str) -> int:
    from invariants import citation_is_real

    return sum(1 for u in body_citation_urls(body) if citation_is_real(u, network_fetch))


# The Strapi articles schema caps these two fields at 160 characters; a longer
# value is rejected with a 400 ValidationError (hit live on 2026-09-25), so the
# repair refuses to write instead of letting the API reject the row mid-run.
FIELD_MAX = 160


def text_warnings(excerpt: str | None, meta: str | None) -> list[str]:
    """Card/SERP rules the content-invariants monitor enforces on published rows.

    Not the write gate (that only wants non-empty fields) — but a row repaired to
    be publishable should also survive the monitor that judges it once live.
    """
    out: list[str] = []
    if excerpt:
        if len(excerpt) > FIELD_MAX:
            out.append(f"excerpt {len(excerpt)}c > {FIELD_MAX}c schema cap")
        if not excerpt.rstrip().endswith((".", "!", "?", "…")):
            out.append("excerpt does not end a sentence")
    if meta:
        if not (120 <= len(meta) <= FIELD_MAX):
            out.append(f"metaDescription {len(meta)}c outside 120-{FIELD_MAX}")
        if not meta.rstrip().endswith((".", "!", "?", ")")):
            out.append("metaDescription does not end a sentence")
    return out


def plan_row(client: StrapiClient, slug: str, spec: dict) -> dict:
    doc_id = spec["documentId"]
    row = client._request("GET", f"/api/articles/{doc_id}", params={"status": "draft"}).get("data") or {}
    fields: dict = {}
    notes: list[str] = []

    if spec.get("excerpt") and not str(row.get("excerpt") or "").strip():
        fields["excerpt"] = spec["excerpt"]
        notes.append("excerpt")

    meta = str(row.get("metaDescription") or "")
    replacement = TEMPLATE_META_REPLACEMENTS.get(slug)
    if replacement and TEMPLATE_RE.search(meta) and replacement.strip() != meta.strip():
        fields["metaDescription"] = replacement
        notes.append("metaDescription (de-templated)")

    body = row.get("bodyMarkdown") or ""
    before = real_citation_count(body)
    if spec.get("sources") and before < 2:
        facts = [{"source_url": u, "source_title": t} for t, u in spec["sources"]]
        new_body = ensure_body_citations(body, facts, fetch=network_fetch)
        if new_body != body:
            fields["bodyMarkdown"] = new_body
            notes.append(f"bodyMarkdown (citations {before} -> {real_citation_count(new_body)})")

    warnings = text_warnings(fields.get("excerpt"), fields.get("metaDescription"))
    if warnings:
        raise ValueError(f"{slug}: refusing to write — {'; '.join(warnings)}")

    return {
        "slug": slug,
        "documentId": doc_id,
        "title": row.get("title"),
        "publishedAt": row.get("publishedAt"),
        "status": row.get("status"),
        "confidence": row.get("confidence"),
        "real_citations_before": before,
        "errors_before": article_invariant_errors(row, fetch=network_fetch),
        "fields": sorted(fields),
        "notes": notes,
        "text_warnings": warnings,
        "_fields": fields,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the repairs (default: dry run)")
    ap.add_argument("--report", help="write a JSON report to this path")
    args = ap.parse_args()

    cfg = load_config()
    client = StrapiClient(cfg)
    report = {"applied": args.apply, "rows": []}

    for slug, spec in REPAIRS.items():
        plan = plan_row(client, slug, spec)
        fields = plan.pop("_fields")

        if args.apply and fields:
            client.update_article(plan["documentId"], fields, status="draft")
            after = client._request(
                "GET", f"/api/articles/{plan['documentId']}", params={"status": "draft"}
            ).get("data") or {}
            plan["written"] = True
            plan["errors_after"] = article_invariant_errors(after, fetch=network_fetch)
            plan["real_citations_after"] = real_citation_count(after.get("bodyMarkdown") or "")
            plan["excerpt_after"] = (after.get("excerpt") or "")[:80]
        else:
            plan["written"] = False

        mark = "OK " if not plan.get("errors_before") else "FAIL"
        print(f"[{mark}] {slug}")
        print(f"       conf={plan['confidence']} pubAt={plan['publishedAt']} citations_before={plan['real_citations_before']}")
        print(f"       errors_before={plan['errors_before']}")
        if plan["notes"]:
            print(f"       plan: {', '.join(plan['notes'])}")
        else:
            print("       plan: nothing to write")
        if plan["text_warnings"]:
            print(f"       WARN: {'; '.join(plan['text_warnings'])}")
        if args.apply:
            print(f"       written={plan['written']} citations_after={plan.get('real_citations_after')}")
            print(f"       errors_after={plan.get('errors_after')}")
        report["rows"].append(plan)

    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nreport -> {args.report}")

    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
