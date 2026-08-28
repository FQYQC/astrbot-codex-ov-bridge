#!/usr/bin/env python3
"""Configure AstrBot's OneBot reverse WebSocket without exposing its token."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--host", default="172.30.0.1")
    parser.add_argument("--port", type=int, default=6199)
    args = parser.parse_args()

    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise SystemExit("OneBot token is missing or too short")

    raw = args.config.read_text(encoding="utf-8-sig")
    config = json.loads(raw)
    platforms = config.setdefault("platform", [])
    if not isinstance(platforms, list):
        raise SystemExit("AstrBot platform configuration is not a list")

    entry = {
        "id": "codex_qq",
        "type": "aiocqhttp",
        "enable": True,
        "ws_reverse_host": args.host,
        "ws_reverse_port": args.port,
        "ws_reverse_token": token,
    }
    for index, current in enumerate(platforms):
        if isinstance(current, dict) and current.get("id") == entry["id"]:
            platforms[index] = entry
            break
    else:
        platforms.append(entry)

    args.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(args.config, args.backup_dir / f"cmd_config.json.before-onebot.{stamp}")

    payload = "\ufeff" + json.dumps(config, ensure_ascii=False, indent=4) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".cmd_config.", dir=args.config.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, args.config)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    print(f"Configured OneBot reverse WebSocket on {args.host}:{args.port}")


if __name__ == "__main__":
    main()
