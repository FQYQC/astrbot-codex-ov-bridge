from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import astrbot.api.message_components as Comp
from astrbot.api.platform import MessageType
from astrbot.api.star import StarTools

from astrbot_plugin_codex_bridge.main import CodexBridgePlugin


class CommandEvent:
    def __init__(
        self,
        sender_id: str,
        session_id: str,
        message: str,
        components: list[object] | None = None,
    ) -> None:
        self.sender_id = sender_id
        self.session_id = session_id
        self.message = message
        self.components = components or []
        self.call_llm = True
        self.stopped = False

    def should_call_llm(self, value: bool) -> None:
        self.call_llm = value

    def stop_event(self) -> None:
        self.stopped = True

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_session_id(self) -> str:
        return self.session_id

    def get_message_str(self) -> str:
        return self.message

    def get_message_type(self) -> MessageType:
        return MessageType.FRIEND_MESSAGE

    def get_self_id(self) -> str:
        return "bot"

    def get_messages(self) -> list[object]:
        return self.components

    def plain_result(self, text: str) -> str:
        return text


async def collect(plugin: CodexBridgePlugin, event: CommandEvent) -> list[str]:
    return [item async for item in plugin.handle_onebot(event)]


class PluginModelCommandTests(unittest.IsolatedAsyncioTestCase):
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
                    "qq_user_whitelist": ["regular"],
                    "group_chat_enabled": False,
                    "memory_enabled": False,
                },
            )

    async def _cleanup(self) -> None:
        await self.plugin.terminate()
        self.temporary.cleanup()

    async def test_owner_can_set_default_and_private_override(self) -> None:
        await collect(self.plugin, CommandEvent("owner", "private", "/codex_default sol"))
        await collect(self.plugin, CommandEvent("owner", "group", "/codex_model luna"))
        self.assertEqual(
            await self.plugin.model_preferences.current("private"),
            ("gpt-5.6-sol", False),
        )
        self.assertEqual(
            await self.plugin.model_preferences.current("group"),
            ("gpt-5.6-luna", True),
        )

    async def test_regular_user_cannot_switch_model(self) -> None:
        reply = await collect(
            self.plugin, CommandEvent("regular", "regular-private", "/codex_default sol")
        )
        self.assertTrue(reply and "只有" in reply[0])
        self.assertEqual(await self.plugin.model_preferences.default(), "gpt-5.6-luna")

    async def test_default_clears_session_override(self) -> None:
        await collect(self.plugin, CommandEvent("owner", "private", "/codex_model sol"))
        await collect(
            self.plugin, CommandEvent("owner", "private", "/codex_model default")
        )
        self.assertEqual(
            await self.plugin.model_preferences.current("private"),
            ("gpt-5.6-luna", False),
        )

    async def test_private_plain_component_normalizes_invisible_command_text(self) -> None:
        event = CommandEvent(
            "owner",
            "private",
            "display text that must not control command parsing",
            [Comp.Plain("\u200b／codex_model sol")],
        )
        reply = await collect(self.plugin, event)
        self.assertTrue(reply and "sol" in reply[0].lower())
        self.assertEqual(
            await self.plugin.model_preferences.current("private"),
            ("gpt-5.6-sol", True),
        )

    async def test_owner_can_set_session_and_default_effort(self) -> None:
        reply = await collect(
            self.plugin, CommandEvent("owner", "private", "/codex_effort max")
        )
        self.assertTrue(reply and "max" in reply[0])
        await collect(
            self.plugin,
            CommandEvent("owner", "private", "/codex_effort_default high"),
        )
        self.assertEqual(
            await self.plugin.effort_preferences.current("private"),
            ("max", True),
        )
        self.assertEqual(await self.plugin.effort_preferences.default(), "high")

    async def test_regular_user_cannot_switch_effort(self) -> None:
        reply = await collect(
            self.plugin,
            CommandEvent("regular", "regular-private", "/codex_effort high"),
        )
        self.assertTrue(reply and "只有" in reply[0])
        self.assertEqual(
            await self.plugin.effort_preferences.current("regular-private"),
            ("medium", False),
        )


if __name__ == "__main__":
    unittest.main()
