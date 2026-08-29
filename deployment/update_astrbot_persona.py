#!/usr/bin/env python3
"""Safely update an existing AstrBot persona from a public JSON template."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def load_template(path: Path) -> tuple[str, str, list[str]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("persona template must be an object")
    persona_id = value.get("persona_id")
    prompt = value.get("system_prompt")
    dialogs = value.get("begin_dialogs", [])
    if not isinstance(persona_id, str) or not persona_id.strip():
        raise ValueError("persona_id is required")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("system_prompt is required")
    if len(prompt) > 16000:
        raise ValueError("system_prompt exceeds the Bridge limit")
    if not isinstance(dialogs, list) or any(
        not isinstance(item, str) or not item.strip() for item in dialogs
    ):
        raise ValueError("begin_dialogs must contain non-empty strings")
    if len(dialogs) % 2 != 0 or len(dialogs) > 12:
        raise ValueError("begin_dialogs must contain at most six complete pairs")
    if any(len(item) > 2000 for item in dialogs):
        raise ValueError("a preset dialog is too long")
    return persona_id.strip(), prompt.strip(), dialogs


def back_up_database(database: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"data_v4.before-persona-{timestamp}.db"
    descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    source = sqlite3.connect(database)
    destination = sqlite3.connect(backup)
    try:
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError("persona backup integrity check failed")
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    finally:
        destination.close()
        source.close()
    os.chmod(backup, 0o600)
    return backup


def update_persona(
    database: Path, persona_id: str, prompt: str, dialogs: list[str]
) -> None:
    connection = sqlite3.connect(database, timeout=30)
    try:
        with connection:
            cursor = connection.execute(
                "UPDATE personas SET system_prompt = ?, begin_dialogs = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE persona_id = ?",
                (prompt, json.dumps(dialogs, ensure_ascii=False), persona_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("exactly one existing persona must match")
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--persona-file", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    persona_id, prompt, dialogs = load_template(args.persona_file)
    if args.validate_only:
        print("persona_template_valid=true")
        print(f"persona_example_pairs={len(dialogs) // 2}")
        return
    if not args.database.is_file():
        raise FileNotFoundError("AstrBot database is unavailable")
    back_up_database(args.database, args.backup_dir)
    update_persona(args.database, persona_id, prompt, dialogs)
    print("persona_backup_created=true")
    print("persona_updated=true")
    print(f"persona_example_pairs={len(dialogs) // 2}")


if __name__ == "__main__":
    main()
