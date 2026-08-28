"""Verify a Codex thread can resume after switching from Luna to Sol."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from astrbot_plugin_codex_bridge.bridge_core import (
    CodexBridgeService,
    CodexRunner,
    SessionStore,
)


async def main() -> None:
    private_tmp_root = Path("/home/ubuntu/personal-ai/astrbot/backups")
    with tempfile.TemporaryDirectory(dir=private_tmp_root) as temporary_dir:
        service = CodexBridgeService(
            CodexRunner(timeout_seconds=240),
            SessionStore(Path(temporary_dir) / "sessions.json"),
        )
        first = await service.ask(
            "model-switch",
            "只回复精确文本 MODEL_LUNA_OK，不要添加其他内容。",
            "gpt-5.6-luna",
        )
        resumed = await service.ask(
            "model-switch",
            "只回复精确文本 MODEL_SOL_OK，不要添加其他内容。",
            "gpt-5.6-sol",
        )
        print(f"luna_first_ok={str(first.text.strip() == 'MODEL_LUNA_OK').lower()}")
        print(f"sol_resume_ok={str(resumed.text.strip() == 'MODEL_SOL_OK').lower()}")
        print(f"thread_reused={str(first.thread_id == resumed.thread_id).lower()}")


if __name__ == "__main__":
    asyncio.run(main())
