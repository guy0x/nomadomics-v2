"""Strapi REST client for the engine — talks to the local Strapi instance using
the engine token from .env. No secrets logged. Handles Draft & Publish documents
(documentId-based API in Strapi v5)."""

from __future__ import annotations

import json
import urllib.parse
from typing import Optional

from config import Config


class StrapiError(Exception):
    pass


class StrapiClient:
    def __init__(self, config: Config, *, http_client=None):
        self.cfg = config
        self.base = config.strapi_url
        self.token = config.strapi_engine_token
        self._client = http_client or self._make_client()

    def _make_client(self):
        import httpx

        return httpx.Client(timeout=30, headers=self._headers())

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, body=None, params=None):
        import httpx

        try:
            resp = self._client.request(
                method, self.base + path, json=body, params=params
            )
            if resp.status_code >= 400:
                raise StrapiError(f"Strapi {method} {path} -> {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        except httpx.RequestError as e:
            raise StrapiError(f"Strapi request failed for {path}: {e}") from e

    # ---- Topics ---------------------------------------------------------
    def list_pending_topics(self, limit: int = 5) -> list[dict]:
        """Fetch topics with status=pending, newest-first, up to `limit`."""
        data = self._request(
            "GET",
            "/api/topics",
            params={
                "filters[status][$eq]": "pending",
                "sort": "createdAt:asc",
                "pagination[pageSize]": limit,
            },
        )
        return data.get("data", [])

    def list_inflight_topics(
        self,
        statuses: tuple = ("researching", "drafting"),
        *,
        updated_before: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Fetch topics sitting in an in-flight status, oldest-updated first.

        Used by the stale-topic reclaim (pipeline_cli.reclaim_stale_topics) to
        find runs that died mid-topic: `list_pending_topics` can never see those
        rows again. `updated_before` (ISO-8601) adds a server-side
        `updatedAt $lt` cutoff; the caller re-checks the age in Python.
        """
        params: dict = {
            "sort": "updatedAt:asc",
            "pagination[pageSize]": limit,
        }
        for i, status in enumerate(statuses):
            params[f"filters[status][$in][{i}]"] = status
        if updated_before:
            params["filters[updatedAt][$lt]"] = updated_before
        data = self._request("GET", "/api/topics", params=params)
        return data.get("data", [])

    def get_topic_by_slug(self, slug: str) -> Optional[dict]:
        data = self._request(
            "GET",
            "/api/topics",
            params={"filters[slug][$eq]": slug, "pagination[pageSize]": 1},
        )
        rows = data.get("data", [])
        return rows[0] if rows else None

    def update_topic(self, document_id: str, fields: dict) -> dict:
        return self._request("PUT", f"/api/topics/{document_id}", {"data": fields})

    # ---- Articles -------------------------------------------------------
    def create_article(self, fields: dict) -> dict:
        return self._request("POST", "/api/articles", {"data": fields})

    # Which draft&publish layer a PUT writes to. See update_article().
    _ARTICLE_WRITE_STATUSES = (None, "draft", "published")

    def update_article(
        self, document_id: str, fields: dict, *, status: Optional[str] = "draft"
    ) -> dict:
        """PUT an article update, explicit about WHICH layer it lands on.

        Strapi v5 (draftAndPublish: true, verified on ^5.49/5.50) treats a PUT
        with no `?status=` as a write-through to the PUBLISHED layer, re-stamping
        `publishedAt` and serving the new body live within the frontend's ISR
        window. That is the 2026-09-22 silent-republish incident (kanban
        t_60ad2c8e): a code path meant to "edit a draft" shipped the edit.

        `status` picks the layer:
          - ``"draft"`` (DEFAULT, fail-safe) -> ``?status=draft``, writes the
            draft layer only; the published layer stays byte-identical.
          - ``"published"`` -> ``?status=published``. This is a PUBLISH. Only
            the publish step may pass it.

        Passing ``None`` omits the query param and therefore writes through to
        the published layer — do not use it to edit a draft.

        An explicit ``publishedAt`` in `fields` is NOT reliable: on v5 the
        document service owns that column and ignores the payload value (the
        observed 07:32 write kept the service-stamped time), so a timestamp can
        never be restored by sending one. Set real publish state only via
        ``status="published"``.
        """
        if status not in self._ARTICLE_WRITE_STATUSES:
            raise ValueError(
                f"update_article: status must be one of "
                f"{self._ARTICLE_WRITE_STATUSES!r}, got {status!r}"
            )
        params = {"status": status} if status else None
        return self._request(
            "PUT", f"/api/articles/{document_id}", {"data": fields}, params=params
        )

    # Which draft&publish layer a READ lands on. Strapi v5 serves the PUBLISHED
    # layer unless `?status=draft` is passed; since the 2026-09-22 write-layer
    # fix every lane write lands on the WORKING layer, so a read that omits the
    # param shows stale published-layer mirrors of the articles instead of the
    # articles themselves (verified live 2026-09-25: published-layer `in_review`
    # = 1 row vs 40 draft-layer rows — `engine.cli drafts` printed 3 rows and
    # hid the whole backlog). See update_article() for the write side.
    ARTICLE_DRAFT_LAYER = "draft"
    # This instance returns duplicate rows per document (one per write pass,
    # differing only in id/updatedAt), so a limit-sized page wastes half its
    # budget on duplicates — ask for 2x and dedupe.
    _DRAFT_QUERY_PAGE_MULTIPLIER = 2

    def list_published_titles(self, limit: int = 200) -> list[dict]:
        """Published articles as {slug, title} pairs — the internal-link corpus.

        Used by the write path's internal-link backstop. Returns an empty list
        on any failure: a missing corpus must degrade to "no links added", never
        to a crash on an otherwise publishable article.
        """
        try:
            q = urllib.parse.urlencode({
                "filters[status][$eq]": "published",
                "sort": "publishedAt:desc",
                "pagination[pageSize]": str(limit),
            })
            rows = self._request("GET", "/api/articles?" + q).get("data", [])
            return [{"slug": r.get("slug"), "title": r.get("title")}
                    for r in rows if r.get("slug")]
        except Exception:  # noqa: BLE001 — no corpus is not a write failure
            return []

    def list_drafts(self, limit: int = 20) -> list[dict]:
        """Working-layer articles awaiting review, one row per document.

        Reads `?status=draft` (see ARTICLE_DRAFT_LAYER) for app status
        draft/in_review, reduces duplicate rows to the freshest copy of each
        documentId, and returns the newest `limit` documents.
        """
        rows = self._request(
            "GET",
            "/api/articles",
            params={
                "status": self.ARTICLE_DRAFT_LAYER,
                "filters[status][$in][0]": "draft",
                "filters[status][$in][1]": "in_review",
                "sort": "createdAt:desc",
                "pagination[pageSize]": limit * self._DRAFT_QUERY_PAGE_MULTIPLIER,
            },
        ).get("data", [])

        best: dict[str, dict] = {}
        for row in rows:
            doc_id = str(row.get("documentId") or "")
            if not doc_id:
                continue
            seen = best.get(doc_id)
            if seen is None or str(row.get("updatedAt") or "") > str(
                seen.get("updatedAt") or ""
            ):
                best[doc_id] = row
        newest = sorted(
            best.values(), key=lambda r: str(r.get("createdAt") or ""), reverse=True
        )
        return newest[:limit]

    def count_published(self) -> int:
        """Number of published articles (proxy for human-reviewed articles —
        feeds the trust-ladder `articles_reviewed` count)."""
        data = self._request(
            "GET",
            "/api/articles",
            params={
                "filters[status][$eq]": "published",
                "pagination[pageSize]": 1,
            },
        )
        return int((data.get("meta") or {}).get("pagination", {}).get("total", 0))

    # ---- Authors --------------------------------------------------------
    def list_authors(self) -> list[dict]:
        """Authors with their article counts, for even byline distribution.

        `populate[articles][fields][0]=slug` keeps the payload small (one slug per
        article) while still giving an exact count per author.
        """
        data = self._request(
            "GET",
            "/api/authors",
            params={
                "fields[0]": "name",
                "fields[1]": "slug",
                "populate[articles][fields][0]": "slug",
                "pagination[pageSize]": 100,
                "sort": "slug:asc",
            },
        )
        rows = data.get("data", [])
        return [
            {
                "documentId": r.get("documentId"),
                "name": r.get("name"),
                "slug": r.get("slug"),
                "articles": len(r.get("articles") or []),
            }
            for r in rows
        ]

    def close(self):
        import httpx

        if isinstance(self._client, httpx.Client):
            self._client.close()
