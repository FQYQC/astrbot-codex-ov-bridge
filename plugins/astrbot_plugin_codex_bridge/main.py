from __future__ import annotations

import asyncio
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.platform import MessageType
from astrbot.api.star import Context, Star, StarTools

from .bridge_core import (
    CodexBridgeError,
    CodexBridgeService,
    CodexRunner,
    CodexTimeoutError,
    ModelPreferenceStore,
    SessionStore,
    model_from_choice,
    model_short_name,
    split_qq_message,
)
from .openviking_memory import OpenVikingMemory, OpenVikingMemoryError


class CodexBridgePlugin(Star):
    def __init__(self, context: Context, config: Any | None = None) -> None:
        super().__init__(context, config)
        self.config = config or {}
        data_dir = StarTools.get_data_dir("astrbot_plugin_codex_bridge")
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        timeout = int(self.config.get("timeout_seconds", 180))
        chunk_chars = int(self.config.get("qq_chunk_chars", 1400))
        self.chunk_chars = max(200, min(chunk_chars, 3000))
        self.runner = CodexRunner(timeout_seconds=timeout)
        self.store = SessionStore(data_dir / "sessions.json")
        self.model_preferences = ModelPreferenceStore(data_dir / "models.json")
        self.service = CodexBridgeService(self.runner, self.store, max_concurrency=2)
        self.memory: OpenVikingMemory | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()
        if bool(self.config.get("memory_enabled", True)):
            try:
                self.memory = OpenVikingMemory.from_environment(data_dir)
            except OpenVikingMemoryError:
                self.logger.warning("OpenViking memory configuration is unavailable")

    async def terminate(self) -> None:
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

    def _remember_background(
        self,
        sender_id: str,
        session_key: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        if self.memory is None:
            return
        task = asyncio.create_task(
            self.memory.remember(
                sender_id, session_key, user_message, assistant_message
            )
        )
        self._background_tasks.add(task)

        def completed(done: asyncio.Task[None]) -> None:
            self._background_tasks.discard(done)
            if done.cancelled():
                return
            try:
                done.result()
            except Exception:
                self.logger.warning("OpenViking background memory write failed")

        task.add_done_callback(completed)

    def _whitelist(self) -> set[str]:
        configured = self.config.get("qq_user_whitelist", [])
        owners = self.config.get("qq_owner_ids", [])
        allowed = configured if isinstance(configured, list) else []
        owner_values = owners if isinstance(owners, list) else []
        return {
            str(value).strip()
            for value in [*allowed, *owner_values]
            if str(value).strip()
        }

    def _owners(self) -> set[str]:
        configured = self.config.get("qq_owner_ids", [])
        if not isinstance(configured, list):
            return set()
        return {str(value).strip() for value in configured if str(value).strip()}

    @staticmethod
    def _is_group(event: AstrMessageEvent) -> bool:
        return event.get_message_type() == MessageType.GROUP_MESSAGE

    @staticmethod
    def _bot_was_mentioned(event: AstrMessageEvent) -> bool:
        self_id = str(event.get_self_id())
        return any(
            isinstance(component, Comp.At) and str(component.qq) == self_id
            for component in event.get_messages()
        )

    @staticmethod
    def _build_prompt(message: str, reference_memory: str = "") -> str:
        message = message.replace("\x00", "").strip()[:16000]
        memory_block = ""
        if reference_memory:
            memory_block = (
                "\n\n<reference_memory>\n"
                + reference_memory[:4000]
                + "\n</reference_memory>"
            )
        return (
            "你正在通过 QQ 与一个已授权用户对话。直接回答当前文本请求。"
            "不要假定或复述任何未提供的 QQ 原始事件、Cookie、token、系统日志或其他用户聊天。"
            "仅在专用工作区内进行必要操作；不要尝试读取认证文件或工作区外的私人数据。\n\n"
            "<current_user_message>\n"
            + message
            + "\n</current_user_message>"
            + memory_block
        )

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.ALL, priority=1000)
    async def handle_onebot(self, event: AstrMessageEvent):
        """Handle allowlisted OneBot messages through the local Codex CLI."""
        event.should_call_llm(False)
        event.stop_event()

        sender_id = str(event.get_sender_id()).strip()
        if not sender_id or sender_id not in self._whitelist():
            return

        is_group = self._is_group(event)
        if is_group:
            if not bool(self.config.get("group_chat_enabled", False)):
                return
            if not self._bot_was_mentioned(event):
                return

        session_key = str(event.get_session_id())
        message = event.get_message_str().strip()
        if not session_key or not message:
            return
        command_parts = message.split()
        command = command_parts[0].lower()
        arguments = [part.lower() for part in command_parts[1:]]
        is_owner = sender_id in self._owners()

        if message == "/codex_new":
            await self.store.delete(session_key)
            yield event.plain_result("已为当前 QQ 会话切换到新的 Codex 会话；下一条消息将创建新 thread。")
            return
        if message == "/codex_reset":
            removed = await self.store.delete(session_key)
            suffix = "已删除当前映射。" if removed else "当前没有已保存的映射。"
            yield event.plain_result(suffix)
            return
        if command == "/codex_model":
            current_model, overridden = await self.model_preferences.current(session_key)
            default_model = await self.model_preferences.default()
            if not arguments:
                yield event.plain_result(
                    "当前 session 模型："
                    + model_short_name(current_model)
                    + ("（单独设置）" if overridden else "（跟随默认）")
                    + "\n全局默认模型："
                    + model_short_name(default_model)
                )
                return
            if not is_owner:
                yield event.plain_result("只有 Bridge 所有者可以切换模型。")
                return
            if len(arguments) != 1:
                yield event.plain_result("用法：/codex_model luna|sol|default")
                return
            if arguments[0] == "default":
                await self.model_preferences.clear_session(session_key)
                selected_model, _ = await self.model_preferences.current(session_key)
                yield event.plain_result(
                    "当前 session 已改为跟随默认模型："
                    + model_short_name(selected_model)
                )
                return
            selected_model = model_from_choice(arguments[0])
            if selected_model is None:
                yield event.plain_result("用法：/codex_model luna|sol|default")
                return
            await self.model_preferences.set_session(session_key, selected_model)
            yield event.plain_result(
                "当前 session 模型已切换为：" + model_short_name(selected_model)
            )
            return
        if command == "/codex_default":
            if not is_owner:
                yield event.plain_result("只有 Bridge 所有者可以切换默认模型。")
                return
            if len(arguments) != 1:
                current_default = await self.model_preferences.default()
                yield event.plain_result(
                    "用法：/codex_default luna|sol\n当前默认："
                    + model_short_name(current_default)
                )
                return
            selected_model = model_from_choice(arguments[0])
            if selected_model is None:
                yield event.plain_result("用法：/codex_default luna|sol")
                return
            await self.model_preferences.set_default(selected_model)
            yield event.plain_result(
                "全局默认模型已切换为："
                + model_short_name(selected_model)
                + "\n已有单独设置的 session 不受影响。"
            )
            return
        if message == "/codex_status":
            logged_in = await self.runner.is_logged_in()
            has_thread = await self.store.has(session_key)
            selected_model, overridden = await self.model_preferences.current(session_key)
            default_model = await self.model_preferences.default()
            yield event.plain_result(
                "Codex 登录："
                + ("有效" if logged_in else "不可用")
                + "\n当前模型："
                + model_short_name(selected_model)
                + ("（单独设置）" if overridden else "（跟随默认）")
                + "\n默认模型："
                + model_short_name(default_model)
                + "\n当前 thread："
                + ("已建立" if has_thread else "尚未建立")
                + "\n长期记忆："
                + ("已启用" if self.memory is not None else "未启用")
                + "\n权限："
                + ("所有者" if sender_id in self._owners() else "授权用户")
            )
            return

        try:
            selected_model, _ = await self.model_preferences.current(session_key)
            reference_memory = ""
            if self.memory is not None:
                try:
                    reference_memory = await self.memory.recall(
                        sender_id, session_key, message
                    )
                except OpenVikingMemoryError:
                    self.logger.warning("OpenViking memory recall failed")
            result = await self.service.ask(
                session_key,
                self._build_prompt(message, reference_memory),
                selected_model,
            )
        except CodexTimeoutError:
            yield event.plain_result("Codex 本次处理超时，请稍后重试。")
            return
        except CodexBridgeError:
            yield event.plain_result("Codex 本次处理失败，请稍后重试或使用 /codex_new。")
            return
        except Exception:
            self.logger.exception("Codex Bridge request failed without message body logging")
            yield event.plain_result("Codex Bridge 暂时不可用，请稍后重试。")
            return

        self._remember_background(sender_id, session_key, message, result.text)
        for chunk in split_qq_message(result.text, self.chunk_chars):
            yield event.plain_result(chunk)
