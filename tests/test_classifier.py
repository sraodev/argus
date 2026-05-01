"""Tests for Argus classifier."""

from argus.models import Article, Criticality


def test_article_model() -> None:
    """Verify Article model can be created with minimal fields."""
    article = Article(url="https://example.com/test", title="Test Article")
    assert article.url == "https://example.com/test"
    assert article.fetched_from == "rss"


def test_criticality_ordering() -> None:
    """Verify criticality enum values."""
    assert Criticality.CRITICAL.value == "critical"
    assert Criticality.HIGH.value == "high"
