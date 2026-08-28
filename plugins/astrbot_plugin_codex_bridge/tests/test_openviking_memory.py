from __future__ import annotations

import tempfile
import unittest
import urllib.parse
from pathlib import Path
from typing import Any

from astrbot_plugin_codex_bridge.openviking_memory import (
    OpenVikingMemory,
    safe_group_memory_text,
    safe_identifier,
    safe_memory_text,
)


class FakeOpenVikingMemory(OpenVikingMemory):
    def __init__(self, data_dir: Path) -> None:
        super().__init__(
            data_dir=data_dir,
            base_url="http://127.0.0.1:1933",
            account_id="test_account",
            admin_api_key="a" * 48,
        )
        self.provisioned: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.rejected_keys: set[str] = set()

    async def _request(  # type: ignore[override]
        self,
        path: str,
        api_key: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        actor_peer_id: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        self.calls.append((path, api_key, payload))
        if path.endswith("/users"):
            user_id = str((payload or {}).get("user_id", ""))
            if user_id in self.provisioned:
                return 409, {"error": {"code": "USER_EXISTS"}}
            user_key = "key_" + user_id + "_" + "x" * 32
            self.provisioned[user_id] = user_key
            return 200, {"result": {"user_key": user_key}}
        if path.endswith("/key") and "/admin/" in path:
            user_id = urllib.parse.unquote(path.rsplit("/", 2)[-2])
            user_key = "rotated_" + user_id + "_" + "y" * 32
            self.provisioned[user_id] = user_key
            return 200, {"result": {"user_key": user_key}}
        if api_key in self.rejected_keys:
            return 401, {"error": {"code": "UNAUTHENTICATED"}}
        if path.endswith("/search/search"):
            return 200, {"result": {"context": "isolated memory"}}
        if "/context?" in path:
            return 200, {
                "result": {
                    "messages": [
                        {
                            "role": "user",
                            "parts": [{"type": "text", "text": "Alice: 何意味"}],
                        },
                        {
                            "role": "assistant",
                            "parts": [{"type": "text", "text": "这是测试回复"}],
                        },
                    ]
                }
            }
        return 200, {"result": {}}


class OpenVikingMemoryTests(unittest.IsolatedAsyncioTestCase):
    def test_identifiers_hide_raw_values_and_are_stable(self) -> None:
        first = safe_identifier("qq", "123456")
        self.assertEqual(first, safe_identifier("qq", "123456"))
        self.assertNotIn("123456", first)

    def test_sensitive_turns_are_rejected(self) -> None:
        self.assertIsNone(safe_memory_text("Authorization: Bearer secret", 1000))
        self.assertIsNone(safe_memory_text("A" * 64, 1000))
        self.assertEqual(safe_memory_text("普通对话", 1000), "普通对话")
        self.assertIsNone(
            safe_group_memory_text("Alice", "Authorization: Bearer hidden")
        )
        self.assertEqual(
            safe_group_memory_text("123456789", "今晚八点开会"),
            "群成员: 今晚八点开会",
        )

    async def test_two_senders_receive_distinct_user_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            memory = FakeOpenVikingMemory(Path(temporary_dir))
            user_a, key_a = await memory.user_key("sender-a")
            user_b, key_b = await memory.user_key("sender-b")
            self.assertNotEqual(user_a, user_b)
            self.assertNotEqual(key_a, key_b)
            self.assertEqual((await memory.user_key("sender-a"))[1], key_a)
            self.assertEqual(len(memory.provisioned), 2)

    async def test_groups_are_shared_within_group_and_isolated_between_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            memory = FakeOpenVikingMemory(Path(temporary_dir))
            group_a, key_a = await memory.group_key("group-session-a")
            group_b, key_b = await memory.group_key("group-session-b")
            self.assertNotEqual(group_a, group_b)
            self.assertNotEqual(key_a, key_b)
            self.assertNotIn("group-session-a", group_a)
            self.assertEqual((await memory.group_key("group-session-a"))[1], key_a)

    async def test_group_recall_and_writes_use_group_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            memory = FakeOpenVikingMemory(Path(temporary_dir))
            context = await memory.recall_group("group-session", "会议时间")
            await memory.remember_group_message(
                "group-session", "Alice", "今晚八点开会"
            )
            await memory.remember_group_turn(
                "group-session", "Owner", "几点开会", "今晚八点"
            )
            self.assertEqual(context, "isolated memory")
            business_calls = [call for call in memory.calls if "/admin/" not in call[0]]
            self.assertTrue(business_calls)
            self.assertTrue(
                all(call[1] != memory.admin_api_key for call in business_calls)
            )
            contents = [
                str((payload or {}).get("content", ""))
                for _, _, payload in business_calls
            ]
            self.assertTrue(any("Alice: 今晚八点开会" in item for item in contents))

    async def test_group_raw_tail_preserves_exact_recent_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            memory = FakeOpenVikingMemory(Path(temporary_dir))
            context = await memory.recent_group_messages("group-session")
            self.assertIn("Alice: 何意味", context)
            self.assertIn("机器人: 这是测试回复", context)

    async def test_recall_and_remember_use_user_key_not_admin_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            memory = FakeOpenVikingMemory(Path(temporary_dir))
            context = await memory.recall("sender-a", "session-a", "question")
            await memory.remember("sender-a", "session-a", "question", "answer")
            self.assertEqual(context, "isolated memory")
            business_calls = [call for call in memory.calls if "/admin/" not in call[0]]
            self.assertTrue(business_calls)
            self.assertTrue(
                all(call[1] != memory.admin_api_key for call in business_calls)
            )

    async def test_rejected_group_key_is_rotated_and_retried_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            memory = FakeOpenVikingMemory(Path(temporary_dir))
            raw_group = "group-session"
            group_id = safe_identifier("group", raw_group)
            stale_key = "stale_" + "z" * 48
            await memory.keys.set(group_id, stale_key)
            memory.provisioned[group_id] = stale_key
            memory.rejected_keys.add(stale_key)

            context = await memory.recall_group(raw_group, "会议时间")
            _, refreshed_key = await memory.group_key(raw_group)

            self.assertEqual(context, "isolated memory")
            self.assertNotEqual(refreshed_key, stale_key)
            self.assertTrue(refreshed_key.startswith("rotated_"))
            business_keys = [
                key for path, key, _ in memory.calls if "/admin/" not in path
            ]
            self.assertIn(stale_key, business_keys)
            self.assertIn(refreshed_key, business_keys)


if __name__ == "__main__":
    unittest.main()
