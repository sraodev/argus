"""Argus CLI — the command interface for all operations.

Commands:
    argus scan      Fetch → Dedup → Classify → Alert criticals
    argus digest    Compile today's articles → Slack + WhatsApp
    argus query     Search recent articles by keyword
    argus setup     Interactive setup wizard
    argus status    Show current state and connection health
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date

import anthropic
import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from argus.classifier import classify_articles
from argus.config import Config, load_config
from argus.deliver.slack import send_critical_alert, send_daily_digest
from argus.deliver.whatsapp import send_critical_whatsapp, send_digest_whatsapp
from argus.models import (
    Article,
    ClassifiedArticle,
    Criticality,
    Digest,
)
from argus.sources.feedly import fetch_feedly_articles
from argus.sources.rss import fetch_rss_articles
from argus.sources.web import fetch_web_articles
from argus.storage import Storage

console = Console()


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging with rich handler."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def main(verbose: bool) -> None:
    """👁️ Argus — AI Security Threat Intelligence for Guard0."""
    _setup_logging(verbose)


# ── argus scan ────────────────────────────────────────────


@main.command()
@click.option("--hours", default=4, help="Fetch articles from the last N hours.")
@click.option("--dry-run", is_flag=True, help="Print results without sending alerts.")
@click.option(
    "--sources",
    default="feedly,rss,web",
    help="Comma-separated sources: feedly,rss,web",
)
def scan(hours: int, dry_run: bool, sources: str) -> None:
    """Fetch articles, classify, and alert on critical items."""
    cfg = load_config()
    if not cfg.anthropic_api_key:
        console.print("[red]✗ ANTHROPIC_API_KEY not set. Run: argus setup[/red]")
        sys.exit(1)

    selected = {s.strip() for s in sources.split(",") if s.strip()}
    console.print(
        f"[bold]👁️ Argus scan[/bold] — last {hours}h, "
        f"sources: {','.join(sorted(selected))}"
        + (" [yellow](dry run)[/yellow]" if dry_run else "")
    )

    asyncio.run(_run_scan(cfg, hours=hours, dry_run=dry_run, selected_sources=selected))


async def _run_scan(
    cfg: Config, hours: int, dry_run: bool, selected_sources: set[str]
) -> None:
    storage = Storage(cfg.data_dir)
    client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)

    raw = await _fetch_all_sources(cfg, client, hours, selected_sources)
    console.print(f"  Fetched: [bold]{len(raw)}[/bold] raw articles")

    fresh = _dedup(raw, storage)
    console.print(f"  After dedup: [bold]{len(fresh)}[/bold] new articles")

    if not fresh:
        console.print("[green]✓ Nothing new to classify[/green]")
        return

    classified = await classify_articles(client, cfg.model, fresh)
    console.print(f"  Classified: [bold]{len(classified)}[/bold] relevant articles")

    if dry_run:
        _print_classified_table(classified)
        return

    storage.append_articles(classified)
    storage.mark_seen([a.url for a in fresh])

    criticals = [c for c in classified if c.is_critical]
    if criticals:
        console.print(f"  [red]🚨 Sending {len(criticals)} critical alerts[/red]")
        _send_critical_alerts(cfg, criticals)

    console.print("[green]✓ Scan complete[/green]")


async def _fetch_all_sources(
    cfg: Config,
    client: anthropic.AsyncAnthropic,
    hours: int,
    selected: set[str],
) -> list[Article]:
    """Run enabled fetchers in parallel, collect normalized Articles."""
    tasks: list = []
    labels: list[str] = []

    if "feedly" in selected and cfg.has_feedly:
        tasks.append(fetch_feedly_articles(cfg.feedly_token, cfg.feedly_streams, hours))
        labels.append("feedly")
    if "rss" in selected:
        tasks.append(fetch_rss_articles(cfg.rss_feeds, hours))
        labels.append("rss")
    if "web" in selected:
        tasks.append(fetch_web_articles(client, cfg.model))
        labels.append("web")

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)

    articles: list[Article] = []
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            console.print(f"  [yellow]⚠ {label} failed: {result}[/yellow]")
            continue
        articles.extend(result)
        console.print(f"  • {label}: {len(result)}")
    return articles


def _dedup(articles: list[Article], storage: Storage) -> list[Article]:
    """Drop articles whose URL is already in seen_urls or duplicated this batch."""
    seen = storage.load_seen_urls()
    fresh: list[Article] = []
    batch_seen: set[str] = set()
    for a in articles:
        if a.url in seen or a.url in batch_seen:
            continue
        batch_seen.add(a.url)
        fresh.append(a)
    return fresh


def _send_critical_alerts(cfg: Config, criticals: list[ClassifiedArticle]) -> None:
    slack = _slack_client(cfg)
    for article in criticals:
        if slack:
            send_critical_alert(slack, cfg.slack_channel, article)
        if cfg.has_whatsapp and cfg.whatsapp_to:
            send_critical_whatsapp(
                cfg.twilio_account_sid,
                cfg.twilio_auth_token,
                cfg.twilio_whatsapp_from,
                cfg.whatsapp_to,
                article,
            )


def _slack_client(cfg: Config):
    if not cfg.has_slack:
        return None
    from slack_sdk import WebClient

    return WebClient(token=cfg.slack_bot_token)


def _print_classified_table(classified: list[ClassifiedArticle]) -> None:
    if not classified:
        console.print("[dim]No relevant articles[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Crit", width=6)
    table.add_column("Cat", width=12)
    table.add_column("Title", overflow="fold")
    table.add_column("Source", width=20)
    for ca in classified:
        table.add_row(
            ca.classification.criticality.value,
            ca.classification.category.value,
            ca.article.title[:80],
            ca.article.source_name[:20],
        )
    console.print(table)


# ── argus digest ──────────────────────────────────────────


@main.command()
@click.option("--dry-run", is_flag=True, help="Print digest without sending.")
@click.option("--weekly", is_flag=True, help="Generate weekly executive brief instead.")
def digest(dry_run: bool, weekly: bool) -> None:
    """Compile today's articles into a digest and deliver."""
    cfg = load_config()
    kind = "weekly" if weekly else "daily"
    console.print(
        f"[bold]👁️ Argus {kind} digest[/bold]"
        + (" [yellow](dry run)[/yellow]" if dry_run else "")
    )
    asyncio.run(_run_digest(cfg, dry_run=dry_run, weekly=weekly))


async def _run_digest(cfg: Config, dry_run: bool, weekly: bool) -> None:
    storage = Storage(cfg.data_dir)

    if weekly:
        recent = storage.load_recent_digests(days=7)
        articles = [ca for d in recent for ca in d.articles]
    else:
        articles = storage.load_today_articles()

    if not articles:
        console.print("[yellow]No articles to digest[/yellow]")
        return

    digest_obj = Digest(date=date.today().isoformat(), articles=articles)
    digest_obj.compute_stats()

    if weekly and cfg.anthropic_api_key:
        digest_obj.weekly_summary = await _build_weekly_summary(cfg, digest_obj)

    s = digest_obj.stats
    console.print(
        f"  {s.total} articles: "
        f"[red]{s.critical}C[/red] [orange1]{s.high}H[/orange1] "
        f"[yellow]{s.medium}M[/yellow] {s.low}L {s.informational}I"
    )

    if dry_run:
        _print_classified_table(digest_obj.articles)
        return

    slack = _slack_client(cfg)
    if slack:
        send_daily_digest(slack, cfg.slack_channel, digest_obj)
    if cfg.has_whatsapp and cfg.whatsapp_to:
        send_digest_whatsapp(
            cfg.twilio_account_sid,
            cfg.twilio_auth_token,
            cfg.twilio_whatsapp_from,
            cfg.whatsapp_to,
            digest_obj,
        )

    storage.save_digest(digest_obj)
    if not weekly:
        storage.clear_today()

    console.print("[green]✓ Digest delivered[/green]")


async def _build_weekly_summary(cfg: Config, digest_obj: Digest) -> str:
    """Ask Claude to produce a 3–5 sentence executive brief over the week."""
    client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_api_key)
    high_signal = [
        ca for ca in digest_obj.articles
        if ca.classification.criticality
        in (Criticality.CRITICAL, Criticality.HIGH, Criticality.MEDIUM)
    ][:30]

    bullets = "\n".join(
        f"- [{ca.classification.criticality.value}] {ca.article.title}: "
        f"{ca.classification.one_line_summary}"
        for ca in high_signal
    )

    response = await client.messages.create(
        model=cfg.model,
        max_tokens=600,
        system=(
            "You are Argus, the AI security analyst for Guard0. "
            "Write a tight 3–5 sentence executive brief covering this week's AI security news. "
            "Focus on themes and what Guard0 customers should care about. No bullet lists, prose only."
        ),
        messages=[{"role": "user", "content": f"This week's items:\n{bullets}"}],
    )
    parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip()


# ── argus query ───────────────────────────────────────────


@main.command()
@click.argument("keyword")
@click.option("--days", default=7, help="Search digests from the last N days.")
def query(keyword: str, days: int) -> None:
    """Search recent articles by keyword."""
    cfg = load_config()
    storage = Storage(cfg.data_dir)
    console.print(f"[bold]👁️ Argus query:[/bold] '{keyword}' (last {days} days)")

    needle = keyword.lower()
    digests = storage.load_recent_digests(days=days)
    today = storage.load_today_articles()
    pool: list[ClassifiedArticle] = list(today)
    for d in digests:
        pool.extend(d.articles)

    matches: list[ClassifiedArticle] = []
    for ca in pool:
        haystack = " ".join(
            [
                ca.article.title,
                ca.article.summary,
                ca.classification.one_line_summary,
                " ".join(ca.classification.tags),
            ]
        ).lower()
        if needle in haystack:
            matches.append(ca)

    matches.sort(
        key=lambda ca: (
            -["informational", "low", "medium", "high", "critical"].index(
                ca.classification.criticality.value
            ),
            ca.classified_at,
        ),
        reverse=True,
    )

    if not matches:
        console.print("[dim]No matches[/dim]")
        return
    _print_classified_table(matches[:50])


# ── argus setup ───────────────────────────────────────────


@main.command()
def setup() -> None:
    """Show current configuration and which keys are missing."""
    console.print("[bold]👁️ Argus setup wizard[/bold]\n")
    cfg = load_config()

    checks = [
        ("Anthropic API", cfg.anthropic_api_key),
        ("Feedly", cfg.feedly_token),
        ("Slack", cfg.slack_bot_token),
        ("WhatsApp (Twilio)", cfg.twilio_account_sid),
    ]
    for name, value in checks:
        status = "[green]✓ configured[/green]" if value else "[red]✗ not set[/red]"
        console.print(f"  {name}: {status}")

    console.print("\nEdit [bold]~/.argus/.env[/bold] to configure missing services.")
    console.print("Then run [bold]argus scan --dry-run[/bold] to test.")


# ── argus status ──────────────────────────────────────────


@main.command()
def status() -> None:
    """Show current Argus state and connection health."""
    cfg = load_config()
    storage = Storage(cfg.data_dir)

    console.print("[bold]👁️ Argus status[/bold]\n")

    seen = storage.load_seen_urls()
    today = storage.load_today_articles()
    digests = list(storage.digest_dir.glob("*.json"))

    console.print(f"  Seen URLs:        {len(seen)}")
    console.print(f"  Articles today:   {len(today)}")
    console.print(f"  Digest archives:  {len(digests)}\n")

    checks = [
        ("Anthropic API", cfg.anthropic_api_key),
        ("Feedly", cfg.feedly_token),
        ("Slack", cfg.slack_bot_token),
        ("WhatsApp", cfg.twilio_account_sid),
    ]
    for name, value in checks:
        icon = "✓" if value else "✗"
        color = "green" if value else "red"
        console.print(f"  [{color}]{icon}[/{color}] {name}")


if __name__ == "__main__":
    main()
