#!/usr/bin/env python3
"""convert_wp.py — Convert WordPress REST API JSON exports to individual .md files.

Input:  reference/wp-articles/raw-page-N.json
Output: reference/wp-articles/<slug>.md with YAML frontmatter + stripped body
"""
import json, os, re, html
from pathlib import Path

SRC = Path("reference/wp-articles")
OUT = SRC

def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[/?[\w_]+[^\]]*\]", "", text)  # strip shortcodes
    return html.unescape(text).strip()

if __name__ == "__main__":
    pages = sorted(SRC.glob("raw-page-*.json"))
    print(f"Found {len(pages)} raw pages")
    total = 0
    for json_file in pages:
        try:
            posts = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"  SKIP {json_file.name}: invalid JSON ({e})")
            continue
        if not isinstance(posts, list) or len(posts) == 0:
            print(f"  SKIP {json_file.name}: empty/non-array")
            continue
        for post in posts:
            slug = post.get("slug") or f"post-{post.get('id', total)}"
            title_html = post.get("title", {}).get("rendered", "")
            title = strip_html(title_html)
            content_html = post.get("content", {}).get("rendered", "")
            content_md = strip_html(content_html)
            excerpt_html = post.get("excerpt", {}).get("rendered", "")
            excerpt = strip_html(excerpt_html)
            date = post.get("date", "")
            link = post.get("link", "")
            pid = post.get("id", 0)

            fm_lines = [
                "---",
                f"title: {title}",
                f"slug: {slug}",
                f"date: {date}",
                f"wp_url: {link}",
                f"wp_id: {pid}",
                f"excerpt: {excerpt}",
                "---",
                "",
            ]
            body = "\n".join(fm_lines) + content_md + "\n"
            (OUT / f"{slug}.md").write_text(body, encoding="utf-8")
            total += 1
    md_count = len(list(OUT.glob("*.md")))
    print(f"Exported {total} posts this run. Total .md files in {OUT}: {md_count}")