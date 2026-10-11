"""Validated, non-secret identity settings for a Nomadomics site."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_SITE_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REQUIRED = (
    "site_key",
    "brand_name",
    "base_url",
    "default_language",
    "categories",
    "sensitive_categories",
    "prompt_dir",
    "affiliate_disclosure_path",
)


@dataclass(frozen=True)
class SiteProfile:
    site_key: str
    brand_name: str
    base_url: str
    default_language: str
    categories: tuple[str, ...]
    sensitive_categories: tuple[str, ...]
    prompt_dir: str
    affiliate_disclosure_path: str


def _non_empty_string(data: dict, field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"site profile field {field_name!r} must be a non-empty string")
    return value.strip()


def _string_list(data: dict, field_name: str) -> tuple[str, ...]:
    value = data.get(field_name)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(f"site profile field {field_name!r} must be a non-empty list of strings")
    return tuple(item.strip() for item in value)


def load_site_profile(path: Path, expected_key: str | None = None) -> SiteProfile:
    """Load and validate a site profile without consulting process environment.

    Profiles under ``config/sites`` (and the built-in Nomadomics profile) are
    production profiles and must use HTTPS. The explicit key check lets callers
    fail closed before using a profile intended for another site.
    """
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("site profile is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("site profile root must be an object")
    missing = [name for name in _REQUIRED if name not in raw]
    if missing:
        raise ValueError("site profile is missing required fields")

    site_key = _non_empty_string(raw, "site_key")
    if not _SITE_KEY.fullmatch(site_key):
        raise ValueError("site profile site_key has invalid format")
    if expected_key is not None and site_key != expected_key:
        raise ValueError("site profile site_key does not match expected key")

    brand_name = _non_empty_string(raw, "brand_name")
    base_url = _non_empty_string(raw, "base_url").rstrip("/")
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("site profile base_url must be an absolute HTTP(S) URL")
    production_profile = site_key == "nomadomics" or path.resolve().parent.name == "sites"
    if production_profile and parsed_url.scheme != "https":
        raise ValueError("production site profile base_url must use HTTPS")

    return SiteProfile(
        site_key=site_key,
        brand_name=brand_name,
        base_url=base_url,
        default_language=_non_empty_string(raw, "default_language"),
        categories=_string_list(raw, "categories"),
        sensitive_categories=_string_list(raw, "sensitive_categories"),
        prompt_dir=_non_empty_string(raw, "prompt_dir"),
        affiliate_disclosure_path=_non_empty_string(raw, "affiliate_disclosure_path"),
    )
