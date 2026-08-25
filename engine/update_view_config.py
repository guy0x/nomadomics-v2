import json
import subprocess

config_backup = {
  "settings": {
    "bulkable": True,
    "filterable": True,
    "searchable": True,
    "pageSize": 10,
    "relationOpenMode": "modal",
    "mainField": "title",
    "defaultSortBy": "title",
    "defaultSortOrder": "ASC"
  },
  "metadatas": {
    "id": {"edit": {}, "list": {"label": "id", "searchable": True, "sortable": True}},
    "title": {"edit": {"label": "Title", "description": "Article headline", "placeholder": "Enter article headline...", "visible": True, "editable": True}, "list": {"label": "Title", "searchable": True, "sortable": True}},
    "slug": {"edit": {"label": "URL Slug", "description": "Auto-generated from title", "placeholder": "", "visible": True, "editable": True}, "list": {"label": "Slug", "searchable": True, "sortable": True}},
    "excerpt": {"edit": {"label": "Excerpt / Summary", "description": "Short article teaser for social & listings", "placeholder": "Write a compelling 1-2 sentence hook...", "visible": True, "editable": True}, "list": {"label": "Excerpt", "searchable": True, "sortable": True}},
    "bodyMarkdown": {"edit": {"label": "Article Body (Markdown Canvas)", "description": "Full-length long-form article content in GitHub-flavored Markdown", "placeholder": "Write or edit the article body here in Markdown...", "visible": True, "editable": True}, "list": {"label": "Body", "searchable": True, "sortable": True}},
    "targetKeywords": {"edit": {"label": "Target Keywords", "description": "Comma-separated target SEO keywords", "placeholder": "e.g. digital nomad, travel hacks", "visible": True, "editable": True}, "list": {"label": "Target Keywords", "searchable": False, "sortable": False}},
    "metaTitle": {"edit": {"label": "Meta Title (SERP)", "description": "Max 60 chars title tag for Google", "placeholder": "SERP title tag...", "visible": True, "editable": True}, "list": {"label": "Meta Title", "searchable": True, "sortable": True}},
    "metaDescription": {"edit": {"label": "Meta Description (SERP)", "description": "Max 160 chars description snippet for Google", "placeholder": "SERP description...", "visible": True, "editable": True}, "list": {"label": "Meta Description", "searchable": True, "sortable": True}},
    "focusKeyword": {"edit": {"label": "Primary Focus Keyword", "description": "The main keyword targeted by the SEO analyzer", "placeholder": "Primary keyword...", "visible": True, "editable": True}, "list": {"label": "Focus Keyword", "searchable": True, "sortable": True}},
    "status": {"edit": {"label": "Publishing Status", "description": "Draft / In Review / Published / Rejected", "placeholder": "", "visible": True, "editable": True}, "list": {"label": "Status", "searchable": True, "sortable": True}},
    "scheduledFor": {"edit": {"label": "Scheduled Publish Date", "description": "Optional future publication date/time", "placeholder": "", "visible": True, "editable": True}, "list": {"label": "Scheduled For", "searchable": True, "sortable": True}},
    "publishedAt": {"edit": {"label": "Published At", "description": "", "placeholder": "", "visible": False, "editable": True}, "list": {"label": "Published At", "searchable": True, "sortable": True}},
    "seoScore": {"edit": {"label": "SEO Score", "description": "", "placeholder": "", "visible": False, "editable": True}, "list": {"label": "SEO Score", "searchable": True, "sortable": True}},
    "readabilityScore": {"edit": {"label": "Readability Score", "description": "", "placeholder": "", "visible": False, "editable": True}, "list": {"label": "Readability Score", "searchable": True, "sortable": True}},
    "confidence": {"edit": {"label": "Confidence Rating", "description": "", "placeholder": "", "visible": False, "editable": True}, "list": {"label": "Confidence", "searchable": True, "sortable": True}},
    "wpSourceUrl": {"edit": {"label": "Legacy WP Source URL", "description": "", "placeholder": "", "visible": False, "editable": True}, "list": {"label": "WP Source", "searchable": True, "sortable": True}},
    "lastError": {"edit": {"label": "Engine Error Log", "description": "", "placeholder": "", "visible": False, "editable": True}, "list": {"label": "Last Error", "searchable": True, "sortable": True}},
    "createdAt": {"edit": {"label": "Created At", "description": "", "placeholder": "", "visible": False, "editable": True}, "list": {"label": "Created At", "searchable": True, "sortable": True}},
    "updatedAt": {"edit": {"label": "Updated At", "description": "", "placeholder": "", "visible": False, "editable": True}, "list": {"label": "Updated At", "searchable": True, "sortable": True}},
    "createdBy": {"edit": {"label": "Created By", "description": "", "placeholder": "", "visible": False, "editable": True, "mainField": "firstname"}, "list": {"label": "Created By", "searchable": True, "sortable": True}},
    "updatedBy": {"edit": {"label": "Updated By", "description": "", "placeholder": "", "visible": False, "editable": True, "mainField": "firstname"}, "list": {"label": "Updated By", "searchable": True, "sortable": True}},
    "documentId": {"edit": {}, "list": {"label": "documentId", "searchable": True, "sortable": True}}
  },
  "layouts": {
    "list": ["id", "title", "status", "focusKeyword", "confidence", "seoScore"],
    "edit": [
      [{"name": "title", "size": 12}],
      [{"name": "bodyMarkdown", "size": 12}],
      [{"name": "excerpt", "size": 12}],
      [{"name": "slug", "size": 6}, {"name": "status", "size": 6}],
      [{"name": "scheduledFor", "size": 6}, {"name": "targetKeywords", "size": 6}],
      [{"name": "focusKeyword", "size": 6}, {"name": "metaTitle", "size": 6}],
      [{"name": "metaDescription", "size": 12}]
    ]
  },
  "uid": "api::article.article"
}

json_str = json.dumps(config_backup)
# Update Postgres
sql = "UPDATE strapi_core_store_settings SET value = %s WHERE key = 'plugin_content_manager_configuration_content_types::api::article.article';"

import psycopg2
conn = psycopg2.connect("dbname=nomadomics user=nomadomics password=nomadomics_dev_password host=127.0.0.1 port=5432")
cur = conn.cursor()
cur.execute(sql, (json_str,))
conn.commit()
print(f"Updated rows: {cur.rowcount}")
cur.close()
conn.close()
