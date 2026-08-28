# Repository contents

This repository contains only reproducible deployment and bridge source code for
the self-hosted QQ assistant. Runtime state and credentials are intentionally
kept outside Git.

## Included

- `plugins/astrbot_plugin_codex_bridge/`
  - OneBot-only AstrBot plugin that invokes the local Codex CLI.
  - Persistent per-session Codex thread, model, and reasoning-effort selection.
  - QQ file staging with size limits and public-network-only downloads.
  - Isolated OpenViking private-user and per-group memory integration.
  - Owner-only management commands, group mention policy, bounded concurrency,
    progress notifications, output splitting, and privacy filters.
  - Unit and privacy-preserving live smoke tests.
- `deployment/`
  - AstrBot installation through uv and a dedicated Python 3.12 runtime.
  - systemd service definition and installation flow.
  - NapCat and AstrBot OneBot v11 configuration helpers.
  - OpenViking scoped-account provisioning without printing credentials.
  - Deployment verification and repository secret scanning.
- `napcat/compose.yaml`
  - Digest-pinned NapCat container definition with localhost-only WebUI.
- `versions.lock`
  - Tested and pinned component versions.

## Excluded

The following are ignored and must never be pushed to GitHub:

- AstrBot configuration, databases, logs, backups, plugin state, and secrets.
- NapCat configuration, QQ login data, tokens, logs, and runtime plugins.
- OpenViking configuration, content, vector database, model data, and auth files.
- Codex/ChatGPT authentication files and OAuth material.
- QQ attachment staging files and the Codex agent workspace.

These items require a separate encrypted backup and restore workflow. See
[`BACKUP_TODO.md`](BACKUP_TODO.md).
