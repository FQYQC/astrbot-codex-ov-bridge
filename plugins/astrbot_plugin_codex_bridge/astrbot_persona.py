"""Resolve AstrBot's native per-session persona for the Codex bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from astrbot.api import sp


@dataclass(frozen=True)
class AstrBotPersona:
    persona_id: str
    prompt: str


class AstrBotPersonaAdapter:
    """Use AstrBot's own persona manager without invoking its LLM provider."""

    def __init__(self, context: Any, max_prompt_chars: int = 16000) -> None:
        self.context = context
        self.max_prompt_chars = max(1000, min(int(max_prompt_chars), 24000))

    async def _resolve_raw(self, event: Any) -> tuple[str | None, Any | None]:
        persona_manager = getattr(self.context, "persona_manager", None)
        config_getter = getattr(self.context, "get_config", None)
        if persona_manager is None or not callable(config_getter):
            return None, None
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        if not umo:
            return None, None

        conversation_persona_id: str | None = None
        conversation_manager = getattr(self.context, "conversation_manager", None)
        try:
            if conversation_manager is not None:
                conversation_id = await conversation_manager.get_curr_conversation_id(
                    umo
                )
                if conversation_id:
                    conversation = await conversation_manager.get_conversation(
                        umo, conversation_id
                    )
                    if conversation is not None:
                        value = getattr(conversation, "persona_id", None)
                        if isinstance(value, str):
                            conversation_persona_id = value

            config = config_getter(umo=umo)
            provider_settings = config.get("provider_settings", {})
            persona_id, persona, _, _ = await persona_manager.resolve_selected_persona(
                umo=umo,
                conversation_persona_id=conversation_persona_id,
                platform_name=str(event.get_platform_name()),
                provider_settings=provider_settings,
            )
        except Exception:
            return None, None

        return persona_id if isinstance(persona_id, str) else None, persona

    async def resolve(self, event: Any) -> AstrBotPersona | None:
        persona_id, persona = await self._resolve_raw(event)

        if not persona or not isinstance(persona_id, str) or not persona_id:
            return None
        prompt = persona.get("prompt")
        if not isinstance(prompt, str):
            return None
        prompt = prompt.replace("\x00", "").strip()[: self.max_prompt_chars]
        if not prompt:
            return None
        return AstrBotPersona(persona_id=persona_id[:255], prompt=prompt)

    async def current_id(self, event: Any) -> str | None:
        persona_id, _ = await self._resolve_raw(event)
        if persona_id == "[%None]":
            return "off"
        return persona_id

    def available_ids(self) -> list[str]:
        persona_manager = getattr(self.context, "persona_manager", None)
        personas = getattr(persona_manager, "personas_v3", None)
        if not isinstance(personas, list):
            return []
        result: list[str] = []
        for persona in personas:
            try:
                value = persona.get("name")
            except (AttributeError, TypeError):
                continue
            if isinstance(value, str) and value.strip():
                result.append(value.strip()[:255])
        return sorted(set(result), key=str.casefold)

    def match_available_id(self, requested: str) -> str | None:
        requested = requested.strip()
        if not requested:
            return None
        available = self.available_ids()
        if requested in available:
            return requested
        folded = requested.casefold()
        matches = [item for item in available if item.casefold() == folded]
        return matches[0] if len(matches) == 1 else None

    async def set_session_selection(
        self, event: Any, persona_id: str | None
    ) -> None:
        """Force a native AstrBot persona for one UMO, or clear the override."""
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        if not umo:
            raise ValueError("missing AstrBot session origin")
        config = (
            await sp.get_async(
                scope="umo",
                scope_id=umo,
                key="session_service_config",
                default={},
            )
            or {}
        )
        if not isinstance(config, dict):
            config = {}
        if persona_id is None:
            config.pop("persona_id", None)
        else:
            config["persona_id"] = persona_id
        await sp.put_async(
            scope="umo",
            scope_id=umo,
            key="session_service_config",
            value=config,
        )
