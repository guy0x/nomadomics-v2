#!/usr/bin/env python3
"""convert_wp_xml.py — Convert WordPress WXR XML exports to individual .md files.

Input:  WordPress WXR XML export (nomadomics.WordPress.*.content.xml)
Output: reference/wp-articles/<slug>.md with YAML frontmatter + clean body

Usage: python3 scripts/convert_wp_xml.py [--source PATH] [--dest PATH]
"""
import xml.etree.ElementTree as ET
import re
import html
import argparse
from pathlib import Path

def strip_html(text):
    """Remove HTML tags and decode entities."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\[/?[\w_]+[^\]]*\]', '', text)  # strip shortcodes
    text = text.replace('&nbsp;', ' ')
    return html.unescape(text).strip()

def process_content_xml(src_path, dest_path):
    """Convert WordPress WXR content XML to markdown files."""
    tree = ET.parse(src_path)
    root = tree.getroot()
    
    dest_path = Path(dest_path)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    items = root.findall('.//item')
    
    extracted = 0
    skipped = 0
    
    for item in items:
        # Check if it's a post (not page, attachment, etc.)
        post_type = item.find('{http://wordpress.org/export/1.2/}post_type')
        if post_type is None or post_type.text != 'post':
            continue
            
        # Extract fields
        title = item.find('title')
        slug = item.find('{http://wordpress.org/export/1.2/}post_name')
        link = item.find('link')
        post_id = item.find('{http://wordpress.org/export/1.2/}post_id')
        content = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
        excerpt = item.find('{http://wordpress.org/export/1.2/excerpt/}encoded')
        date = item.find('{http://wordpress.org/export/1.2/}post_date')
        categories = item.findall('category')
        
        slug_text = slug.text if slug is not None else ""
        if not slug_text:
            skipped += 1
            continue
            
        # Check if file already exists
        output_file = dest_path / f"{slug_text}.md"
        if output_file.exists():
            print(f"  SKIP (exists): {slug_text}")
            continue
        
        # Build frontmatter
        frontmatter = [
            "---",
            f"title: {strip_html(title.text) if title is not None else ''}",
            f"slug: {slug_text}",
            f"date: {date.text if date is not None else ''}",
            f"wp_url: {link.text if link is not None else ''}",
            f"wp_id: {post_id.text if post_id is not None else ''}",
            f"excerpt: {strip_html(excerpt.text) if excerpt is not None else ''}",
            "---",
            "",
        ]
        
        # Convert content to markdown
        content_html = content.text if content is not None else ""
        content_md = strip_html(content_html)
        
        # Write file
        output_file.write_text("\n".join(frontmatter) + content_md + "\n", encoding="utf-8")
        print(f"  CREATED: {slug_text}")
        extracted += 1
    
    print(f"\nExtracted {extracted} new posts to {dest_path}")
    return extracted

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='reference/wp-articles/*.xml', help='Source XML file')
    parser.add_argument('--dest', default='reference/wp-articles', help='Destination directory')
    args = parser.parse_args()
    
    src = Path(args.source)
    if src.is_dir() or '*' in str(src):
        # Find the most recent content XML
        xml_files = sorted(Path('.').glob('*/nomadomics.WordPress.*.content.xml'))
        if not xml_files:
            xml_files = sorted(Path('.').glob('**/Nomadomics*/*/nomadomics.WordPress.*.content.xml'))
        if xml_files:
            src = xml_files[-1]
            print(f"Using latest: {src}")
        else:
            print("No WordPress XML found")
            exit(1)
    
    process_content_xml(src, args.dest)