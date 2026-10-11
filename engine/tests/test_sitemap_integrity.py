"""Tests for the sitemap-vs-published integrity invariant (QA F-01, 2026-10-08).

The production sitemap advertised ``cost-of-living-cape-town-nomads`` while
live Strapi returned that article as ``in_review`` and the production URL
returned 404 — a stale Vercel ISR render (``age: 41655``, ``x-vercel-cache:
HIT``). These tests pin the invariant's required behaviours (acceptance
criteria 1-4):

  - failing case:   sitemap-only slug and/or emitted article URL not HTTP 200
  - clean case:     sitemap and published sets reconcile, all URLs 200
  - unavailable deps: sitemap/CMS unreachable, non-200, or EMPTY is a
                      dependency error — never a pass and never a fail
  - URL handling:   both absolute and relative <loc> values parse to the same
                    slug set; only same-origin single-segment paths count

and the named-set output contract (criterion 2).

Run:  cd ~/nomadomics-v2/engine && env -u PYTHONPATH ../.venv/bin/python -m pytest \
          tests/test_sitemap_integrity.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sitemap_integrity import (  # noqa: E402
    DEFAULT_SITEMAP_URL,
    DependencyError,
    analyze,
    fetch_published_slugs,
    fetch_sitemap_xml,
    format_report,
    parse_sitemap,
    run_integrity,
    run_sitemap_check,
)

SITE = "https://www.nomadomics.blog"
STALE_SLUG = "cost-of-living-cape-town-nomads"
REAL_SLUG = "cost-of-living-berlin-digital-nomads"


def _urlset(*locs: str) -> str:
    """Minimal urlset XML with one <url><loc> entry per given loc."""
    urls = "".join(f"<url><loc>{l}</loc></url>" for l in locs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )


def _status_map(statuses: dict):
    """A url_status callable backed by a URL->status dict, default 200."""
    return lambda url: statuses.get(url, 200)


class FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class FakeHttp:
    """httpx.Client double: serves the sitemap URL, then per-URL statuses."""

    def __init__(
        self,
        sitemap_text: str = "",
        sitemap_status: int = 200,
        url_status: dict | None = None,
        *,
        connect_error: bool = False,
        close_calls: list | None = None,
    ):
        self.sitemap_text = sitemap_text
        self.sitemap_status = sitemap_status
        self.url_status = url_status or {}
        self.connect_error = connect_error
        self.closed = close_calls

    def get(self, url, **kwargs):
        if self.connect_error:
            raise httpx.ConnectError("connection refused")
        if url == DEFAULT_SITEMAP_URL:
            return FakeResp(self.sitemap_status, self.sitemap_text)
        return FakeResp(self.url_status.get(url, 200))

    def close(self):
        if self.closed is not None:
            self.closed.append(True)


class FakeStrapi:
    """StrapiClient double: only the published-articles read is needed."""

    def __init__(self, data: dict | None = None, *, raises: Exception | None = None):
        self.data = data
        self.raises = raises

    def _request(self, method, path, body=None, params=None):
        if self.raises is not None:
            raise self.raises
        return self.data

    def close(self):
        pass


# --- Acceptance criterion 1: the reproduced failing case -----------------------

def test_detects_the_reproduced_stale_sitemap_case():
    """The exact 2026-10-08 defect: cape-town in the sitemap, not in the live
    published set, and its emitted URL returns 404."""
    xml = _urlset(
        f"{SITE}/about",
        f"{SITE}/{REAL_SLUG}",
        f"{SITE}/{STALE_SLUG}",
        f"{SITE}/category/travel",
    )
    report = analyze(
        xml,
        {REAL_SLUG},
        url_status=_status_map({f"{SITE}/{STALE_SLUG}": 404}),
    )

    assert report.sitemap_only == {STALE_SLUG}
    assert report.published_only == set()
    assert report.non200 == [(f"{SITE}/{STALE_SLUG}", 404)]
    assert report.failed is True
    assert report.verdict == "FAIL"


def test_non200_emitted_article_url_alone_fails_the_check():
    """A slug that IS in the published set but whose URL 404s is still a
    failure — criterion 1 is sitemap-only slug AND/OR URL not HTTP 200."""
    xml = _urlset(f"{SITE}/{REAL_SLUG}")
    report = analyze(
        xml,
        {REAL_SLUG},
        url_status=_status_map({f"{SITE}/{REAL_SLUG}": 404}),
    )

    assert report.sitemap_only == set()
    assert report.non200 == [(f"{SITE}/{REAL_SLUG}", 404)]
    assert report.failed is True


def test_sitemap_only_slug_alone_fails_the_check():
    """A sitemap-only slug with a reachable 200 URL is still a failure (the
    sitemap advertises a URL outside the live published set)."""
    xml = _urlset(f"{SITE}/{REAL_SLUG}", f"{SITE}/{STALE_SLUG}")
    report = analyze(xml, {REAL_SLUG})

    assert report.sitemap_only == {STALE_SLUG}
    assert report.non200 == []
    assert report.failed is True


# --- Acceptance criterion: clean matching case ---------------------------------

def test_clean_matching_case_passes():
    xml = _urlset(f"{SITE}/{REAL_SLUG}", f"{SITE}/best-esim-plans-for-digital-nomads")
    report = analyze(
        xml,
        {REAL_SLUG, "best-esim-plans-for-digital-nomads"},
        url_status=lambda url: 200,
    )

    assert report.sitemap_only == set()
    assert report.published_only == set()
    assert report.non200 == []
    assert report.failed is False
    assert report.verdict == "PASS"


def test_published_only_drift_is_reported_but_not_a_failure():
    """A just-published article legitimately lags the sitemap until the hourly
    ISR revalidate — reported, not a failure."""
    xml = _urlset(f"{SITE}/{REAL_SLUG}")
    report = analyze(xml, {REAL_SLUG, "brand-new-slug"})

    assert report.published_only == {"brand-new-slug"}
    assert report.sitemap_only == set()
    assert report.failed is False
    assert report.verdict == "PASS"


# --- Acceptance criterion 2: absolute AND relative URL handling ----------------

def test_absolute_and_relative_locs_parse_to_the_same_slug_set():
    """Both forms in one document must be recognised as the same article set:
    absolute ``https://www.nomadomics.blog/a`` and site-relative ``/b``."""
    xml = _urlset(f"{SITE}/a-slug", "/b-slug")
    article, non_article = parse_sitemap(xml)
    slugs = {u.rsplit("/", 1)[1] for u in article}

    assert slugs == {"a-slug", "b-slug"}
    assert sorted(article) == [f"{SITE}/a-slug", f"{SITE}/b-slug"]
    assert non_article == []

    report = analyze(xml, {"a-slug", "b-slug"}, url_status=lambda url: 200)
    assert report.failed is False


def test_www_and_apex_hosts_compare_equal():
    """The frontend emits the apex (NEXT_PUBLIC_SITE_URL) while the sitemap is
    served at www; host-key normalisation must treat them as the same origin."""
    xml = _urlset("https://nomadomics.blog/a-slug", f"{SITE}/b-slug")
    report = analyze(xml, {"a-slug", "b-slug"})

    assert report.sitemap_article_slugs == {"a-slug", "b-slug"}
    assert report.sitemap_only == set()
    assert report.failed is False


def test_non_article_and_external_locs_are_excluded():
    xml = _urlset(
        f"{SITE}/",
        f"{SITE}/about",
        f"{SITE}/privacy",
        f"{SITE}/category/banking",
        f"{SITE}/author/guy-mandel",
        "https://external.example/not-an-article",
    )
    report = analyze(xml, {"some-real-slug"})

    assert report.sitemap_article_slugs == set()
    assert report.sitemap_locs_total == 6


def test_unknown_host_single_segment_is_not_an_article():
    xml = _urlset(f"{SITE}/{REAL_SLUG}", "https://other.blog/not-mine")
    report = analyze(xml, {REAL_SLUG})

    assert report.sitemap_article_slugs == {REAL_SLUG}
    assert report.failed is False


# --- Acceptance criterion 2: the compared sets are named in output -------------

def test_report_names_the_compared_sets():
    report = analyze(_urlset(f"{SITE}/{STALE_SLUG}", f"{SITE}/{REAL_SLUG}"), {REAL_SLUG})
    lines = "\n".join(format_report(report))

    assert "sitemap_article_slugs=2" in lines
    assert "published_article_slugs=1" in lines
    assert "sitemap_only=1" in lines
    assert "published_only=0" in lines
    assert "sitemap_only: /cost-of-living-cape-town-nomads" in lines


# --- Acceptance criterion 3: empty/unauthenticated CMS is a dependency error ----

def test_empty_published_set_is_a_dependency_error_not_zero():
    """The fail-open trap: an empty CMS response must never read as 'zero
    published articles'. The pure invariant refuses to analyse an empty set."""
    with pytest.raises(DependencyError, match="EMPTY published-article set"):
        analyze(_urlset(f"{SITE}/{REAL_SLUG}"), set())


def test_fetch_published_slugs_refuses_an_empty_cms_response():
    client = FakeStrapi(data={"data": []})
    with pytest.raises(DependencyError, match="ZERO published article slugs"):
        fetch_published_slugs(client)


def test_fetch_published_slugs_refuses_an_unauthenticated_response():
    from strapi import StrapiError

    client = FakeStrapi(raises=StrapiError("Strapi GET /api/articles -> 401: unauthorized"))
    with pytest.raises(DependencyError, match="Strapi published-articles fetch failed"):
        fetch_published_slugs(client)


# --- Acceptance criterion 4: unavailable-dependency behaviour ------------------

def test_unreachable_sitemap_is_a_dependency_error():
    report = run_integrity(
        client=FakeStrapi(data={"data": [{"slug": REAL_SLUG}]}),
        http_client=FakeHttp(sitemap_text="irrelevant", connect_error=True),
    )

    assert report.dependency_error is not None
    assert "sitemap fetch failed" in report.dependency_error
    assert report.failed is False
    assert report.verdict == "unavailable"


def test_sitemap_http_error_is_a_dependency_error():
    report = run_integrity(
        client=FakeStrapi(data={"data": [{"slug": REAL_SLUG}]}),
        http_client=FakeHttp(sitemap_status=500),
    )

    assert report.dependency_error is not None
    assert "HTTP 500" in report.dependency_error
    assert report.failed is False
    assert report.verdict == "unavailable"


def test_empty_sitemap_body_is_a_dependency_error():
    report = run_integrity(
        client=FakeStrapi(data={"data": [{"slug": REAL_SLUG}]}),
        http_client=FakeHttp(sitemap_text="   "),
    )

    assert report.dependency_error is not None
    assert "EMPTY body" in report.dependency_error
    assert report.verdict == "unavailable"


def test_sitemapindex_is_a_dependency_error():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://www.nomadomics.blog/sitemap-1.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    with pytest.raises(DependencyError, match="sitemap index"):
        parse_sitemap(xml)


def test_clean_live_run_exits_zero():
    xml = _urlset(f"{SITE}/{REAL_SLUG}")
    code = run_sitemap_check(
        client=FakeStrapi(data={"data": [{"slug": REAL_SLUG}]}),
        http_client=FakeHttp(sitemap_text=xml, url_status={f"{SITE}/{REAL_SLUG}": 200}),
    )
    assert code == 0


def test_failing_live_run_exits_one():
    xml = _urlset(f"{SITE}/{REAL_SLUG}", f"{SITE}/{STALE_SLUG}")
    code = run_sitemap_check(
        client=FakeStrapi(data={"data": [{"slug": REAL_SLUG}]}),
        http_client=FakeHttp(
            sitemap_text=xml, url_status={f"{SITE}/{STALE_SLUG}": 404},
        ),
    )
    assert code == 1


def test_unavailable_run_exits_two():
    code = run_sitemap_check(
        client=FakeStrapi(data={"data": []}),
        http_client=FakeHttp(sitemap_text=_urlset(f"{SITE}/{REAL_SLUG}")),
    )
    assert code == 2
