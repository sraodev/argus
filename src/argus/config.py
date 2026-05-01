"""Configuration management — loads from ~/.argus/.env or environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    """Load .env from ~/.argus/.env, then project .env as fallback.

    override=True so values in ~/.argus/.env win over stale/empty shell exports.
    """
    home_env = Path.home() / ".argus" / ".env"
    if home_env.exists():
        load_dotenv(home_env, override=True)
    load_dotenv(override=True)  # project-local .env


_load_env()


@dataclass(frozen=True)
class Config:
    """All Argus configuration in one place."""

    # Claude API
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("ARGUS_MODEL", "claude-sonnet-4-20250514"))

    # Feedly
    feedly_token: str = field(default_factory=lambda: os.getenv("FEEDLY_TOKEN", ""))
    feedly_user_id: str = field(default_factory=lambda: os.getenv("FEEDLY_USER_ID", ""))
    feedly_streams: list[str] = field(
        default_factory=lambda: [
            s.strip()
            for s in os.getenv("FEEDLY_STREAMS", "").split(",")
            if s.strip()
        ]
    )

    # Slack
    slack_bot_token: str = field(default_factory=lambda: os.getenv("SLACK_BOT_TOKEN", ""))
    slack_channel: str = field(default_factory=lambda: os.getenv("SLACK_CHANNEL", "#argus-intel"))

    # WhatsApp (Twilio)
    twilio_account_sid: str = field(default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID", ""))
    twilio_auth_token: str = field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN", ""))
    twilio_whatsapp_from: str = field(
        default_factory=lambda: os.getenv("TWILIO_WHATSAPP_FROM", "")
    )
    whatsapp_to: str = field(default_factory=lambda: os.getenv("WHATSAPP_TO", ""))

    # Paths
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("ARGUS_DATA_DIR", str(Path.home() / ".argus" / "data"))
        ).expanduser()
    )
    log_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("ARGUS_LOG_DIR", str(Path.home() / ".argus" / "logs"))
        ).expanduser()
    )

    # RSS feeds (hardcoded defaults, extend via env)
    rss_feeds: list[str] = field(
        default_factory=lambda: [
            "https://feeds.feedburner.com/TheHackersNews",
            "https://github.com/advisories.atom",
            "https://owasp.org/feed.xml",
            "https://krebsonsecurity.com/feed/",
            "https://www.bleepingcomputer.com/feed/",
            "https://blog.trailofbits.com/feed/",
        ]
    )

    @property
    def has_feedly(self) -> bool:
        return bool(self.feedly_token and self.feedly_streams)

    @property
    def has_slack(self) -> bool:
        return bool(self.slack_bot_token)

    @property
    def has_whatsapp(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token)

    def ensure_dirs(self) -> None:
        """Create data and log directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "digests").mkdir(exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    """Load and return configuration."""
    cfg = Config()
    cfg.ensure_dirs()
    return cfg
