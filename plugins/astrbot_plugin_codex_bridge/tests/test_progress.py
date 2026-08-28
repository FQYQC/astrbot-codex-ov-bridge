from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from astrbot_plugin_codex_bridge.bridge_core import CodexRunner
from astrbot_plugin_codex_bridge.progress import (
    LUNA_MODEL,
    ProgressSummarizer,
    ProgressTracker,
    sanitize_progress_output,
    sanitize_progress_text,
)


class ProgressTrackerTests(unittest.TestCase):
    def test_tracker_uses_actual_todo_and_removes_sensitive_values(self) -> None:
        tracker = ProgressTracker()
        tracker.ingest(
            {
                "type": "item.updated",
                "item": {
                    "type": "todo_list",
                    "items": [
                        {"text": "完成配置备份", "completed": True},
                        {
                            "text": "检查 /srv/private/config token=super-secret-value",
                            "completed": False,
                        },
                        {"text": "重启并验证服务", "completed": False},
                    ],
                },
            }
        )
        snapshot = tracker.snapshot()
        summary = snapshot.fallback_text(240)
        self.assertIn("完成配置备份", summary)
        self.assertIn("重启并验证服务", summary)
        self.assertNotIn("/srv/private", summary)
        self.assertNotIn("super-secret-value", summary)
        self.assertIn("[已隐藏]", summary)

    def test_stream_parser_updates_tracker(self) -> None:
        tracker = ProgressTracker()
        output = b"\n".join(
            [
                json.dumps(
                    {"type": "thread.started", "thread_id": "thread_12345678"}
                ).encode(),
                json.dumps(
                    {
                        "type": "item.updated",
                        "item": {
                            "type": "todo_list",
                            "items": [
                                {"text": "运行集成测试", "completed": False}
                            ],
                        },
                    }
                ).encode(),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "测试完成"},
                    }
                ).encode(),
            ]
        )
        result = CodexRunner.parse_jsonl(output, None, tracker)
        self.assertEqual(result.text, "测试完成")
        self.assertEqual(tracker.snapshot().todos[0].text, "运行集成测试")

    def test_agent_message_body_is_not_retained_for_progress(self) -> None:
        tracker = ProgressTracker()
        tracker.add_stage("主任务开始")
        tracker.ingest(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "用户原始正文不应进入总结器",
                },
            }
        )
        self.assertNotIn("用户原始正文", tracker.snapshot().prompt_payload(120))

    def test_timeout_allows_long_complex_tasks(self) -> None:
        self.assertEqual(CodexRunner(timeout_seconds=2400).timeout_seconds, 2400)
        self.assertEqual(CodexRunner(timeout_seconds=9999).timeout_seconds, 3600)


class ProgressSummarizerTests(unittest.TestCase):
    def test_summary_command_is_luna_ephemeral_low_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            summarizer = ProgressSummarizer(
                Path(temporary_dir), codex_path=Path("/opt/codex")
            )
            command = summarizer.build_command()
        self.assertEqual(command[command.index("--model") + 1], LUNA_MODEL)
        self.assertIn("--ephemeral", command)
        self.assertIn('model_reasoning_effort="low"', command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertNotIn("--yolo", command)
        self.assertNotIn("danger-full-access", command)

    def test_final_summary_preserves_todo_lines_and_redacts(self) -> None:
        text = (
            "任务进度（约 4 分钟）\n"
            "✓ 已完成：备份配置\n"
            "→ 正在进行：检查 /srv/private/file\n"
            "○ 下一步：重启服务"
        )
        stdout = json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": text},
            },
            ensure_ascii=False,
        ).encode()
        parsed = ProgressSummarizer._parse_final(stdout)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(len(parsed.splitlines()), 4)
        self.assertNotIn("/srv/private", parsed)
        self.assertIn("[工作区路径]", parsed)

    def test_multiline_sanitizer_removes_urls_and_credentials(self) -> None:
        value = "已完成：https://example.invalid/x\n下一步：password=hunter2"
        safe = sanitize_progress_output(value)
        self.assertEqual(len(safe.splitlines()), 2)
        self.assertNotIn("example.invalid", safe)
        self.assertNotIn("hunter2", safe)
        self.assertNotEqual(sanitize_progress_text(value), value)


if __name__ == "__main__":
    unittest.main()
