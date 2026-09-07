"""Hard-rule tests: no years in article slugs (Guy, 2026-09-07)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline_cli import _yearless_slug


@pytest.mark.parametrize(
    "raw,expected",
    [
        # trailing-year variants
        ("top-geoarbitrage-hotspots-for-2025", "top-geoarbitrage-hotspots"),
        ("best-countries-for-remote-workers-in-2025", "best-countries-for-remote-workers"),
        ("14-travel-hacks-that-ll-save-you-money-in-2025", "14-travel-hacks-that-ll-save-you-money"),
        ("best-travel-credit-cards-for-2025", "best-travel-credit-cards"),
        ("7-best-flight-booking-apps-in-2025", "7-best-flight-booking-apps"),
        # leading-year variant
        ("2025-europe-travel-rules", "europe-travel-rules"),
        # bare-year
        ("is-crypto-worth-it-2026", "is-crypto-worth-it"),
        # no year — unchanged
        ("budget-travel-accommodation-hacks", "budget-travel-accommodation-hacks"),
        ("best-atms-in-spain", "best-atms-in-spain"),
        ("travel-hacks-to-save-money", "travel-hacks-to-save-money"),
        # double-hyphen cleanup
        ("geoarbitrage--2025--guide", "geoarbitrage-guide"),
        # idempotent
        ("top-geoarbitrage-hotspots", "top-geoarbitrage-hotspots"),
    ],
)
def test_yearless_slug(raw, expected):
    assert _yearless_slug(raw) == expected


def test_yearless_slug_idempotent():
    once = _yearless_slug("best-vpns-for-traveling-in-2026")
    assert _yearless_slug(once) == once


def test_yearless_slug_never_contains_year():
    for raw in (
        "best-vpns-for-2025",
        "2026-tax-guide",
        "guide-to-2027-travel",
    ):
        import re

        assert not re.search(r"20\d{2}", _yearless_slug(raw))
