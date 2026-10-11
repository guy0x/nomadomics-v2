import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts_dev" / "backfill_site_key.py"
spec = importlib.util.spec_from_file_location("backfill_site_key", SCRIPT)
backfill = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(backfill)


class FakeClient:
    def __init__(self):
        self.rows = {
            "topics": [
                {"documentId": "topic-1", "title": "one"},
                {"documentId": "topic-1", "title": "one duplicate"},
                {"documentId": "topic-2", "siteKey": "nomadomics"},
            ],
            "articles": [
                {"documentId": "article-1", "attributes": {"title": "one"}},
                {"documentId": "article-2", "siteKey": "nomadomics"},
            ],
        }
        self.calls = []

    def _request(self, method, path, params=None):
        self.calls.append((method, path, params))
        parts = path.split("/")
        collection = parts[2]
        if len(parts) == 4:
            doc_id = parts[3]
            row = next(row for row in self.rows[collection] if row["documentId"] == doc_id)
            return {"data": row}
        return {"data": list(self.rows[collection])}

    def update_topic(self, document_id, fields):
        self.calls.append(("TOPIC_UPDATE", document_id, fields))
        for row in self.rows["topics"]:
            if row["documentId"] == document_id:
                row.update(fields)
        return {"data": {"documentId": document_id, **fields}}

    def update_article(self, document_id, fields, *, status="draft"):
        self.calls.append(("ARTICLE_UPDATE", document_id, fields, status))
        assert status == "draft"
        for row in self.rows["articles"]:
            if row["documentId"] == document_id:
                row.update(fields)
        return {"data": {"documentId": document_id, **fields}}

    def close(self):
        pass


def test_inventory_counts_missing_and_duplicate_document_ids():
    client = FakeClient()
    result = backfill.inventory(client.rows["topics"], "nomadomics")
    assert result["rows"] == 3
    assert result["missing_site_key"] == 2
    assert result["duplicate_document_ids"] == {"topic-1": 2}


def test_apply_updates_missing_once_and_rereads_each_document():
    client = FakeClient()
    inventories = {
        collection: backfill.inventory(client.rows[collection], "nomadomics")
        for collection in backfill.COLLECTIONS
    }
    updated = backfill.apply_missing(client, inventories, "nomadomics")
    assert updated == 2  # duplicate topic document is written once
    updates = [call for call in client.calls if call[0] in {"TOPIC_UPDATE", "ARTICLE_UPDATE"}]
    assert len(updates) == 2
    assert all(call[-1] == "draft" for call in updates if call[0] == "ARTICLE_UPDATE")
    rereads = [call for call in client.calls if call[0] == "GET" and len(call[1].split("/")) == 4]
    assert len(rereads) == 2
    assert all(call[2] == {"status": "draft"} for call in rereads if "articles" in call[1])


def test_apply_requires_exact_site_key_acknowledgement(monkeypatch):
    with pytest.raises(SystemExit):
        backfill.main(["--apply"])
    with pytest.raises(SystemExit):
        backfill.main(["--apply", "--site-key", "other-site"])
