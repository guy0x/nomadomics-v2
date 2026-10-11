import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from site_profile import SiteProfile, load_site_profile  # noqa: E402


VALID = {
    "site_key": "nomadomics",
    "brand_name": "Nomadomics",
    "base_url": "https://www.nomadomics.blog",
    "default_language": "en",
    "categories": ["travel", "gear"],
    "sensitive_categories": ["banking"],
    "prompt_dir": "engine/writer/prompts",
    "affiliate_disclosure_path": "/disclosure",
}


def write_profile(tmp_path: Path, **changes) -> Path:
    data = {**VALID, **changes}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(data))
    return path


def test_valid_profile_load_is_frozen_and_normalizes_sequences(tmp_path):
    profile = load_site_profile(write_profile(tmp_path), expected_key="nomadomics")
    assert isinstance(profile, SiteProfile)
    assert profile.categories == ("travel", "gear")
    assert profile.sensitive_categories == ("banking",)
    with pytest.raises((AttributeError, TypeError)):
        profile.site_key = "other"  # type: ignore[misc]


def test_missing_profile_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_site_profile(tmp_path / "missing.json")


def test_missing_field_raises_value_error_without_reading_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("NOMADOMICS_SITE_KEY", "secret-env-value")
    path = write_profile(tmp_path)
    data = json.loads(path.read_text())
    del data["brand_name"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError) as exc:
        load_site_profile(path)
    assert "secret-env-value" not in str(exc.value)


def test_invalid_site_key_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="invalid format"):
        load_site_profile(write_profile(tmp_path, site_key="Nomadomics!"))


def test_expected_key_mismatch_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="does not match"):
        load_site_profile(write_profile(tmp_path), expected_key="other-site")


def test_production_profile_requires_https(tmp_path):
    with pytest.raises(ValueError, match="HTTPS"):
        load_site_profile(write_profile(tmp_path, base_url="http://example.test"))


def test_malformed_json_raises_value_error(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text("not-json")
    with pytest.raises(ValueError, match="valid JSON"):
        load_site_profile(path)
