from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_codex_bridge.bridge_core import (
    CodexBridgeService,
    CodexResult,
    CodexRunner,
    EffortPreferenceStore,
    ModelPreferenceStore,
    SessionStore,
    effort_from_choice,
    model_from_choice,
    split_qq_message,
)


class FakeRunner:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.active_by_prompt: dict[str, int] = {}
        self.max_by_prompt: dict[str, int] = {}

    async def run(
        self,
        prompt: str,
        thread_id: str | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> CodexResult:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        key = prompt.split(":", 1)[0]
        self.active_by_prompt[key] = self.active_by_prompt.get(key, 0) + 1
        self.max_by_prompt[key] = max(
            self.max_by_prompt.get(key, 0), self.active_by_prompt[key]
        )
        await asyncio.sleep(0.04)
        self.active -= 1
        self.active_by_prompt[key] -= 1
        return CodexResult(thread_id=thread_id or f"thread_{key}_12345678", text=prompt)


class BridgeCoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_turn_and_resume_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner()
            store = SessionStore(Path(tmp) / "sessions.json")
            service = CodexBridgeService(runner, store)
            first = await service.ask("qq-a", "a:first")
            second = await service.ask("qq-a", "a:second")
            self.assertEqual(first.thread_id, second.thread_id)
            self.assertEqual(await store.get("qq-a"), first.thread_id)

    async def test_same_session_is_serial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner()
            service = CodexBridgeService(
                runner, SessionStore(Path(tmp) / "sessions.json")
            )
            await asyncio.gather(
                service.ask("same", "same:one"),
                service.ask("same", "same:two"),
            )
            self.assertEqual(runner.max_by_prompt["same"], 1)

    async def test_busy_session_reports_that_it_will_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner()
            service = CodexBridgeService(
                runner, SessionStore(Path(tmp) / "sessions.json")
            )
            first = asyncio.create_task(service.ask("same", "same:first"))
            await asyncio.sleep(0.01)
            self.assertTrue(await service.will_queue("same"))
            await first

    async def test_two_sessions_can_run_but_global_limit_is_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner()
            service = CodexBridgeService(
                runner, SessionStore(Path(tmp) / "sessions.json")
            )
            await asyncio.gather(
                service.ask("a", "a:one"),
                service.ask("b", "b:one"),
                service.ask("c", "c:one"),
            )
            self.assertEqual(runner.max_active, 2)

    async def test_model_preferences_are_per_session_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            store = ModelPreferenceStore(path)
            self.assertEqual(await store.current("private"), ("gpt-5.6-luna", False))
            await store.set_default("gpt-5.6-sol")
            await store.set_session("group", "gpt-5.6-luna")
            reloaded = ModelPreferenceStore(path)
            self.assertEqual(await reloaded.current("private"), ("gpt-5.6-sol", False))
            self.assertEqual(await reloaded.current("group"), ("gpt-5.6-luna", True))
            await reloaded.clear_session("group")
            self.assertEqual(await reloaded.current("group"), ("gpt-5.6-sol", False))

    def test_runner_accepts_only_allowlisted_models(self) -> None:
        runner = CodexRunner()
        command = runner.build_command(None, "gpt-5.6-sol")
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-sol")
        self.assertEqual(model_from_choice("LUNA"), "gpt-5.6-luna")
        with self.assertRaises(Exception):
            runner.build_command(None, "untrusted-model")

    async def test_effort_preferences_are_per_session_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "efforts.json"
            store = EffortPreferenceStore(path)
            self.assertEqual(await store.current("private"), ("medium", False))
            await store.set_default("high")
            await store.set_session("group", "max")
            reloaded = EffortPreferenceStore(path)
            self.assertEqual(await reloaded.current("private"), ("high", False))
            self.assertEqual(await reloaded.current("group"), ("max", True))
            await reloaded.clear_session("group")
            self.assertEqual(await reloaded.current("group"), ("high", False))

    def test_runner_passes_only_allowlisted_effort(self) -> None:
        runner = CodexRunner()
        command = runner.build_command(None, "gpt-5.6-sol", "xhigh")
        self.assertIn('model_reasoning_effort="xhigh"', command)
        self.assertEqual(effort_from_choice("MAX"), "max")
        with self.assertRaises(Exception):
            runner.build_command(None, "gpt-5.6-sol", "unlimited")

    def test_jsonl_parser(self) -> None:
        output = b"\n".join(
            [
                json.dumps(
                    {"type": "thread.started", "thread_id": "thread_12345678"}
                ).encode(),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "done"},
                    }
                ).encode(),
            ]
        )
        result = CodexRunner.parse_jsonl(output, None)
        self.assertEqual(result.thread_id, "thread_12345678")
        self.assertEqual(result.text, "done")

    def test_message_splitting(self) -> None:
        parts = split_qq_message("甲" * 450, 200)
        self.assertEqual("".join(parts), "甲" * 450)
        self.assertTrue(all(len(part) <= 200 for part in parts))


if __name__ == "__main__":
    unittest.main()
    effort_from_choice,
