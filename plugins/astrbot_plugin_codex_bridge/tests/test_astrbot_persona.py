from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot_plugin_codex_bridge.astrbot_persona import AstrBotPersonaAdapter
from astrbot_plugin_codex_bridge.main import CodexBridgePlugin


class FakeConversationManager:
    async def get_curr_conversation_id(self, umo: str) -> str:
        return "conversation"

    async def get_conversation(self, umo: str, conversation_id: str):
        return SimpleNamespace(persona_id="created-persona")


class FakePersonaManager:
    personas_v3 = [
        {"name": "created-persona", "prompt": "保持简洁且有角色风格。"},
        {"name": "另一个人格", "prompt": "另一个提示。"},
    ]

    async def resolve_selected_persona(self, **kwargs):
        self.kwargs = kwargs
        return (
            "created-persona",
            {"name": "created-persona", "prompt": "保持简洁且有角色风格。"},
            None,
            False,
        )


class FakeContext:
    def __init__(self) -> None:
        self.persona_manager = FakePersonaManager()
        self.conversation_manager = FakeConversationManager()

    def get_config(self, umo: str):
        return {"provider_settings": {"default_personality": "default"}}


class FakeEvent:
    unified_msg_origin = "aiocqhttp:GroupMessage:test"

    def get_platform_name(self) -> str:
        return "aiocqhttp"


class AstrBotPersonaTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_astrbot_conversation_persona(self) -> None:
        adapter = AstrBotPersonaAdapter(FakeContext())
        selected = await adapter.resolve(FakeEvent())
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.persona_id, "created-persona")
        self.assertIn("角色风格", selected.prompt)

    async def test_missing_astrbot_context_fails_closed(self) -> None:
        self.assertIsNone(await AstrBotPersonaAdapter(object()).resolve(FakeEvent()))

    async def test_lists_and_matches_available_personas(self) -> None:
        adapter = AstrBotPersonaAdapter(FakeContext())
        self.assertEqual(
            adapter.available_ids(), ["created-persona", "另一个人格"]
        )
        self.assertEqual(
            adapter.match_available_id("CREATED-PERSONA"), "created-persona"
        )

    async def test_native_session_override_preserves_other_settings(self) -> None:
        adapter = AstrBotPersonaAdapter(FakeContext())
        with (
            patch(
                "astrbot_plugin_codex_bridge.astrbot_persona.sp.get_async",
                new=AsyncMock(return_value={"llm_enabled": True}),
            ),
            patch(
                "astrbot_plugin_codex_bridge.astrbot_persona.sp.put_async",
                new=AsyncMock(),
            ) as put,
        ):
            await adapter.set_session_selection(FakeEvent(), "created-persona")
        value = put.await_args.kwargs["value"]
        self.assertTrue(value["llm_enabled"])
        self.assertEqual(value["persona_id"], "created-persona")

    def test_persona_is_a_trusted_separate_prompt_block(self) -> None:
        prompt = CodexBridgePlugin._build_prompt(
            "当前问题",
            persona_prompt="保持简洁且有角色风格。",
        )
        self.assertIn("<astrbot_persona_instructions>", prompt)
        self.assertIn("保持简洁且有角色风格。", prompt)
        self.assertLess(
            prompt.index("<astrbot_persona_instructions>"),
            prompt.index("<current_user_message>"),
        )


if __name__ == "__main__":
    unittest.main()
