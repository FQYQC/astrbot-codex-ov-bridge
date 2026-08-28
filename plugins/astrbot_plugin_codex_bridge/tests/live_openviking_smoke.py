"""Verify real OpenViking writes and cross-user access isolation."""

from __future__ import annotations

import asyncio
import os
import tempfile
import urllib.parse
from pathlib import Path

from astrbot_plugin_codex_bridge.openviking_memory import (
    OpenVikingMemory,
    OpenVikingMemoryError,
    safe_identifier,
)


def load_private_environment(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value


async def main() -> None:
    load_private_environment(
        Path("/home/ubuntu/personal-ai/astrbot/secrets/codex-bridge.env")
    )
    private_tmp_root = Path("/home/ubuntu/personal-ai/astrbot/backups")
    with tempfile.TemporaryDirectory(dir=private_tmp_root) as temporary_dir:
        memory = OpenVikingMemory.from_environment(Path(temporary_dir))
        if memory is None:
            raise RuntimeError("OpenViking memory is not enabled")
        memory.timeout_seconds = 60
        sender_a = "openviking-isolation-smoke-a"
        sender_b = "openviking-isolation-smoke-b"
        user_a = safe_identifier("qq", sender_a)
        user_b = safe_identifier("qq", sender_b)
        session_a_raw = "openviking-smoke-session-a"
        session_b_raw = "openviking-smoke-session-b"
        cleanup_results: list[bool] = []
        try:
            _, key_a = await memory.user_key(sender_a)
            _, key_b = await memory.user_key(sender_b)
            await memory.remember(
                sender_a,
                session_a_raw,
                "我最喜欢的测试颜色是琥珀色。",
                "已记录测试偏好。",
            )
            await memory.remember(
                sender_b,
                session_b_raw,
                "我最喜欢的测试颜色是靛蓝色。",
                "已记录测试偏好。",
            )
            session_a = safe_identifier("session", session_a_raw)
            quoted_session_a = urllib.parse.quote(session_a, safe="")
            own_status, _ = await memory._request(
                f"/api/v1/sessions/{quoted_session_a}", key_a
            )
            cross_status, _ = await memory._request(
                f"/api/v1/sessions/{quoted_session_a}", key_b
            )
            recall_results = []
            for sender, session in (
                (sender_a, session_a_raw),
                (sender_b, session_b_raw),
            ):
                try:
                    await memory.recall(sender, session, "测试颜色偏好")
                    recall_results.append(True)
                except OpenVikingMemoryError:
                    recall_results.append(False)

            print(f"distinct_user_keys={str(key_a != key_b).lower()}")
            print(f"own_session_visible={str(own_status == 200).lower()}")
            print(f"cross_session_blocked={str(cross_status in {403, 404}).lower()}")
            print(f"recall_a_ok={str(recall_results[0]).lower()}")
            print(f"recall_b_ok={str(recall_results[1]).lower()}")
        finally:
            quoted_account = urllib.parse.quote(memory.account_id, safe="")
            for user_id in (user_a, user_b):
                quoted_user = urllib.parse.quote(user_id, safe="")
                status, _ = await memory._request(
                    f"/api/v1/admin/accounts/{quoted_account}/users/{quoted_user}",
                    memory.admin_api_key,
                    method="DELETE",
                )
                cleanup_results.append(status in {200, 202, 204, 404})
            print(
                "test_users_cleanup_requested="
                + str(all(cleanup_results)).lower()
            )


if __name__ == "__main__":
    asyncio.run(main())
