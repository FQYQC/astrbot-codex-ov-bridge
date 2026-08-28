#!/usr/bin/env python3
"""Provision a scoped OpenViking account for AstrBot without printing keys."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ACCOUNT_ID = "astrbot_codex_bridge"
ADMIN_USER_ID = "bridge_admin"


def request_json(
    url: str,
    api_key: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            parsed = json.loads(response.read().decode("utf-8"))
            return response.status, parsed if isinstance(parsed, dict) else {}
    except urllib.error.HTTPError as exc:
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = {}
        return exc.code, parsed if isinstance(parsed, dict) else {}


def existing_admin_key(env_file: Path) -> str | None:
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENVIKING_ADMIN_API_KEY="):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


def write_env(path: Path, admin_key: str, owner_uid: int, owner_gid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    os.chown(path.parent, owner_uid, owner_gid)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        payload = (
            "OPENVIKING_ENABLED=1\n"
            "OPENVIKING_URL=http://127.0.0.1:1933\n"
            f"OPENVIKING_ACCOUNT_ID={ACCOUNT_ID}\n"
            f"OPENVIKING_ADMIN_API_KEY={admin_key}\n"
        )
        os.write(fd, payload.encode("utf-8"))
        os.fchmod(fd, 0o600)
        os.fchown(fd, owner_uid, owner_gid)
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ov-config", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--owner-uid", type=int, default=1000)
    parser.add_argument("--owner-gid", type=int, default=1000)
    parser.add_argument("--rotate-existing", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.ov_config.read_text(encoding="utf-8-sig"))
    root_key = str(config.get("server", {}).get("root_api_key", "")).strip()
    if len(root_key) < 32:
        raise SystemExit("OpenViking root key is unavailable")

    base_url = "http://127.0.0.1:1933"
    current_key = existing_admin_key(args.env_file)
    if current_key:
        status, _ = request_json(
            f"{base_url}/api/v1/admin/accounts/{ACCOUNT_ID}/users", current_key
        )
        if status == 200:
            print("OpenViking Bridge scoped account is already provisioned")
            return

    status, response = request_json(
        f"{base_url}/api/v1/admin/accounts",
        root_key,
        method="POST",
        payload={"account_id": ACCOUNT_ID, "admin_user_id": ADMIN_USER_ID},
    )
    if status == 200:
        admin_key = str(response.get("result", {}).get("user_key", "")).strip()
    elif status in {400, 409} and args.rotate_existing:
        status, response = request_json(
            f"{base_url}/api/v1/admin/accounts/{ACCOUNT_ID}/users/{ADMIN_USER_ID}/key",
            root_key,
            method="POST",
            payload={},
        )
        admin_key = str(response.get("result", {}).get("user_key", "")).strip()
    elif status in {400, 409}:
        raise SystemExit(
            "Bridge account already exists but no valid local key was found; "
            "rerun with --rotate-existing only after checking other deployments"
        )
    else:
        raise SystemExit(f"OpenViking account provisioning failed with HTTP {status}")

    if status != 200 or len(admin_key) < 32:
        raise SystemExit("OpenViking did not return a valid scoped admin key")
    write_env(args.env_file, admin_key, args.owner_uid, args.owner_gid)
    print("Provisioned scoped OpenViking account and private environment file")


if __name__ == "__main__":
    main()
