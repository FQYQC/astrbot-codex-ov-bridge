from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from astrbot_plugin_codex_bridge.openviking_memory import (
    OpenVikingMemory,
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
            user_key = "key_" + user_id + "_" + "x" * 32
            self.provisioned[user_id] = user_key
            return 200, {"result": {"user_key": user_key}}
        if path.endswith("/search/search"):
            return 200, {"result": {"context": "isolated memory"}}
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

    async def test_two_senders_receive_distinct_user_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            memory = FakeOpenVikingMemory(Path(temporary_dir))
            user_a, key_a = await memory.user_key("sender-a")
            user_b, key_b = await memory.user_key("sender-b")
            self.assertNotEqual(user_a, user_b)
            self.assertNotEqual(key_a, key_b)
            self.assertEqual((await memory.user_key("sender-a"))[1], key_a)
            self.assertEqual(len(memory.provisioned), 2)

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


if __name__ == "__main__":
    unittest.main()
