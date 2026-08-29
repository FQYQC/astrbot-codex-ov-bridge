# Project operating instructions

This repository deploys the user's private QQ assistant. Before changing or
diagnosing anything, read `docs/DEPLOYMENT_STATE.md`, then `README.md`, and
compare those records with current read-only service checks. Runtime state is
authoritative when it differs from the dated status document.

## Non-negotiable boundaries

- Keep the architecture NapCat/OneBot v11 -> AstrBot -> local Codex CLI ->
  OpenViking. Do not introduce VikingBot, an OpenAI-compatible AstrBot
  provider, an extra OpenAI API key, or Claude Code login.
- Invoke Codex through `/home/ubuntu/.local/bin/codex`; the service environment
  cannot rely on a login-shell `PATH`.
- Never print, copy, back up to Git, or commit OAuth material, `auth.json`, QQ
  login data, cookies, OneBot tokens, OpenViking keys, root keys, raw QQ IDs, or
  private chat transcripts.
- Preserve all existing OpenViking configuration and data. Back up any runtime
  configuration before editing it, with mode `0600`, under an ignored runtime
  backup directory.
- Keep AstrBot and NapCat WebUIs localhost-only and keep OneBot off the public
  network. Codex must remain sandboxed with `workspace-write`; never use yolo,
  `danger-full-access`, or bypass approvals/sandboxing.
- Runtime configuration, databases, logs, attachments, tokens, and login state
  stay outside Git. Only reproducible source, public-safe documentation, and
  secret-free examples belong in the repository.

## Working and handoff practice

- Operate and verify the VPS directly. Do not hand the user commands to run
  unless a QR login, secret entry, or material product choice requires them.
- Preserve unrelated user changes. Use `apply_patch` for source edits.
- Run `./deployment/verify.sh` after relevant changes. Run the privacy-safe live
  smoke tests when Codex/OpenViking integration behavior or tested versions
  change.
- Run `python3 deployment/check_repo_secrets.py` after staging and before every
  commit. Never stage ignored runtime backups to make a test pass.
- Update `docs/DEPLOYMENT_STATE.md` whenever deployed behavior, pinned/tested
  versions, verification evidence, or remaining operational gaps change. Keep
  it factual, dated, concise, and free of credentials or personal identifiers.
- Commit self-authored code with a clear local commit and push to `origin/main`
  after tests pass, unless the user explicitly asks otherwise.
