"""One publish ledger for both Nomadomics lanes.

The draft lane and the daily publish lane append here. Readers union this
file with each lane's historical journal so a slug published by either lane
is seen by the other. Append-only. This module never publishes.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

LEDGER = Path(__file__).resolve().parent / "state" / "publish-ledger.jsonl"


def record(entry: dict, path: Path | None = None) -> None:
    dest = Path(path) if path else LEDGER
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def published_slugs(paths: list[Path], *, today_only: bool = False) -> set[str]:
    out: set[str] = set()
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    for path in paths:
        if not path or not Path(path).exists():
            continue
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") not in ("published", "article_created"):
                continue
            if event.get("event") == "article_created" and not event.get("published"):
                continue
            slug = event.get("slug")
            if not slug:
                continue
            if today_only and not str(event.get("ts") or "").startswith(today):
                continue
            out.add(str(slug))
    return out
