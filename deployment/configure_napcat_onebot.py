#!/usr/bin/env python3
"""Configure the logged-in NapCat account as an OneBot reverse WS client."""

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
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--url", default="ws://172.30.0.1:6199/ws")
    args = parser.parse_args()

    account_configs = sorted(args.config_dir.glob("onebot11_*.json"))
    if len(account_configs) != 1:
        raise SystemExit(
            f"Expected exactly one logged-in account config, found {len(account_configs)}"
        )
    config_path = account_configs[0]
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise SystemExit("OneBot token is missing or too short")

    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    network = config.setdefault("network", {})
    clients = network.setdefault("websocketClients", [])
    if not isinstance(clients, list):
        raise SystemExit("NapCat websocketClients configuration is not a list")

    client = {
        "name": "astrbot-codex",
        "enable": True,
        "url": args.url,
        "messagePostFormat": "array",
        "reportSelfMessage": False,
        "reconnectInterval": 5000,
        "token": token,
        "debug": False,
        "heartInterval": 30000,
        "verifyCertificate": True,
    }
    for index, current in enumerate(clients):
        if isinstance(current, dict) and current.get("name") == client["name"]:
            clients[index] = client
            break
    else:
        clients.append(client)

    args.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(config_path, args.backup_dir / f"onebot11.before-bridge.{stamp}.json")

    payload = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".onebot11.", dir=config_path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, config_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    print("Configured one logged-in NapCat account with one reverse WS client")


if __name__ == "__main__":
    main()
