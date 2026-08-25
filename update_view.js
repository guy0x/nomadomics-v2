const fs = require('fs');
const { Client } = require('pg');

const config = {
  "settings": {
    "bulkable": true,
    "filterable": true,
    "searchable": true,
    "pageSize": 10,
    "relationOpenMode": "modal",
    "mainField": "title",
    "defaultSortBy": "title",
    "defaultSortOrder": "ASC"
  },
  "metadatas": {
    "id": {"edit": {}, "list": {"label": "id", "searchable": true, "sortable": true}},
    "title": {"edit": {"label": "Title", "description": "Article headline", "placeholder": "Enter article headline...", "visible": true, "editable": true}, "list": {"label": "Title", "searchable": true, "sortable": true}},
    "slug": {"edit": {"label": "URL Slug", "description": "Auto-generated from title", "placeholder": "", "visible": true, "editable": true}, "list": {"label": "Slug", "searchable": true, "sortable": true}},
    "excerpt": {"edit": {"label": "Excerpt / Summary", "description": "Short article teaser for social & listings", "placeholder": "Write a compelling 1-2 sentence hook...", "visible": true, "editable": true}, "list": {"label": "Excerpt", "searchable": true, "sortable": true}},
    "bodyMarkdown": {"edit": {"label": "Article Body (Markdown Canvas)", "description": "Full-length long-form article content in GitHub-flavored Markdown", "placeholder": "Write or edit the article body here in Markdown...", "visible": true, "editable": true}, "list": {"label": "Body", "searchable": true, "sortable": true}},
    "targetKeywords": {"edit": {"label": "Target Keywords", "description": "Comma-separated target SEO keywords", "placeholder": "e.g. digital nomad, travel hacks", "visible": true, "editable": true}, "list": {"label": "Target Keywords", "searchable": false, "sortable": false}},
    "metaTitle": {"edit": {"label": "Meta Title (SERP)", "description": "Max 60 chars title tag for Google", "placeholder": "SERP title tag...", "visible": true, "editable": true}, "list": {"label": "Meta Title", "searchable": true, "sortable": true}},
    "metaDescription": {"edit": {"label": "Meta Description (SERP)", "description": "Max 160 chars description snippet for Google", "placeholder": "SERP description...", "visible": true, "editable": true}, "list": {"label": "Meta Description", "searchable": true, "sortable": true}},
    "focusKeyword": {"edit": {"label": "Primary Focus Keyword", "description": "The main keyword targeted by the SEO analyzer", "placeholder": "Primary keyword...", "visible": true, "editable": true}, "list": {"label": "Focus Keyword", "searchable": true, "sortable": true}},
    "status": {"edit": {"label": "Publishing Status", "description": "Draft / In Review / Published / Rejected", "placeholder": "", "visible": true, "editable": true}, "list": {"label": "Status", "searchable": true, "sortable": true}},
    "scheduledFor": {"edit": {"label": "Scheduled Publish Date", "description": "Optional future publication date/time", "placeholder": "", "visible": true, "editable": true}, "list": {"label": "Scheduled For", "searchable": true, "sortable": true}},
    "publishedAt": {"edit": {"label": "Published At", "description": "", "placeholder": "", "visible": false, "editable": true}, "list": {"label": "Published At", "searchable": true, "sortable": true}},
    "seoScore": {"edit": {"label": "SEO Score", "description": "", "placeholder": "", "visible": false, "editable": true}, "list": {"label": "SEO Score", "searchable": true, "sortable": true}},
    "readabilityScore": {"edit": {"label": "Readability Score", "description": "", "placeholder": "", "visible": false, "editable": true}, "list": {"label": "Readability Score", "searchable": true, "sortable": true}},
    "confidence": {"edit": {"label": "Confidence Rating", "description": "", "placeholder": "", "visible": false, "editable": true}, "list": {"label": "Confidence", "searchable": true, "sortable": true}},
    "wpSourceUrl": {"edit": {"label": "Legacy WP Source URL", "description": "", "placeholder": "", "visible": false, "editable": true}, "list": {"label": "WP Source", "searchable": true, "sortable": true}},
    "lastError": {"edit": {"label": "Engine Error Log", "description": "", "placeholder": "", "visible": false, "editable": true}, "list": {"label": "Last Error", "searchable": true, "sortable": true}},
    "createdAt": {"edit": {"label": "Created At", "description": "", "placeholder": "", "visible": false, "editable": true}, "list": {"label": "Created At", "searchable": true, "sortable": true}},
    "updatedAt": {"edit": {"label": "Updated At", "description": "", "placeholder": "", "visible": false, "editable": true}, "list": {"label": "Updated At", "searchable": true, "sortable": true}},
    "createdBy": {"edit": {"label": "Created By", "description": "", "placeholder": "", "visible": false, "editable": true, "mainField": "firstname"}, "list": {"label": "Created By", "searchable": true, "sortable": true}},
    "updatedBy": {"edit": {"label": "Updated By", "description": "", "placeholder": "", "visible": false, "editable": true, "mainField": "firstname"}, "list": {"label": "Updated By", "searchable": true, "sortable": true}},
    "documentId": {"edit": {}, "list": {"label": "documentId", "searchable": true, "sortable": true}}
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
};

async function main() {
  const client = new Client({
    host: '127.0.0.1',
    port: 5432,
    database: 'nomadomics',
    user: 'nomadomics',
    password: 'nomadomics_dev_password',
  });
  await client.connect();
  const res = await client.query(
    'UPDATE strapi_core_store_settings SET value = $1 WHERE key = $2',
    [JSON.stringify(config), 'plugin_content_manager_configuration_content_types::api::article.article']
  );
  console.log(`Successfully updated ${res.rowCount} row(s).`);
  await client.end();
}

main().catch(console.error);
