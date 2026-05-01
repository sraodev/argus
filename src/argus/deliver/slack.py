"""Send alerts and digests to Slack using Block Kit formatting."""

from __future__ import annotations

import logging

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from argus.models import ClassifiedArticle, Criticality, Digest

logger = logging.getLogger(__name__)

CRITICALITY_EMOJI: dict[Criticality, str] = {
    Criticality.CRITICAL: ":rotating_light:",
    Criticality.HIGH: ":warning:",
    Criticality.MEDIUM: ":large_yellow_circle:",
    Criticality.LOW: ":large_blue_circle:",
    Criticality.INFORMATIONAL: ":information_source:",
}

CRITICALITY_ORDER: list[Criticality] = [
    Criticality.CRITICAL,
    Criticality.HIGH,
    Criticality.MEDIUM,
    Criticality.LOW,
    Criticality.INFORMATIONAL,
]


def send_critical_alert(client: WebClient, channel: str, article: ClassifiedArticle) -> None:
    """Send an immediate Slack alert for a critical article."""
    c = article.classification
    a = article.article

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":rotating_light: ARGUS CRITICAL ALERT"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{_escape(a.title)}*\n{_escape(c.one_line_summary or a.summary[:200])}",
            },
        },
    ]

    if c.guard0_relevance:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":office: *Guard0 relevance:* {_escape(c.guard0_relevance)}",
                },
            }
        )

    meta_bits: list[str] = []
    if c.tags:
        meta_bits.append(":label: " + ", ".join(_escape(t) for t in c.tags[:5]))
    meta_bits.append(f":file_folder: {c.category.value}")
    if a.source_name:
        meta_bits.append(f":newspaper: {_escape(a.source_name)}")

    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": " | ".join(meta_bits)},
        }
    )

    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":link: <{a.url}|Read more>"},
        }
    )

    fallback = f"ARGUS CRITICAL: {a.title}"
    _post(client, channel, blocks, fallback)


def send_daily_digest(client: WebClient, channel: str, digest: Digest) -> None:
    """Send the full daily digest to Slack, grouped by criticality."""
    s = digest.stats

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":eye: Argus Daily Intel — {digest.date}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":bar_chart: *{s.critical}* Critical | "
                    f"*{s.high}* High | *{s.medium}* Medium | "
                    f"*{s.low}* Low | *{s.informational}* Info  "
                    f"(total {s.total})"
                ),
            },
        },
        {"type": "divider"},
    ]

    if digest.weekly_summary:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":memo: *Weekly summary*\n{_escape(digest.weekly_summary)}",
                },
            }
        )
        blocks.append({"type": "divider"})

    grouped: dict[Criticality, list[ClassifiedArticle]] = {c: [] for c in CRITICALITY_ORDER}
    for article in digest.articles:
        grouped[article.classification.criticality].append(article)

    for level in CRITICALITY_ORDER:
        items = grouped[level]
        if not items:
            continue

        emoji = CRITICALITY_EMOJI[level]
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *{level.value.upper()}* ({len(items)})",
                },
            }
        )

        for ca in items[:10]:
            a = ca.article
            c = ca.classification
            line = (
                f"• *{_escape(a.title)}*"
                f" — {_escape(c.one_line_summary or a.summary[:200])}\n"
                f"  :link: <{a.url}|link>"
            )
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": line}}
            )

        if len(items) > 10:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"_+{len(items) - 10} more {level.value} items in archive_",
                        }
                    ],
                }
            )

    blocks.append({"type": "divider"})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":eye: Argus by Guard0 | Protecting the AI-first enterprise",
                }
            ],
        }
    )

    fallback = f"Argus Daily Intel {digest.date} — {s.total} articles"
    _post(client, channel, blocks, fallback)


def _post(client: WebClient, channel: str, blocks: list[dict], fallback: str) -> None:
    """Send blocks to Slack with consistent error handling."""
    try:
        client.chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=fallback,
            unfurl_links=False,
            unfurl_media=False,
        )
        logger.info("Slack: posted to %s", channel)
    except SlackApiError as e:
        logger.error("Slack post failed: %s", e.response.get("error", e))


def _escape(text: str) -> str:
    """Escape Slack mrkdwn metacharacters."""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
