"""Classify articles using Claude API — the brain of Argus.

Two-stage pipeline:
  1. Keyword pre-filter (free, instant) — fast-track or skip obvious articles
  2. Claude API batch classification — structured JSON output per article
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

import anthropic

from argus.models import (
    Article,
    Category,
    ClassifiedArticle,
    Classification,
    Criticality,
)

logger = logging.getLogger(__name__)

# ── Stage 1: Keyword pre-filter (no API cost) ────────────

FAST_TRACK_KEYWORDS: list[str] = [
    "prompt injection", "model poisoning", "ai supply chain",
    "llm vulnerability", "adversarial ml", "jailbreak",
    "model extraction", "training data leak", "owasp llm",
    "ai security", "model theft", "ai red team",
    "rag poisoning", "agent hijacking", "tool poisoning",
    "mcp security", "guardrails bypass", "ai gateway",
    "shadow ai", "llm firewall", "embedding attack",
    "onnx vulnerability", "hugging face security",
    "pytorch cve", "tensorflow cve", "langchain vulnerability",
    "ai agent exploit", "deepfake detection", "ai governance",
]

SKIP_KEYWORDS: list[str] = [
    "recipe", "sports score", "celebrity gossip", "horoscope",
    "dating app", "reality tv", "fashion week", "box office",
    "music awards", "astrology",
]

# ── Stage 2: Claude API classification prompt ─────────────

SYSTEM_PROMPT = """You are Argus, the AI security intelligence analyst for Guard0,
an AI Security Posture Management (AI-SPM) platform.

Guard0 helps enterprises discover shadow AI, validate AI security with red teaming
(rakshan-kavach), and monitor AI supply chain risks through code-to-cloud correlation.

Classify each article for our daily threat intelligence digest.
Only mark as relevant if it relates to AI/ML security, AI governance,
or threats to AI-powered systems.

For guard0_relevance: explain why this matters for companies using AI in production —
think prompt injection defense, model supply chain, LLM monitoring, AI access control.

Respond ONLY with a JSON array. No markdown fences, no preamble."""

CLASSIFICATION_SCHEMA_HINT = """Each item in the JSON array must follow this exact schema:
{
  "index": <int, the article number from the input>,
  "relevant": <bool>,
  "category": <one of: "vulnerability", "attack", "regulation", "tool", "research", "incident", "advisory">,
  "criticality": <one of: "critical", "high", "medium", "low", "informational">,
  "ai_specific": <bool, true if specifically about AI/ML systems>,
  "tags": <list of short string tags>,
  "one_line_summary": <single sentence, max 200 chars>,
  "guard0_relevance": <single sentence, why this matters for Guard0 customers>
}"""

VALID_CATEGORIES = {c.value for c in Category}
VALID_CRITICALITIES = {c.value for c in Criticality}
MAX_OUTPUT_TOKENS = 4096


# ── Stage 1 ───────────────────────────────────────────────


def pre_filter(article: Article) -> Literal["fast_track", "skip", "needs_llm"]:
    """Keyword-based pre-filter to save API costs."""
    text = f"{article.title} {article.summary}".lower()

    for kw in SKIP_KEYWORDS:
        if kw in text:
            return "skip"

    for kw in FAST_TRACK_KEYWORDS:
        if kw in text:
            return "fast_track"

    return "needs_llm"


# ── Stage 2 ───────────────────────────────────────────────


async def classify_articles(
    client: anthropic.AsyncAnthropic,
    model: str,
    articles: list[Article],
    batch_size: int = 10,
) -> list[ClassifiedArticle]:
    """Classify a list of articles using the two-stage pipeline."""
    if not articles:
        return []

    candidates: list[Article] = []
    skipped = 0
    for article in articles:
        verdict = pre_filter(article)
        if verdict == "skip":
            skipped += 1
            continue
        candidates.append(article)

    logger.info(
        "Pre-filter: %d candidates (%d skipped) of %d articles",
        len(candidates),
        skipped,
        len(articles),
    )

    if not candidates:
        return []

    classified: list[ClassifiedArticle] = []
    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start : batch_start + batch_size]
        try:
            classifications = await _classify_batch(client, model, batch)
        except Exception as e:  # noqa: BLE001
            logger.warning("Batch classification failed: %s", e)
            continue

        for article, classification in zip(batch, classifications):
            if classification and classification.relevant:
                classified.append(
                    ClassifiedArticle(article=article, classification=classification)
                )

    logger.info("Classifier: %d relevant of %d candidates", len(classified), len(candidates))
    return classified


async def _classify_batch(
    client: anthropic.AsyncAnthropic,
    model: str,
    batch: list[Article],
) -> list[Classification | None]:
    """Send one batch to Claude, return one Classification per input slot."""
    user_message = _format_batch_prompt(batch)

    response = await client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT + "\n\n" + CLASSIFICATION_SCHEMA_HINT,
        messages=[{"role": "user", "content": user_message}],
    )

    if hasattr(response, "usage"):
        logger.debug(
            "Classification batch tokens: in=%d out=%d",
            getattr(response.usage, "input_tokens", 0),
            getattr(response.usage, "output_tokens", 0),
        )

    raw_text = _extract_text(response)
    items = _parse_json_array(raw_text)

    results: list[Classification | None] = [None] * len(batch)
    for item in items:
        idx = item.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(batch):
            continue
        results[idx] = _build_classification(item)

    return results


def _format_batch_prompt(batch: list[Article]) -> str:
    """Render the batch as numbered items in the user prompt."""
    lines = ["Classify the following articles. Return a JSON array with one object per article.\n"]
    for i, article in enumerate(batch):
        lines.append(f"--- Article {i} ---")
        lines.append(f"Title: {article.title}")
        if article.source_name:
            lines.append(f"Source: {article.source_name}")
        if article.summary:
            lines.append(f"Summary: {article.summary[:600]}")
        lines.append(f"URL: {article.url}")
        lines.append("")
    return "\n".join(lines)


def _extract_text(response) -> str:
    """Concatenate all text blocks from a Messages API response."""
    parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "\n".join(parts).strip()


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _parse_json_array(text: str) -> list[dict]:
    """Parse a JSON array from Claude's response, tolerating fences and stray prose."""
    if not text:
        return []

    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()

    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        logger.warning("No JSON array found in classifier response")
        return []

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        logger.warning("Classifier JSON parse failed: %s", e)
        return []

    return [item for item in parsed if isinstance(item, dict)]


def _build_classification(item: dict) -> Classification:
    """Build a Classification from a dict, defaulting unknown enums safely."""
    category_raw = str(item.get("category", "")).lower()
    category = Category(category_raw) if category_raw in VALID_CATEGORIES else Category.RESEARCH

    crit_raw = str(item.get("criticality", "")).lower()
    criticality = (
        Criticality(crit_raw) if crit_raw in VALID_CRITICALITIES else Criticality.INFORMATIONAL
    )

    tags_raw = item.get("tags", [])
    tags = [str(t) for t in tags_raw if isinstance(t, (str, int, float))] if isinstance(
        tags_raw, list
    ) else []

    return Classification(
        relevant=bool(item.get("relevant", False)),
        category=category,
        criticality=criticality,
        ai_specific=bool(item.get("ai_specific", False)),
        tags=tags,
        one_line_summary=str(item.get("one_line_summary", ""))[:300],
        guard0_relevance=str(item.get("guard0_relevance", ""))[:500],
    )
