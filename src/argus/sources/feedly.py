"""Fetch articles from Feedly API using Sri's curated feed subscriptions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from argus.models import Article

logger = logging.getLogger(__name__)

FEEDLY_API_BASE = "https://cloud.feedly.com/v3"
FEEDLY_TIMEOUT = 30.0
FEEDLY_PAGE_SIZE = 100


async def fetch_feedly_articles(
    token: str,
    stream_ids: list[str],
    since_hours: int = 4,
) -> list[Article]:
    """Fetch recent articles from Feedly for all configured streams."""
    if not token or not stream_ids:
        logger.info("Feedly: no token or streams configured, skipping")
        return []

    newer_than_ms = int(
        (datetime.now(timezone.utc) - timedelta(hours=since_hours)).timestamp() * 1000
    )

    headers = {"Authorization": f"Bearer {token}"}
    articles: list[Article] = []

    async with httpx.AsyncClient(timeout=FEEDLY_TIMEOUT, headers=headers) as client:
        for stream_id in stream_ids:
            try:
                resp = await client.get(
                    f"{FEEDLY_API_BASE}/streams/contents",
                    params={
                        "streamId": stream_id,
                        "count": FEEDLY_PAGE_SIZE,
                        "newerThan": newer_than_ms,
                    },
                )
                resp.raise_for_status()
                items = resp.json().get("items", [])
            except httpx.HTTPStatusError as e:
                logger.warning("Feedly stream %s failed: %s", stream_id, e)
                continue
            except httpx.HTTPError as e:
                logger.warning("Feedly network error on %s: %s", stream_id, e)
                continue

            for item in items:
                article = _normalize_feedly_item(item)
                if article:
                    articles.append(article)

    logger.info("Feedly: fetched %d articles across %d streams", len(articles), len(stream_ids))
    return articles


def _normalize_feedly_item(item: dict) -> Article | None:
    """Convert a Feedly item dict into an Article."""
    url = item.get("originId") or item.get("canonicalUrl") or ""
    if not url:
        alternate = item.get("alternate") or []
        if alternate and isinstance(alternate, list):
            url = alternate[0].get("href", "")
    if not url:
        return None

    title = item.get("title", "").strip() or "(untitled)"
    summary_html = (item.get("summary") or {}).get("content", "")
    summary = _strip_html(summary_html)[:500]
    source_name = (item.get("origin") or {}).get("title", "")

    published_at: datetime | None = None
    published_ms = item.get("published")
    if isinstance(published_ms, (int, float)):
        try:
            published_at = datetime.fromtimestamp(published_ms / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            published_at = None

    return Article(
        url=url,
        title=title,
        summary=summary,
        source_name=source_name,
        published_at=published_at,
        fetched_from="feedly",
    )


def _strip_html(html: str) -> str:
    """Crude HTML strip — no external dep needed for digest summaries."""
    if not html:
        return ""
    import re

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
