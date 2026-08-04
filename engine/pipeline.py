#!/usr/bin/env python3
"""Nomadomics MVP pipeline — local Markdown queue (no Strapi yet).

Tiny, dependency-free orchestrator for the content engine MVP.
Strapi/Next.js/Vercel are deferred; drafts live as Markdown under content/drafts/.

Usage:
  python3 engine/pipeline.py next      # show next unprocessed topic
  python3 engine/pipeline.py list      # show all topics + status
  python3 engine/pipeline.py scaffold <slug>   # create drafts/<slug>.md from template
  python3 engine/pipeline.py done <slug>       # move a topic to queue/done.md

The actual writing is done by Hermes (write-nomadomics-draft skill) or a cron
that calls `hermes run-skill`. This script just keeps the queue honest.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
QUEUE = ROOT / "engine" / "queue" / "approved.md"
DONE = ROOT / "engine" / "queue" / "done.md"
DRAFTS = ROOT / "content" / "drafts"


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:80]


def _parse_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    topics = []
    cur = None
    for line in QUEUE.read_text().splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            cur = {"title": m.group(1).strip(), "angle": "", "slug": _slugify(m.group(1))}
            topics.append(cur)
        elif cur is not None and line.strip() and not line.startswith("#"):
            cur["angle"] = line.strip()
    return topics


def _draft_exists(slug: str) -> bool:
    return (DRAFTS / f"{slug}.md").exists()


def cmd_next() -> None:
    for t in _parse_queue():
        if not _draft_exists(t["slug"]):
            print(f"{t['title']}\n  slug: {t['slug']}\n  angle: {t['angle']}")
            return
    print("queue empty — all topics have drafts.")


def cmd_list() -> None:
    for t in _parse_queue():
        mark = "✓ draft" if _draft_exists(t["slug"]) else "• todo"
        print(f"[{mark}] {t['title']}  ({t['slug']})")


def cmd_scaffold(slug: str) -> None:
    DRAFTS.mkdir(parents=True, exist_ok=True)
    t = next((x for x in _parse_queue() if x["slug"] == slug), None)
    title = t["title"] if t else slug.replace("-", " ").title()
    p = DRAFTS / f"{slug}.md"
    if p.exists():
        print(f"exists: {p}")
        return
    p.write_text(
        f"---\ntitle: \"{title}\"\nslug: {slug}\nstatus: draft\naiGenerated: true\n"
        f"excerpt: \"\"\nmetaTitle: \"\"\nmetaDescription: \"\"\n"
        f"primaryKeyword: \"\"\nsecondaryKeywords: []\ndate: \"\"\n---\n\n"
        f"<!-- Draft body goes here. Lead money-first. Voice: snark at institutions, never reader. -->\n"
    )
    print(f"scaffolded: {p}")


def cmd_done(slug: str) -> None:
    DONE.parent.mkdir(parents=True, exist_ok=True)
    if not DONE.exists():
        DONE.write_text("# Done topics\n\n")
    DONE.write_text(DONE.read_text() + f"\n- {slug}\n")
    # strip from approved.md
    if QUEUE.exists():
        lines = [l for l in QUEUE.read_text().splitlines() if slug not in l.lower() or not l.startswith("##")]
        QUEUE.write_text("\n".join(lines) + "\n")
    print(f"marked done: {slug}")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]
    if cmd == "next":
        cmd_next()
    elif cmd == "list":
        cmd_list()
    elif cmd == "scaffold":
        cmd_scaffold(args[1]) if len(args) > 1 else print("need <slug>")
    elif cmd == "done":
        cmd_done(args[1]) if len(args) > 1 else print("need <slug>")
    else:
        print(f"unknown: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
