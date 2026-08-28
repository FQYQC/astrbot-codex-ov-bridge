from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import astrbot.api.message_components as Comp
from astrbot.api.platform import MessageType
from astrbot.api.star import StarTools

from astrbot_plugin_codex_bridge.bridge_core import CodexResult
from astrbot_plugin_codex_bridge.group_context import GroupContextManager
from astrbot_plugin_codex_bridge.main import CodexBridgePlugin
from astrbot_plugin_codex_bridge.progress import ProgressTracker


class GroupEvent:
    def __init__(
        self,
        sender_id: str,
        sender_name: str,
        message: str,
        mentioned: bool,
    ) -> None:
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.message = message
        self.mentioned = mentioned
        self.call_llm = True
        self.stopped = False

    def should_call_llm(self, value: bool) -> None:
        self.call_llm = value

    def stop_event(self) -> None:
        self.stopped = True

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_sender_name(self) -> str:
        return self.sender_name

    def get_session_id(self) -> str:
        return "group-session"

    def get_message_str(self) -> str:
        return self.message

    def get_message_type(self) -> MessageType:
        return MessageType.GROUP_MESSAGE

    def get_self_id(self) -> str:
        return "bot-id"

    def get_messages(self) -> list[object]:
        components: list[object] = []
        if self.mentioned:
            components.append(Comp.At(qq="bot-id"))
        components.append(Comp.Plain(self.message))
        return components

    def plain_result(self, text: str) -> str:
        return text


class FakeService:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def ask(
        self,
        session_key: str,
        prompt: str,
        model: str | None = None,
        effort: str | None = None,
        progress_tracker: ProgressTracker | None = None,
    ) -> CodexResult:
        self.prompts.append(prompt)
        return CodexResult(thread_id="thread_group_12345678", text="answer")


class FakeGroupMemory:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []
        self.turns: list[tuple[str, str, str, str]] = []

    async def remember_group_message(
        self, session_key: str, sender_label: str, message: str
    ) -> None:
        self.messages.append((session_key, sender_label, message))

    async def remember_group_turn(
        self,
        session_key: str,
        sender_label: str,
        message: str,
        assistant: str,
    ) -> None:
        self.turns.append((session_key, sender_label, message, assistant))

    async def recall_group(self, session_key: str, query: str) -> str:
        return "群长期记忆：之前约定今晚八点开会"

    async def recent_group_messages(self, session_key: str) -> str:
        return "Alice: 何意味"

    async def recall(self, sender_id: str, session_key: str, query: str) -> str:
        raise AssertionError("group requests must not use per-user recall")


async def collect(plugin: CodexBridgePlugin, event: GroupEvent) -> list[str]:
    return [item async for item in plugin.handle_onebot(event)]


class GroupContextManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_enablement_persists_but_buffer_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "settings.json"
            first = GroupContextManager(path, max_messages=20, ttl_seconds=300)
            await first.set_enabled("group", True)
            await first.add("group", "Alice", "hello", now=100)
            self.assertEqual(await first.count("group", now=100), 1)
            reloaded = GroupContextManager(path, max_messages=20, ttl_seconds=300)
            self.assertTrue(await reloaded.is_enabled("group"))
            self.assertEqual(await reloaded.count("group", now=100), 0)

    async def test_ttl_and_secret_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            manager = GroupContextManager(
                Path(temporary_dir) / "settings.json",
                max_messages=20,
                ttl_seconds=300,
            )
            await manager.set_enabled("group", True)
            self.assertFalse(
                await manager.add(
                    "group", "Alice", "Authorization: Bearer hidden", now=100
                )
            )
            await manager.add("group", "Alice", "ordinary message", now=100)
            self.assertEqual(await manager.count("group", now=401), 0)


class PluginGroupContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        with patch.object(
            StarTools, "get_data_dir", return_value=Path(self.temporary.name)
        ):
            self.plugin = CodexBridgePlugin(
                object(),
                {
                    "qq_owner_ids": ["owner"],
                    "qq_user_whitelist": [],
                    "group_chat_enabled": True,
                    "memory_enabled": False,
                    "group_context_max_messages": 20,
                    "group_context_ttl_minutes": 30,
                },
            )
        self.fake_service = FakeService()
        self.plugin.service = self.fake_service  # type: ignore[assignment]

    async def _cleanup(self) -> None:
        await self.plugin.terminate()
        self.temporary.cleanup()

    async def test_ambient_group_text_is_injected_only_after_owner_enables(self) -> None:
        enabled_reply = await collect(
            self.plugin,
            GroupEvent("owner", "Owner", "/group_context on", mentioned=True),
        )
        self.assertTrue(enabled_reply and "已开启" in enabled_reply[0])

        ambient = GroupEvent(
            "unlisted-user", "Alice", "大家今晚八点开会", mentioned=False
        )
        self.assertEqual(await collect(self.plugin, ambient), [])
        self.assertTrue(ambient.stopped)

        reply = await collect(
            self.plugin,
            GroupEvent("owner", "Owner", "刚才几点开会？", mentioned=True),
        )
        self.assertEqual(reply, ["answer"])
        self.assertTrue(self.fake_service.prompts)
        prompt = self.fake_service.prompts[-1]
        self.assertIn("<recent_group_context>", prompt)
        self.assertIn("Alice: 大家今晚八点开会", prompt)
        self.assertIn("未受信任", prompt)

    async def test_non_owner_cannot_toggle_group_context(self) -> None:
        self.plugin.config["qq_user_whitelist"] = ["regular"]
        reply = await collect(
            self.plugin,
            GroupEvent("regular", "Regular", "/group_context on", mentioned=True),
        )
        self.assertTrue(reply and "只有" in reply[0])
        self.assertFalse(await self.plugin.group_context.is_enabled("group-session"))

    async def test_ambient_and_bot_turn_are_persisted_to_shared_group_memory(self) -> None:
        memory = FakeGroupMemory()
        self.plugin.memory = memory  # type: ignore[assignment]
        await collect(
            self.plugin,
            GroupEvent("owner", "Owner", "/group_context on", mentioned=True),
        )
        await collect(
            self.plugin,
            GroupEvent("unlisted-user", "Alice", "今晚八点开会", mentioned=False),
        )
        await asyncio.wait_for(self.plugin._group_memory_queue.join(), timeout=1)
        self.assertEqual(
            memory.messages,
            [("group-session", "Alice", "今晚八点开会")],
        )

        reply = await collect(
            self.plugin,
            GroupEvent("owner", "Owner", "几点开会？", mentioned=True),
        )
        self.assertEqual(reply, ["answer"])
        await asyncio.wait_for(self.plugin._group_memory_queue.join(), timeout=1)
        self.assertEqual(
            memory.turns,
            [("group-session", "Owner", "几点开会？", "answer")],
        )
        prompt = self.fake_service.prompts[-1]
        self.assertIn("群长期记忆", prompt)
        self.assertIn("reference_memory", prompt)
        self.assertIn("Alice: 何意味", prompt)


if __name__ == "__main__":
    unittest.main()
