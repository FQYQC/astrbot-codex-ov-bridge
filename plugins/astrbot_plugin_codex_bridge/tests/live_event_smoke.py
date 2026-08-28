"""Exercise the plugin handler with simulated OneBot events and real Codex."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

from astrbot.api.platform import MessageType
from astrbot.api.star import StarTools

from astrbot_plugin_codex_bridge.main import CodexBridgePlugin


class SimulatedPrivateEvent:
    def __init__(self, message: str) -> None:
        self.message = message
        self.call_llm = True
        self.stopped = False

    def should_call_llm(self, value: bool) -> None:
        self.call_llm = value

    def stop_event(self) -> None:
        self.stopped = True

    def get_sender_id(self) -> str:
        return "test-allowlisted-user"

    def get_message_type(self) -> MessageType:
        return MessageType.FRIEND_MESSAGE

    def get_session_id(self) -> str:
        return "simulated-private-session"

    def get_message_str(self) -> str:
        return self.message

    def get_self_id(self) -> str:
        return "simulated-bot"

    def get_messages(self) -> list[object]:
        return []

    def plain_result(self, text: str) -> str:
        return text


async def collect(plugin: CodexBridgePlugin, event: SimulatedPrivateEvent) -> list[str]:
    return [result async for result in plugin.handle_onebot(event)]


async def main() -> None:
    private_tmp_root = Path("/home/ubuntu/personal-ai/astrbot/backups")
    with tempfile.TemporaryDirectory(dir=private_tmp_root) as temporary_dir:
        with patch.object(StarTools, "get_data_dir", return_value=Path(temporary_dir)):
            plugin = CodexBridgePlugin(
                object(),
                {
                    "qq_user_whitelist": ["test-allowlisted-user"],
                    "group_chat_enabled": False,
                    "timeout_seconds": 180,
                    "qq_chunk_chars": 1400,
                },
            )
        first_event = SimulatedPrivateEvent(
            "只回复精确文本 EVENT_FIRST_OK，不要添加其他内容。"
        )
        first_reply = await collect(plugin, first_event)
        resumed_event = SimulatedPrivateEvent(
            "只回复精确文本 EVENT_RESUME_OK，不要添加其他内容。"
        )
        resumed_reply = await collect(plugin, resumed_event)

        print(f"first_reply_ok={str(first_reply == ['EVENT_FIRST_OK']).lower()}")
        print(f"resume_reply_ok={str(resumed_reply == ['EVENT_RESUME_OK']).lower()}")
        print(
            "default_llm_blocked="
            + str(not first_event.call_llm and not resumed_event.call_llm).lower()
        )
        print(
            "events_stopped="
            + str(first_event.stopped and resumed_event.stopped).lower()
        )
        print(f"thread_persisted={str(await plugin.store.has(first_event.get_session_id())).lower()}")


if __name__ == "__main__":
    asyncio.run(main())
