"""Privacy-preserving live smoke test for streamed TODO progress and Luna summary."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from astrbot_plugin_codex_bridge.bridge_core import CodexRunner
from astrbot_plugin_codex_bridge.progress import ProgressSummarizer, ProgressTracker


async def main() -> None:
    tracker = ProgressTracker()
    runner = CodexRunner(timeout_seconds=240, model="gpt-5.6-luna")
    result = await runner.run(
        "这是 Bridge 的安全多步冒烟测试。开始后必须立即调用内置 update_plan/TODO 计划工具，"
        "列出‘检查输入’、‘核对约束’和‘给出结论’三项，依次将每项标为完成；"
        "除了计划工具外不要调用工具、读取文件或访问网络；最终只回答：进度测试完成。",
        model="gpt-5.6-luna",
        effort="medium",
        progress_tracker=tracker,
    )
    snapshot = tracker.snapshot()
    with tempfile.TemporaryDirectory(prefix="bridge-progress-smoke-") as temp_dir:
        summarizer = ProgressSummarizer(Path(temp_dir), max_concurrency=2)
        summary = await summarizer.summarize(snapshot, 240)

    safe_summary = summary or snapshot.fallback_text(240)
    print(
        json.dumps(
            {
                "result_ok": result.text == "进度测试完成。",
                "todo_seen": bool(snapshot.todos),
                "todo_completed": bool(snapshot.todos)
                and all(item.completed for item in snapshot.todos),
                "summary_ok": bool(summary),
                "summary_structured": "已完成" in safe_summary
                and "正在进行" in safe_summary,
                "timeout_2400_honored": CodexRunner(
                    timeout_seconds=2400
                ).timeout_seconds
                == 2400,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
