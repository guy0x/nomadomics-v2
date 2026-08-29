"""Editor module — QA/polish pass between draft and SEO scoring.

Runs on the edit model (Gemini flash primary). The editor does NOT generate new
content from scratch; it receives the writer's draft and tightens it against the
voice anchor and brand system before the deterministic SEO/confidence scorer sees
it, so the score reflects the *edited* article.

Returns EditedDraft with the same duck-typed fields the SEO scorer consumes
(markdown, word_count, used_facts) plus a short edit_report.
"""
