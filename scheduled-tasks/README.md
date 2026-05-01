# Scheduled tasks

This directory contains version-controlled copies of the Claude Code Scheduled Task
definitions that run Argus automatically.

The live tasks live at `~/.claude/scheduled-tasks/<task-id>/SKILL.md` on each machine
where Argus runs. The copies here are for:

- **Reproducibility** — recreate the task on a new machine without retyping the prompt.
- **Diff & review** — see when and why the task prompt changed.
- **Pi/cloud parity** — port the same prompt to a Raspberry Pi or a Cloud Routine.

## Tasks

| Task | Cron | What it does |
|---|---|---|
| [`argus-scan`](argus-scan/SKILL.md) | `0 */4 * * *` (every 4 hours) | Fetch RSS, classify, persist, alert criticals to Slack |

## How to install on a new machine

The Scheduled Task system stores tasks via an MCP tool, not by reading files from this
directory. To install on a fresh machine, open Claude Code and ask it to create a
scheduled task using the prompt body from the SKILL.md you want, with the matching cron.

Example:

> Create a scheduled task named `argus-scan` with cron `0 */4 * * *` and the prompt body
> from `scheduled-tasks/argus-scan/SKILL.md` in this repo.

The harness writes the file to `~/.claude/scheduled-tasks/argus-scan/SKILL.md` and
schedules it.

## Editing the live task

You can edit `~/.claude/scheduled-tasks/<task-id>/SKILL.md` directly — changes take
effect on the next fire. After editing, copy your changes back into this directory and
commit, so they're version-controlled.
