"""Fetch articles via Claude API web search tool — catches news not in RSS/Feedly."""

from __future__ import annotations

import logging
import random
from urllib.parse import urlparse

import anthropic

from argus.models import Article

logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    "AI security vulnerability latest",
    "LLM exploit prompt injection new",
    "AI supply chain attack 2026",
    "model poisoning training data attack new",
    "RAG poisoning vulnerability",
    "MCP server security advisory",
    "AI agent jailbreak research",
]

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}
MAX_TOKENS = 4096


async def fetch_web_articles(
    client: anthropic.AsyncAnthropic,
    model: str,
    queries: list[str] | None = None,
    queries_per_scan: int = 2,
) -> list[Article]:
    """Use Claude's web_search tool to find latest AI security news."""
    pool = queries or SEARCH_QUERIES
    if not pool:
        return []

    picks = random.sample(pool, min(queries_per_scan, len(pool)))
    articles: list[Article] = []

    for query in picks:
        try:
            articles.extend(await _run_query(client, model, query))
        except anthropic.APIError as e:
            logger.warning("Web search failed for %r: %s", query, e)
        except Exception as e:  # noqa: BLE001
            logger.warning("Web search unexpected error for %r: %s", query, e)

    logger.info("Web: fetched %d articles across %d queries", len(articles), len(picks))
    return articles


async def _run_query(
    client: anthropic.AsyncAnthropic, model: str, query: str
) -> list[Article]:
    """Run one web_search query through Claude and extract Articles."""
    response = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        tools=[WEB_SEARCH_TOOL],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Search the web for: {query}\n"
                    "Find the most recent and authoritative articles on this topic. "
                    "Prioritize results from the last 7 days from security vendors, "
                    "research labs, and reputable tech news sources."
                ),
            }
        ],
    )

    return _extract_articles_from_response(response)


def _extract_articles_from_response(response) -> list[Article]:
    """Walk Claude's content blocks and pull out web_search_result items."""
    articles: list[Article] = []
    seen_urls: set[str] = set()

    for block in response.content:
        block_type = getattr(block, "type", None)

        if block_type == "web_search_tool_result":
            results = getattr(block, "content", []) or []
            for item in results:
                article = _parse_search_item(item)
                if article and article.url not in seen_urls:
                    seen_urls.add(article.url)
                    articles.append(article)

    return articles


def _parse_search_item(item) -> Article | None:
    """Parse a single web_search_result block item."""
    item_type = getattr(item, "type", None) or (
        item.get("type") if isinstance(item, dict) else None
    )
    if item_type != "web_search_result":
        return None

    def _get(key: str, default: str = "") -> str:
        if isinstance(item, dict):
            return item.get(key, default) or default
        return getattr(item, key, default) or default

    url = _get("url")
    if not url:
        return None

    title = _get("title", "(untitled)").strip() or "(untitled)"
    snippet = _get("encrypted_content") or _get("snippet") or _get("page_age", "")
    summary = (snippet[:500] if isinstance(snippet, str) else "")
    source_name = _domain_of(url)

    return Article(
        url=url,
        title=title,
        summary=summary,
        source_name=source_name,
        published_at=None,
        fetched_from="web",
    )


def _domain_of(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc.removeprefix("www.")
    except ValueError:
        return ""
