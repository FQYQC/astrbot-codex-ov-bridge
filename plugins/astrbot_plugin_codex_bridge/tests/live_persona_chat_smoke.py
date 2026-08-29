"""Verify that the deployed persona handles casual group banter naturally.

The fixture is wholly fictional.  Deliberately print booleans only so neither
the injected context nor the model response becomes part of routine logs.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from astrbot_plugin_codex_bridge.bridge_core import CodexRunner
from astrbot_plugin_codex_bridge.main import CodexBridgePlugin


TEMPLATE = Path("/home/ubuntu/personal-ai/personas/fywy.json")
CONSERVATIVE_PHRASES = (
    "现实中的身份",
    "根据我能看到的上下文",
    "不能据此认定",
    "无法确定",
    "旅行者",
)


async def main() -> None:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    dialogs = template["begin_dialogs"]
    examples = tuple(
        (str(dialogs[index]), str(dialogs[index + 1]))
        for index in range(0, len(dialogs) - 1, 2)
    )
    prompt = CodexBridgePlugin._build_prompt(
        "[群聊近期消息]\n小岚：以后就叫你阿澈老公了\n"
        "[当前消息]\n你知道我是谁老公吗？",
        persona_prompt=str(template["system_prompt"]),
        persona_examples=examples,
    )
    result = await CodexRunner(timeout_seconds=180).run(
        prompt,
        model="gpt-5.6-luna",
        effort="low",
    )
    response = result.text.strip()
    print(
        json.dumps(
            {
                "response_nonempty": bool(response),
                "recognized_fictional_relation": "阿澈" in response,
                "avoided_conservative_boilerplate": not any(
                    phrase in response for phrase in CONSERVATIVE_PHRASES
                ),
                "casual_reply_length": len(response) <= 160,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
