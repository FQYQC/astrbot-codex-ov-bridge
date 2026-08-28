# Backup TODO

Status: planned, not yet scheduled. The VPS currently has no automatic remote
backup, so a local disk or VPS loss can still destroy runtime state.

## OpenViking logical backup

- [ ] Add a root-owned backup script that temporarily stops AstrBot writes,
  waits for OpenViking background work to settle, and calls the official
  `/api/v1/pack/backup` endpoint.
- [ ] Export without dense vectors. OpenViking 0.4.16 produced a valid OVPack
  containing session paths in the live probe, while `include_vectors=true` was
  rejected by the current index consistency check. Restore with vector
  recomputation through the configured Ollama embedding model.
- [ ] Validate the archive before publishing it: ZIP integrity, non-zero file
  count, expected session paths, SHA-256 manifest, and restrictive permissions.
- [ ] Never print command headers, account identifiers, API keys, archive
  contents, message paths, or message text in logs.

## Encrypted disaster-recovery backup

- [ ] Select a remote Restic repository: Backblaze B2, private S3-compatible
  storage, or a separately administered server.
- [ ] Store Restic repository credentials in a root-readable `0600` environment
  file outside this Git repository.
- [ ] Add a weekly cold-backup job that stops AstrBot and OpenViking before
  capturing the local OpenViking datastore and the matching AstrBot Bridge
  runtime state.
- [ ] Explicitly exclude every `auth.json`, `codex_auth.json`, auth lock, QQ
  login directory, transient PID, staging file, and service log.
- [ ] Encrypt all retained runtime configuration because OpenViking account
  metadata and Bridge user-key mappings are sensitive even without auth files.
- [ ] Restart services and verify health automatically after every backup,
  including on backup failure.

## Retention and restore verification

- [ ] Suggested retention: 7 daily, 5 weekly, and 6 monthly snapshots.
- [ ] Run `restic check` on a schedule and record only boolean/status summaries.
- [ ] Perform a restore drill into an isolated temporary OpenViking instance.
- [ ] Verify private-user isolation, group isolation, exact recent session tail,
  semantic recall after vector recomputation, and Bridge key reprovisioning.
- [ ] Document recovery order without copying credentials into the repository:
  OpenViking content, scoped account reprovisioning, Bridge state, then AstrBot.

## Required user decision

Choose the remote backup destination and provide its credential through an
interactive/private channel. No remote backup implementation should be enabled
until this destination is selected.
