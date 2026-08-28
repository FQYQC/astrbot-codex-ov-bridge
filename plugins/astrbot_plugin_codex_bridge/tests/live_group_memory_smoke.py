"""Verify real shared-per-group OpenViking memory and cross-group isolation."""

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
        group_a_raw = "openviking-group-smoke-a"
        group_b_raw = "openviking-group-smoke-b"
        group_a = safe_identifier("group", group_a_raw)
        group_b = safe_identifier("group", group_b_raw)
        cleanup_results: list[bool] = []
        try:
            _, key_a = await memory.group_key(group_a_raw)
            _, key_b = await memory.group_key(group_b_raw)
            await memory.remember_group_message(
                group_a_raw, "测试成员甲", "群测试会议在二十一点开始。"
            )
            await memory.remember_group_turn(
                group_a_raw,
                "测试成员乙",
                "群测试会议几点开始？",
                "二十一点开始。",
            )
            session_a = safe_identifier("group_session", group_a_raw)
            quoted_session_a = urllib.parse.quote(session_a, safe="")
            own_status, _ = await memory._request(
                f"/api/v1/sessions/{quoted_session_a}", key_a
            )
            cross_status, _ = await memory._request(
                f"/api/v1/sessions/{quoted_session_a}", key_b
            )
            recall_ok = True
            try:
                await memory.recall_group(group_a_raw, "测试会议时间")
            except OpenVikingMemoryError:
                recall_ok = False
            raw_tail = await memory.recent_group_messages(group_a_raw)
            print(f"distinct_group_keys={str(key_a != key_b).lower()}")
            print(f"own_group_session_visible={str(own_status == 200).lower()}")
            print(
                "cross_group_session_blocked="
                + str(cross_status in {403, 404}).lower()
            )
            print(f"group_recall_ok={str(recall_ok).lower()}")
            print(
                "group_raw_tail_ok="
                + str("群测试会议" in raw_tail).lower()
            )
        finally:
            quoted_account = urllib.parse.quote(memory.account_id, safe="")
            for group_id in (group_a, group_b):
                quoted_group = urllib.parse.quote(group_id, safe="")
                status, _ = await memory._request(
                    f"/api/v1/admin/accounts/{quoted_account}/users/{quoted_group}",
                    memory.admin_api_key,
                    method="DELETE",
                )
                cleanup_results.append(status in {200, 202, 204, 404})
            print(
                "test_groups_cleanup_requested="
                + str(all(cleanup_results)).lower()
            )


if __name__ == "__main__":
    asyncio.run(main())
