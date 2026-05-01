"""Fetch articles from direct RSS feeds using feedparser."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser

from argus.models import Article

logger = logging.getLogger(__name__)

RSS_TIMEOUT = 20.0


async def fetch_rss_articles(
    feed_urls: list[str],
    since_hours: int = 4,
) -> list[Article]:
    """Fetch and parse recent articles from RSS/Atom feeds."""
    if not feed_urls:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    results = await asyncio.gather(
        *(_fetch_single(url, cutoff) for url in feed_urls),
        return_exceptions=True,
    )

    articles: list[Article] = []
    for url, result in zip(feed_urls, results):
        if isinstance(result, Exception):
            logger.warning("RSS feed %s failed: %s", url, result)
            continue
        articles.extend(result)

    logger.info("RSS: fetched %d articles across %d feeds", len(articles), len(feed_urls))
    return articles


async def _fetch_single(feed_url: str, cutoff: datetime) -> list[Article]:
    """Parse one feed in a thread (feedparser is sync) and normalize entries."""
    parsed = await asyncio.wait_for(
        asyncio.to_thread(feedparser.parse, feed_url),
        timeout=RSS_TIMEOUT,
    )

    if parsed.bozo and not parsed.entries:
        logger.debug("RSS feed %s parse error: %s", feed_url, parsed.bozo_exception)
        return []

    source_name = getattr(parsed.feed, "title", "") or feed_url
    articles: list[Article] = []

    for entry in parsed.entries:
        article = _normalize_rss_entry(entry, source_name, cutoff)
        if article:
            articles.append(article)

    return articles


def _normalize_rss_entry(entry, source_name: str, cutoff: datetime) -> Article | None:
    """Convert a feedparser entry into an Article (or None if too old / invalid)."""
    url = getattr(entry, "link", "") or ""
    if not url:
        return None

    title = (getattr(entry, "title", "") or "(untitled)").strip()

    raw_summary = (
        getattr(entry, "summary", "")
        or getattr(entry, "description", "")
        or ""
    )
    summary = _strip_html(raw_summary)[:500]

    published_at: datetime | None = None
    parsed_time = (
        getattr(entry, "published_parsed", None)
        or getattr(entry, "updated_parsed", None)
    )
    if parsed_time:
        try:
            published_at = datetime.fromtimestamp(mktime(parsed_time), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            published_at = None

    if published_at and published_at < cutoff:
        return None

    return Article(
        url=url,
        title=title,
        summary=summary,
        source_name=source_name,
        published_at=published_at,
        fetched_from="rss",
    )


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = _HTML_TAG_RE.sub(" ", html)
    return _WHITESPACE_RE.sub(" ", text).strip()
