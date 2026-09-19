"""Strapi REST client for the engine — talks to the local Strapi instance using
the engine token from .env. No secrets logged. Handles Draft & Publish documents
(documentId-based API in Strapi v5)."""

from __future__ import annotations

import json
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

    def update_article(self, document_id: str, fields: dict) -> dict:
        return self._request("PUT", f"/api/articles/{document_id}", {"data": fields})

    def list_drafts(self) -> list[dict]:
        data = self._request(
            "GET",
            "/api/articles",
            params={
                "filters[status][$in][0]": "draft",
                "filters[status][$in][1]": "in_review",
                "sort": "createdAt:desc",
                "pagination[pageSize]": 20,
            },
        )
        return data.get("data", [])

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
