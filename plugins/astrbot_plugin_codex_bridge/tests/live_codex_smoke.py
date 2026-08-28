"""Run a privacy-preserving real Codex first-turn/resume smoke test."""

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
        store = SessionStore(Path(temporary_dir) / "sessions.json")
        service = CodexBridgeService(CodexRunner(timeout_seconds=180), store)
        first = await service.ask(
            "live-a", "只回复精确文本 BRIDGE_FIRST_OK，不要添加其他内容。"
        )
        resumed = await service.ask(
            "live-a", "只回复精确文本 BRIDGE_RESUME_OK，不要添加其他内容。"
        )
        print(f"first_ok={str(first.text.strip() == 'BRIDGE_FIRST_OK').lower()}")
        print(f"resume_ok={str(resumed.text.strip() == 'BRIDGE_RESUME_OK').lower()}")
        print(f"thread_reused={str(first.thread_id == resumed.thread_id).lower()}")


if __name__ == "__main__":
    asyncio.run(main())
