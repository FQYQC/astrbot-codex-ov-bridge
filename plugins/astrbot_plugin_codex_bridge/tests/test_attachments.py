from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import astrbot.api.message_components as Comp
from astrbot.api.platform import MessageType
from astrbot.api.star import StarTools

from astrbot_plugin_codex_bridge.attachments import (
    AttachmentManager,
    AttachmentTooLargeError,
    PublicOnlyResolver,
)
from astrbot_plugin_codex_bridge.bridge_core import CodexResult
from astrbot_plugin_codex_bridge.main import CodexBridgePlugin
from astrbot_plugin_codex_bridge.progress import ProgressTracker


class FileEvent:
    def __init__(self, file_component: Comp.File) -> None:
        self.file_component = file_component
        self.sent: list[str] = []

    def should_call_llm(self, value: bool) -> None:
        return None

    def stop_event(self) -> None:
        return None

    def get_sender_id(self) -> str:
        return "owner"

    def get_session_id(self) -> str:
        return "private-session"

    def get_message_str(self) -> str:
        return ""

    def get_message_type(self) -> MessageType:
        return MessageType.FRIEND_MESSAGE

    def get_self_id(self) -> str:
        return "bot"

    def get_messages(self) -> list[object]:
        return [self.file_component]

    def plain_result(self, text: str) -> str:
        return text

    async def send(self, message: str) -> None:
        self.sent.append(message)


class FakeService:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def will_queue(self, session_key: str) -> bool:
        return False

    async def ask(
        self,
        session_key: str,
        prompt: str,
        model: str | None = None,
        effort: str | None = None,
        progress_tracker: ProgressTracker | None = None,
    ) -> CodexResult:
        self.prompts.append(prompt)
        return CodexResult("thread_attachment_12345678", "file answer")


class AttachmentManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_file_is_copied_to_hashed_private_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "source.txt"
            source.write_text("hello attachment", encoding="utf-8")
            manager = AttachmentManager(root / "staged")
            paths = await manager.stage(
                "raw-private-session-id",
                [Comp.File(name="../private-name.txt", file=str(source))],
            )
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].read_text(encoding="utf-8"), "hello attachment")
            self.assertTrue(paths[0].is_relative_to(root / "staged"))
            self.assertNotIn("private-name", paths[0].name)
            self.assertNotIn("raw-private-session-id", str(paths[0]))
            self.assertEqual(os.stat(paths[0]).st_mode & 0o777, 0o600)

    async def test_oversized_local_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "large.bin"
            source.write_bytes(b"x" * 2048)
            manager = AttachmentManager(root / "staged", max_file_bytes=1024)
            with self.assertRaises(AttachmentTooLargeError):
                await manager.stage(
                    "session", [Comp.File(name="large.bin", file=str(source))]
                )

    def test_private_network_download_is_rejected(self) -> None:
        self.assertFalse(PublicOnlyResolver.is_public_address("127.0.0.1"))
        self.assertFalse(PublicOnlyResolver.is_public_address("10.0.0.1"))
        self.assertTrue(PublicOnlyResolver.is_public_address("1.1.1.1"))


class PluginAttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_file_only_event_reaches_codex_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "input.md"
            source.write_text("document body", encoding="utf-8")
            with patch.object(StarTools, "get_data_dir", return_value=root / "data"):
                plugin = CodexBridgePlugin(
                    object(),
                    {
                        "qq_owner_ids": ["owner"],
                        "qq_user_whitelist": [],
                        "group_chat_enabled": False,
                        "memory_enabled": False,
                    },
                )
            self.addAsyncCleanup(plugin.terminate)
            plugin.attachments = AttachmentManager(root / "attachments")
            service = FakeService()
            plugin.service = service  # type: ignore[assignment]
            event = FileEvent(Comp.File(name="input.md", file=str(source)))
            replies = [item async for item in plugin.handle_onebot(event)]
            self.assertEqual(replies, ["file answer"])
            self.assertTrue(service.prompts)
            prompt = service.prompts[0]
            self.assertIn("<uploaded_files>", prompt)
            self.assertIn(str(root / "attachments"), prompt)
            self.assertNotIn(str(source), prompt)
            self.assertIn("不受信任文件", prompt)
            self.assertEqual(len(event.sent), 1)
            self.assertIn("开始处理", event.sent[0])

    async def test_low_effort_private_file_does_not_send_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "input.txt"
            source.write_text("small", encoding="utf-8")
            with patch.object(StarTools, "get_data_dir", return_value=root / "data"):
                plugin = CodexBridgePlugin(
                    object(),
                    {
                        "qq_owner_ids": ["owner"],
                        "group_chat_enabled": False,
                        "memory_enabled": False,
                    },
                )
            self.addAsyncCleanup(plugin.terminate)
            await plugin.effort_preferences.set_session("private-session", "low")
            plugin.attachments = AttachmentManager(root / "attachments")
            plugin.service = FakeService()  # type: ignore[assignment]
            event = FileEvent(Comp.File(name="input.txt", file=str(source)))
            replies = [item async for item in plugin.handle_onebot(event)]
            self.assertEqual(replies, ["file answer"])
            self.assertEqual(event.sent, [])


if __name__ == "__main__":
    unittest.main()
