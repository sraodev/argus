# 👁️ ARGUS — AI Risk Gathering & Urgent Signaling 

**AI Security Threat Intelligence Agent for Guard0** — an automated pipeline that scans
the AI/ML security landscape, classifies threats with persona-based insights, and delivers
prioritized alerts to Slack (and optionally WhatsApp).

Argus runs in two modes:

1. **Scheduled Task mode** (recommended) — uses your Claude Max subscription via Claude
   Code Scheduled Tasks. Zero API credit cost. Runs every 4 hours automatically.
2. **CLI mode** — standalone Python CLI calling the Anthropic API directly. Useful for
   ad-hoc runs, headless deployments (Pi, server), or pipelines outside Claude Code.

---

## Why Argus

The AI security space generates more news than any team can triage manually. Most of it
is noise; the rest is critical and time-sensitive. Argus exists to:

- **Read continuously** — 13 RSS feeds plus optional Feedly category and Claude web search.
- **Classify with judgment** — every relevant article gets a category, criticality,
  CISO TL;DR, engineer action, and a note on relevance to Guard0 customers.
- **Alert on what matters** — critical items go to Slack within minutes; the rest land
  in a daily digest and a weekly executive brief.
- **Stay cheap and portable** — Mac → Pi → cloud, the same code works everywhere.

---

## Architecture

```
                ┌───────────────────────────────────────────────┐
                │              SOURCES (parallel)               │
                │  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
                │  │ Feedly   │  │ 13 RSS   │  │ Claude       │ │
                │  │ category │  │ feeds    │  │ web_search   │ │
                │  └─────┬────┘  └─────┬────┘  └──────┬───────┘ │
                └────────┼─────────────┼──────────────┼─────────┘
                         └─────────────┼──────────────┘
                                       ▼
                         ┌─────────────────────────┐
                         │   Dedup vs seen_urls    │
                         └────────────┬────────────┘
                                      ▼
                         ┌─────────────────────────┐
                         │  Pre-filter (keywords)  │ ← skip / fast / needs-llm
                         └────────────┬────────────┘
                                      ▼
                         ┌─────────────────────────┐
                         │  Claude classification  │ ← criticality, CISO TL;DR,
                         │     (batch of 10)       │   engineer action, tags
                         └────────────┬────────────┘
                                      ▼
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
   ┌─────────────────────┐                        ┌─────────────────────┐
   │  CRITICAL pathway   │                        │   Persistence       │
   │  ── Slack alert     │                        │  ── today_articles  │
   │  ── WhatsApp ping   │                        │  ── seen_urls       │
   │  (immediate)        │                        │  ── scans/<ts>.json │
   └─────────────────────┘                        └─────────────────────┘
                                                              │
                                                              ▼
                                             ┌────────────────────────────┐
                                             │ Daily digest (8am cron)    │
                                             │  ── Slack (full Block Kit) │
                                             │  ── WhatsApp (top 3)       │
                                             │  ── archive digest         │
                                             └────────────────────────────┘
```

### State on disk

```
~/.argus/
├── .env                        # secrets — gitignored, never in repo
└── data/
    ├── seen_urls.json          # dedup cache (max 5000 URLs, auto-trimmed)
    ├── today_articles.json     # accumulator, cleared after daily digest
    ├── scans/<timestamp>.json  # per-scan audit trail
    └── digests/<date>.json     # archived daily/weekly digests
```

All Argus state is local. No cloud database, no shared storage. Portable to any machine.

### Domain model

| Type | Purpose |
|---|---|
| `Article` | Raw article from any source: url, title, summary, source, published_at, fetched_from |
| `Classification` | LLM output: relevant, category, criticality, ai_specific, tags, ciso_tldr, engineer_action, one_line_summary, guard0_relevance |
| `ClassifiedArticle` | Article + Classification + classified_at |
| `Digest` | date + articles + stats (counts) + optional weekly_summary |

Categories: `vulnerability` · `attack` · `regulation` · `tool` · `research` · `incident` · `advisory`
Criticality: `critical` · `high` · `medium` · `low` · `informational`

### Persona-based insights

Every relevant article is annotated for two audiences:

- **CISO TL;DR** — one-sentence board-level risk framing. ("Board-level risk: a core ML
  training library used across the data science stack was actively backdoored.")
- **Engineer action** — one-sentence concrete next step. ("Pin pytorch-lightning to a
  known-good version, scan recent CI runs, rotate exposed tokens.")

This makes the digest actionable for both audiences in the same message.

---

## Setup

### Prerequisites

- macOS, Linux, or Raspberry Pi
- Python ≥ 3.11
- A Slack workspace (optional, but Argus is much more useful with it)
- One of:
  - Claude Max subscription → run via Scheduled Tasks (no API cost)
  - Anthropic API credits → run via the CLI

### 1. Clone and install

```bash
git clone https://github.com/sraodev/argus.git
cd argus
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 2. Configure secrets

```bash
mkdir -p ~/.argus
cp .env.example ~/.argus/.env
$EDITOR ~/.argus/.env
```

Minimum to run a scan:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...     # only needed for CLI mode (skip for Scheduled Tasks)
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL=#argus-intel
```

Optional:

```dotenv
FEEDLY_TOKEN=...                 # https://feedly.com/v3/auth/dev
FEEDLY_USER_ID=<uuid>
FEEDLY_STREAMS=user/<uuid>/category/<uuid>
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
```

### 3. Verify

```bash
argus status
```

You should see ✓ for each configured service.

---

## Usage

### CLI commands

| Command | What it does |
|---|---|
| `argus scan` | Fetch → dedup → classify → alert criticals → persist. Default: last 4 hours. |
| `argus scan --dry-run` | Same fetch+classify pipeline, prints a table, no Slack/storage writes. |
| `argus scan --sources rss` | Restrict to a subset: any of `feedly`, `rss`, `web` comma-separated. |
| `argus scan --hours 24` | Wider time window for first runs or after downtime. |
| `argus digest` | Roll up `today_articles.json` into a digest, deliver, archive, clear. |
| `argus digest --weekly` | Last 7 days of archived digests + Claude-written executive summary. |
| `argus digest --dry-run` | Print digest without sending. |
| `argus query "<keyword>"` | Search recent articles by keyword across last 7 days. |
| `argus setup` | Show which services are configured and which are missing. |
| `argus status` | Counts of seen URLs, today's articles, archived digests + service health. |
| `argus -v <command>` | Add `-v` for debug logging. |

### Typical day

```bash
argus scan                       # critical alerts pop into Slack as they're found
argus scan                       # … repeat through the day
argus digest                     # end-of-day roll-up message + archive
```

### Live test (no Slack/storage side effects)

```bash
argus scan --sources rss --hours 24 --dry-run
```

---

## Slack integration

### App setup (one-time)

1. https://api.slack.com/apps → **Create New App** → **From scratch** → name `Argus`
2. **OAuth & Permissions** → add Bot Token Scopes: `chat:write` and `chat:write.public`
3. **Install to Workspace** → copy the **Bot User OAuth Token** (`xoxb-...`)
4. Create a channel (e.g. `#argus-intel`); for private channels, run `/invite @Argus` inside
5. Add to `~/.argus/.env`:
   ```dotenv
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_CHANNEL=#argus-intel
   ```

### Message format

**Critical alert** (one per critical item, immediately):

```
🚨 ARGUS CRITICAL ALERT
*<title>*
<one_line_summary>

🎯 CISO TL;DR: Board-level risk: <executive framing>
🔧 Engineer action: <concrete next step>
🏢 Guard0 relevance: <why this matters for AI-first enterprises>

🏷️ <tags> | 📁 <category> | 📰 <source>
🔗 <Read more>
```

**Daily digest** (one per day, grouped by criticality):

```
👁️ Argus Daily Intel — 2026-05-01
📊 3 Critical | 2 High | 5 Medium | 3 Low | 1 Info  (total 14)

🚨 CRITICAL (3)
• <title> — <summary>
  🔗 <link>
…
⚠️ HIGH (2)
…
```

---

## WhatsApp integration (optional)

Uses Twilio. Free sandbox works for testing; production needs a verified sender number.

1. Sign up at https://www.twilio.com → activate the WhatsApp sandbox
2. From your phone, send `join <sandbox-phrase>` to the Twilio sandbox number
3. Add to `~/.argus/.env`:
   ```dotenv
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
   WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
   ```

WhatsApp messages are intentionally short — full digest goes to Slack.

---

## Feedly integration (optional)

Adds your curated Feedly category as a source.

1. https://feedly.com/v3/auth/dev → click **"Get my access token"**
2. Note your user ID (shown above the token) and your category UUIDs (visible in Feedly URL bar)
3. Add to `~/.argus/.env`:
   ```dotenv
   FEEDLY_TOKEN=<long-token>
   FEEDLY_USER_ID=<uuid>
   FEEDLY_STREAMS=user/<uuid>/category/<uuid>,user/<uuid>/category/<uuid>
   ```

**Caveats:** the dev token is rate-limited to 250 requests/day and expires every ~30 days.
For long-term unattended use, register an OAuth app in the Feedly Developer Console.

---

## Scheduling — four upgrade paths

Argus is designed to run automatically. Pick the path that matches your setup.

### Stage 1 — Claude Code Scheduled Tasks (Mac, recommended for Max users)

Uses your Claude Max subscription. **Zero API credit cost.** Runs only while Claude
Desktop is open.

The task lives at `~/.claude/scheduled-tasks/argus-scan/SKILL.md` — a real Markdown
file you can version control. A copy is checked in at
[`scheduled-tasks/argus-scan/SKILL.md`](scheduled-tasks/argus-scan/SKILL.md) for
reproducibility.

To install:

```bash
# Inside Claude Code, ask it to create a scheduled task with the contents of
# scheduled-tasks/argus-scan/SKILL.md and cron "0 */4 * * *"
```

The task fires every 4 hours, fetches RSS, classifies in-conversation (free, uses Max),
persists to `~/.argus/data/`, and posts to Slack.

### Stage 2 — Cloud Routines (24/7, recommended once Argus is proven)

Runs on Anthropic's infrastructure on a real cron, no Mac required. Same SKILL.md
format. Visit https://claude.ai/code/routines to set up. Cost: per-run API time
(small).

### Stage 3 — Raspberry Pi (headless, always on)

```bash
# On the Pi
git clone https://github.com/sraodev/argus.git
cd argus && python3 -m venv .venv && source .venv/bin/activate && pip install -e .
scp local-mac:~/.argus/.env ~/.argus/.env

# Add a systemd timer (every 4 hours)
sudo tee /etc/systemd/system/argus-scan.service > /dev/null <<EOF
[Unit]
Description=Argus AI security scan
[Service]
Type=oneshot
User=pi
WorkingDirectory=/home/pi/argus
ExecStart=/home/pi/argus/.venv/bin/argus scan
EOF

sudo tee /etc/systemd/system/argus-scan.timer > /dev/null <<EOF
[Unit]
Description=Run Argus scan every 4 hours
[Timer]
OnCalendar=*-*-* 00/4:00:00
Persistent=true
[Install]
WantedBy=timers.target
EOF

sudo systemctl enable --now argus-scan.timer
```

### Stage 4 — Productize as a Python agent (cloud-deployable)

The `src/argus/` package is already structured as a deployable agent. Wrap with FastAPI
or Cloud Run, swap local JSON storage for a managed KV (Cloudflare R2, Supabase, Turso),
and you have a multi-tenant version.

---

## Cost

| Mode | Cost | Notes |
|---|---|---|
| Scheduled Tasks (Max plan) | $0/month extra | Subscription you already pay for. |
| CLI with Anthropic API | ~$5–15/month | Sonnet at 6 scans/day, ~50 articles each. |
| Slack | $0 | Free workspace tier. |
| Twilio WhatsApp | ~$0.005/msg | Optional. |
| Feedly | $0 (dev token) | Or paid plan if you want OAuth/no expiry. |

---

## Development

```bash
pip install -e ".[dev]"
pytest -v                              # unit tests
ruff check src/                         # lint
mypy src/                               # type check
python -m argus scan --dry-run -v       # debug a scan
```

### Project layout

```
argus/
├── src/argus/
│   ├── cli.py                  # Click CLI: scan, digest, query, setup, status
│   ├── config.py               # ~/.argus/.env loader, typed Config dataclass
│   ├── models.py               # Pydantic: Article, Classification, Digest
│   ├── storage.py              # JSON file I/O, dedup, archives
│   ├── classifier.py           # Two-stage: keyword pre-filter → Claude batch
│   ├── sources/
│   │   ├── feedly.py           # Feedly v3 API
│   │   ├── rss.py              # feedparser, async-parallel
│   │   └── web.py              # Claude web_search tool
│   └── deliver/
│       ├── slack.py            # Block Kit formatter
│       └── whatsapp.py         # Twilio sender
├── scheduled-tasks/
│   └── argus-scan/SKILL.md     # version-controlled task definition
├── tests/
└── pyproject.toml
```

---

## Security & privacy

- Secrets live only in `~/.argus/.env` — gitignored and never logged.
- Article state stays local. Argus does not call out to any service besides the
  configured sources (Feedly/RSS/Claude/Slack/Twilio).
- Slack messages disable link unfurling so URLs aren't auto-fetched on display.
- The dev Feedly token expires; rotate before long unattended deployments.

---

## License

MIT. See `LICENSE`.

---

## Author

Built by [@sraodev](https://github.com/sraodev) for [Guard0](https://guard0.ai),
the AI Security Posture Management platform.
