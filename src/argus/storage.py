"""Local JSON storage for articles, dedup tracking, and digest archives."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from argus.models import ClassifiedArticle, Digest

logger = logging.getLogger(__name__)

MAX_SEEN_URLS = 5000
TRIM_TO = 3000


class Storage:
    """Manages all Argus data files under ~/.argus/data/."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.seen_file = data_dir / "seen_urls.json"
        self.today_file = data_dir / "today_articles.json"
        self.digest_dir = data_dir / "digests"
        self.digest_dir.mkdir(parents=True, exist_ok=True)

    # ── Deduplication ─────────────────────────────────────

    def load_seen_urls(self) -> set[str]:
        """Load the set of already-processed URLs."""
        if not self.seen_file.exists():
            return set()
        data = json.loads(self.seen_file.read_text())
        return set(data) if isinstance(data, list) else set()

    def save_seen_urls(self, urls: set[str]) -> None:
        """Persist seen URLs, trimming if over limit."""
        url_list = list(urls)
        if len(url_list) > MAX_SEEN_URLS:
            url_list = url_list[-TRIM_TO:]
            logger.info("Trimmed seen_urls from %d to %d", len(urls), TRIM_TO)
        self.seen_file.write_text(json.dumps(url_list, indent=2))

    def is_seen(self, url: str) -> bool:
        """Check if a URL has already been processed."""
        return url in self.load_seen_urls()

    def mark_seen(self, urls: list[str]) -> None:
        """Add URLs to the seen set."""
        seen = self.load_seen_urls()
        seen.update(urls)
        self.save_seen_urls(seen)

    # ── Today's articles ──────────────────────────────────

    def load_today_articles(self) -> list[ClassifiedArticle]:
        """Load articles classified today."""
        if not self.today_file.exists():
            return []
        data = json.loads(self.today_file.read_text())
        return [ClassifiedArticle.model_validate(item) for item in data]

    def append_articles(self, articles: list[ClassifiedArticle]) -> None:
        """Append newly classified articles to today's file."""
        existing = self.load_today_articles()
        existing.extend(articles)
        self._write_articles(self.today_file, existing)
        logger.info("Appended %d articles (total today: %d)", len(articles), len(existing))

    def clear_today(self) -> None:
        """Reset today's articles after digest is sent."""
        self.today_file.write_text("[]")

    # ── Digest archives ───────────────────────────────────

    def save_digest(self, digest: Digest) -> None:
        """Archive a daily digest."""
        path = self.digest_dir / f"{digest.date}.json"
        path.write_text(digest.model_dump_json(indent=2))
        logger.info("Saved digest to %s", path)

    def load_digest(self, date_str: str) -> Digest | None:
        """Load a specific day's digest."""
        path = self.digest_dir / f"{date_str}.json"
        if not path.exists():
            return None
        return Digest.model_validate_json(path.read_text())

    def load_recent_digests(self, days: int = 7) -> list[Digest]:
        """Load digests from the last N days."""
        digests: list[Digest] = []
        today = date.today()
        for i in range(days):
            d = today - timedelta(days=i)
            digest = self.load_digest(d.isoformat())
            if digest:
                digests.append(digest)
        return digests

    # ── Helpers ────────────────────────────────────────────

    def _write_articles(self, path: Path, articles: list[ClassifiedArticle]) -> None:
        data = [a.model_dump(mode="json") for a in articles]
        path.write_text(json.dumps(data, indent=2, default=str))
