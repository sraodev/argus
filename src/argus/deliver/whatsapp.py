"""Send alerts and digest summaries via WhatsApp (Twilio)."""

from __future__ import annotations

import logging

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from argus.models import ClassifiedArticle, Criticality, Digest

logger = logging.getLogger(__name__)

WHATSAPP_BODY_LIMIT = 1500  # Twilio caps at 1600; leave headroom


def send_critical_whatsapp(
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_number: str,
    article: ClassifiedArticle,
) -> None:
    """Send a brief WhatsApp alert for a critical article."""
    a = article.article
    c = article.classification
    summary = c.one_line_summary or a.summary[:200]

    body = (
        "🚨 ARGUS CRITICAL\n\n"
        f"*{a.title}*\n"
        f"{summary}\n\n"
        f"{a.url}"
    )
    _send(account_sid, auth_token, from_number, to_number, body)


def send_digest_whatsapp(
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_number: str,
    digest: Digest,
) -> None:
    """Send a brief WhatsApp summary of the daily digest."""
    s = digest.stats

    top = [
        ca for ca in digest.articles
        if ca.classification.criticality in (Criticality.CRITICAL, Criticality.HIGH)
    ][:3]

    lines = [
        f"👁️ Argus Daily — {digest.date}",
        f"{s.critical} Critical | {s.high} High | {s.medium} Medium | {s.low} Low",
        "",
    ]

    if top:
        lines.append("Top items:")
        for i, ca in enumerate(top, 1):
            title = ca.article.title[:80]
            lines.append(f"{i}. {title}")
        lines.append("")

    lines.append("Full digest → Slack #argus-intel")
    body = "\n".join(lines)
    _send(account_sid, auth_token, from_number, to_number, body)


def _send(
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_number: str,
    body: str,
) -> None:
    """Send a WhatsApp message via Twilio with consistent error handling."""
    if not (account_sid and auth_token and from_number and to_number):
        logger.info("WhatsApp: missing Twilio config, skipping send")
        return

    if len(body) > WHATSAPP_BODY_LIMIT:
        body = body[: WHATSAPP_BODY_LIMIT - 3] + "..."

    try:
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            from_=from_number,
            to=to_number,
            body=body,
        )
        logger.info("WhatsApp: sent message sid=%s", message.sid)
    except TwilioRestException as e:
        logger.error("WhatsApp send failed: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.error("WhatsApp unexpected error: %s", e)
