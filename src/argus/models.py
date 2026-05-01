"""Domain models for Argus threat intelligence pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class Criticality(str, Enum):
    """Threat criticality levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class Category(str, Enum):
    """Article classification categories."""

    VULNERABILITY = "vulnerability"
    ATTACK = "attack"
    REGULATION = "regulation"
    TOOL = "tool"
    RESEARCH = "research"
    INCIDENT = "incident"
    ADVISORY = "advisory"


class Article(BaseModel):
    """A raw article fetched from any source."""

    url: str
    title: str
    summary: str = ""
    source_name: str = ""
    published_at: datetime | None = None
    fetched_from: Literal["feedly", "rss", "web"] = "rss"


class Classification(BaseModel):
    """LLM-produced classification for an article."""

    relevant: bool = False
    category: Category = Category.VULNERABILITY
    criticality: Criticality = Criticality.INFORMATIONAL
    ai_specific: bool = False
    tags: list[str] = Field(default_factory=list)
    one_line_summary: str = ""
    guard0_relevance: str = ""


class ClassifiedArticle(BaseModel):
    """An article with its classification attached."""

    article: Article
    classification: Classification
    classified_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_critical(self) -> bool:
        return self.classification.criticality == Criticality.CRITICAL

    @property
    def is_high_or_above(self) -> bool:
        return self.classification.criticality in (
            Criticality.CRITICAL,
            Criticality.HIGH,
        )


class DigestStats(BaseModel):
    """Aggregate counts for a digest."""

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    informational: int = 0
    total: int = 0


class Digest(BaseModel):
    """A compiled daily or weekly digest."""

    date: str
    articles: list[ClassifiedArticle] = Field(default_factory=list)
    stats: DigestStats = Field(default_factory=DigestStats)
    weekly_summary: str | None = None

    def compute_stats(self) -> None:
        """Recompute stats from articles."""
        self.stats = DigestStats(total=len(self.articles))
        for a in self.articles:
            crit = a.classification.criticality
            if crit == Criticality.CRITICAL:
                self.stats.critical += 1
            elif crit == Criticality.HIGH:
                self.stats.high += 1
            elif crit == Criticality.MEDIUM:
                self.stats.medium += 1
            elif crit == Criticality.LOW:
                self.stats.low += 1
            else:
                self.stats.informational += 1
