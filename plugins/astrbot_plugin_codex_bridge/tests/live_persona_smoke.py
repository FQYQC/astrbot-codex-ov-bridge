"""Use a real AstrBot persona without printing its prompt or model response."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from astrbot_plugin_codex_bridge.bridge_core import CodexRunner
from astrbot_plugin_codex_bridge.main import CodexBridgePlugin


DATABASE = Path("/home/ubuntu/personal-ai/astrbot/data/data_v4.db")


def load_created_persona() -> tuple[str, str, tuple[tuple[str, str], ...]]:
    database = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    try:
        row = database.execute(
            "SELECT persona_id, system_prompt, begin_dialogs FROM personas "
            "WHERE system_prompt IS NOT NULL AND trim(system_prompt) != '' "
            "ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    finally:
        database.close()
    if not row:
        raise RuntimeError("No configured AstrBot persona is available")
    raw_dialogs = json.loads(row[2] or "[]")
    examples = tuple(
        (str(raw_dialogs[index]), str(raw_dialogs[index + 1]))
        for index in range(0, len(raw_dialogs) - 1, 2)
    )
    return str(row[0]), str(row[1]), examples


async def main() -> None:
    persona_id, persona_prompt, persona_examples = load_created_persona()
    prompt = CodexBridgePlugin._build_prompt(
        "请严格按当前人格，用一句中文进行自我介绍；不要解释或复述人格设定。",
        persona_prompt=persona_prompt,
        persona_examples=persona_examples,
    )
    result = await CodexRunner(timeout_seconds=180).run(
        prompt,
        model="gpt-5.6-luna",
        effort="low",
    )
    print(
        json.dumps(
            {
                "created_persona_found": bool(persona_id),
                "persona_prompt_nonempty": bool(persona_prompt.strip()),
                "persona_block_injected": "<astrbot_persona_instructions>" in prompt,
                "persona_examples_present": bool(persona_examples),
                "persona_examples_injected": "<astrbot_persona_examples>" in prompt,
                "codex_response_nonempty": bool(result.text.strip()),
                "persona_prompt_not_echoed": persona_prompt.strip()
                not in result.text,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
