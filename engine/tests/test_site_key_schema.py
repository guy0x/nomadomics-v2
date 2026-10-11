import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_site_key_is_optional_with_nomadomics_default():
    for relative in (
        "src/api/topic/content-types/topic/schema.json",
        "src/api/article/content-types/article/schema.json",
    ):
        schema = json.loads((ROOT / relative).read_text())
        field = schema["attributes"]["siteKey"]
        assert field == {"type": "string", "default": "nomadomics"}
        assert "required" not in field
