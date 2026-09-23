# Deployment state and handoff

Last verified: 2026-08-29 UTC

This is the public-safe continuity record for new Codex sessions and server
migrations. It deliberately excludes IP addresses, QQ identifiers, credentials,
tokens, message bodies, database contents, and login state. Current runtime
checks take precedence over this dated snapshot.

## Objective and architecture

The deployed path is:

```text
ordinary QQ account
  -> NapCatQQ
  -> OneBot v11 reverse WebSocket
  -> AstrBot
  -> astrbot_plugin_codex_bridge
  -> local Codex CLI using ChatGPT subscription login
  -> OpenViking long-term memory
```

VikingBot, an AstrBot OpenAI-compatible provider, extra OpenAI API keys, and
Claude Code login are intentionally out of scope.

## Verified deployment snapshot

| Component | Deployed/tested state |
| --- | --- |
| Host | Ubuntu 26.04 x86_64, 2 vCPU, about 4 GiB RAM, 2 GiB swap |
| AstrBot | 4.27.4, uv-managed Python 3.12.14, systemd active and enabled |
| Codex CLI | 0.151.0, ChatGPT login valid, absolute binary path required |
| Codex Bridge | 0.9.0, loaded from the repository through the AstrBot plugin symlink |
| NapCat | Digest-pinned image from `versions.lock`, running with `unless-stopped` |
| OpenViking | 0.4.16, healthy, existing data preserved |
| Ollama | Running with `unless-stopped`; embedding workload remains local |

Network checks on 2026-08-29:

- AstrBot WebUI listens only on `127.0.0.1:6185`.
- NapCat WebUI listens only on `127.0.0.1:6099`.
- OneBot listens only on the Docker bridge gateway at port 6199.
- Public non-SSH TCP listener count is zero.
- UFW is currently inactive. Exposure is constrained by loopback/Docker-bridge
  binds and the assertion in `deployment/verify.sh`; enabling a host firewall
  remains a separate defense-in-depth decision.

Resource snapshot after normal idle operation:

- Memory used: about 1.6 GiB; available: about 2.1 GiB.
- Swap used: about 649 MiB of 2 GiB.
- OpenViking, Ollama, and NapCat were below their configured container memory
  limits; no sustained OOM condition was observed.

All Bridge JSON state, the Bridge environment file, and the OneBot token were
verified as mode `0600`. A real host reboot on 2026-08-28 was followed by all
three Docker containers running under `unless-stopped`; AstrBot remains enabled
for boot and active.

## Delivered Bridge behavior

- Only OneBot/QQ events are handled; AstrBot's default LLM path is blocked for
  handled messages to prevent duplicate replies.
- Each QQ private chat or group maps to an independent persistent Codex thread.
  Calls use JSONL `codex exec`/`codex exec resume`, `workspace-write`, and the
  dedicated agent workspace.
- The owner can choose Luna or Sol and reasoning effort per session, with
  persistent global defaults and owner-only modification commands.
- The owner can select AstrBot-native personas per QQ session. Persona prompts
  are injected as a separate trusted instruction block without enabling an
  AstrBot LLM provider. AstrBot's alternating preset dialogs are injected as
  explicitly fictional style examples, not as real history. Switching persona
  currently starts a fresh Codex thread; OpenViking memory is retained.
- Same-session messages are serialized. Up to two main QQ sessions run at once.
  Private medium-or-higher effort tasks receive detailed 120-second progress
  summaries from two separate ephemeral Luna/low read-only slots.
- The current main-task timeout is 2400 seconds. Timeout terminates the Codex
  process; it does not leave the task running silently in the background.
- QQ file inputs are staged under private randomized paths with per-file, count,
  aggregate-size, network-source, and retention limits.
- Group responses require an explicit bot mention. Enabled groups collect
  compliant ordinary text into a 100-message/24-hour recent buffer and isolated
  per-group OpenViking memory, including messages that do not mention the bot.
- Private users and groups receive separate OpenViking scoped credentials and
  hashed identifiers. A rejected scoped key is rotated under a cross-instance
  file lock and retried once. Credential-like content is rejected from memory.
- OpenViking write failures never block the QQ response.

## Verification ledger

2026-08-29:

- Deployed Bridge 0.9.0 and the public-safe `fywy` persona template. AstrBot
  loaded its prompt plus six alternating preset-dialog pairs; a real Luna call
  confirmed both blocks were injected, produced a non-empty response, and did
  not echo the persona prompt. The previous runtime persona database was backed
  up consistently with mode `0600` before the update.
- The `fywy` template prioritizes casual QQ conversation over audit-style
  hedging. A live Luna smoke with wholly fictional group context recognized the
  implied relationship, avoided the configured conservative boilerplate and
  unsolicited “旅行者”, and stayed within the short-chat limit.
- `./deployment/verify.sh`: all service, login, listener, exposure, health, and
  resource checks passed; 49 unit tests passed. The script now exits nonzero on
  critical service, version, restart-policy, listener, link, or file-mode drift.
- Real simulated OneBot private event: first Codex turn passed, resume passed,
  thread persisted, default AstrBot LLM stayed blocked, and both events stopped.
- Codex CLI 0.151.0 was therefore accepted as the current tested version.
- A separate ephemeral, Luna/low, read-only Codex run loaded the root
  `AGENTS.md`, followed its handoff instruction, and found this state document.

2026-08-28:

- Real OpenViking private-user and group isolation smokes passed, including
  cross-principal denial and test-principal cleanup.
- A stale real group scoped key was repaired without deleting the group memory;
  retained group text was read back and confirmed visible to a real Codex call.
- The user's existing AstrBot persona was read through AstrBot's native persona
  manager and passed a real privacy-safe Codex injection smoke.
- Detailed progress/TODO extraction, separate summary concurrency, same-session
  queueing, different-session isolation, first-session creation, and resume were
  covered by automated or live tests.

## Source landmarks

- `64c657b`: base AstrBot/NapCat/Codex/OpenViking deployment.
- `61bf2c8`: owner-only per-session Luna/Sol selection.
- `ee60090`: isolated persistent group memory.
- `ffba77a`: file input, effort controls, and durable group context.
- `e040f56`: detailed Luna progress summaries for long tasks.
- `d51a7a9`: group-memory scoped-key repair and AstrBot persona integration.

Use `git log --oneline origin/main` for commits after this document's last
verification date.

## Remaining operational work

- Implement and test an encrypted OpenViking data/config backup and restore
  procedure. The detailed private backup plan remains in an ignored runtime
  backup file and must not be committed.
- Add an optional, deduplicated NapCat history backfill path if messages from
  before Bridge collection or during an outage must be imported. Live ordinary
  group-message collection is already working.
- Perform a real QQ attachment round trip when a suitable non-sensitive test
  file is available; simulated/unit coverage is already present.

These are operational gaps, not reasons to expose credentials or copy runtime
databases into this repository.
