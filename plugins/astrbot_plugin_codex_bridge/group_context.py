"""Owner-controlled, bounded, in-memory group context buffering."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .openviking_memory import safe_memory_text


@dataclass(frozen=True)
class GroupContextEntry:
    created_at: float
    sender_label: str
    text: str


class GroupContextManager:
    """Persist enablement only; message buffers intentionally remain in RAM."""

    def __init__(
        self,
        settings_path: Path,
        max_messages: int = 100,
        ttl_seconds: int = 86400,
    ) -> None:
        self.settings_path = settings_path
        self.max_messages = max(5, min(int(max_messages), 300))
        self.ttl_seconds = max(300, min(int(ttl_seconds), 604800))
        self.settings_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._buffers: dict[str, deque[GroupContextEntry]] = {}
        self._lock = asyncio.Lock()
        self._enabled = self._read_enabled_unlocked()

    def _read_enabled_unlocked(self) -> set[str]:
        if not self.settings_path.exists():
            return set()
        try:
            value = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        enabled = value.get("enabled_sessions", []) if isinstance(value, dict) else []
        if not isinstance(enabled, list):
            return set()
        return {item for item in enabled if isinstance(item, str) and item}

    def _write_enabled_unlocked(self, enabled: set[str]) -> None:
        fd, temporary_name = tempfile.mkstemp(
            prefix=".group-context.", dir=self.settings_path.parent
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {"enabled_sessions": sorted(enabled)},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.settings_path)
            os.chmod(self.settings_path, 0o600)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _prune_unlocked(self, session_key: str, now: float) -> None:
        buffer = self._buffers.get(session_key)
        if buffer is None:
            return
        cutoff = now - self.ttl_seconds
        while buffer and buffer[0].created_at < cutoff:
            buffer.popleft()
        if not buffer:
            self._buffers.pop(session_key, None)

    async def is_enabled(self, session_key: str) -> bool:
        async with self._lock:
            return session_key in self._enabled

    async def set_enabled(self, session_key: str, enabled_value: bool) -> None:
        async with self._lock:
            if enabled_value:
                self._enabled.add(session_key)
            else:
                self._enabled.discard(session_key)
                self._buffers.pop(session_key, None)
            self._write_enabled_unlocked(self._enabled)

    async def add(
        self,
        session_key: str,
        sender_label: str,
        text: str,
        now: float | None = None,
    ) -> bool:
        safe_text = safe_memory_text(text, 600)
        if not safe_text or safe_text.startswith("/"):
            return False
        safe_text = safe_text.replace("<", "＜").replace(">", "＞")
        safe_sender = " ".join(str(sender_label).replace("\x00", "").split())[:40]
        safe_sender = safe_memory_text(safe_sender, 40) or ""
        safe_sender = safe_sender.replace("<", "＜").replace(">", "＞")
        if not safe_sender or safe_sender.isdecimal():
            safe_sender = "群成员"
        current_time = time.time() if now is None else now
        async with self._lock:
            if session_key not in self._enabled:
                return False
            self._prune_unlocked(session_key, current_time)
            buffer = self._buffers.setdefault(
                session_key, deque(maxlen=self.max_messages)
            )
            buffer.append(
                GroupContextEntry(current_time, safe_sender, safe_text)
            )
            return True

    async def render(self, session_key: str, now: float | None = None) -> str:
        current_time = time.time() if now is None else now
        async with self._lock:
            if session_key not in self._enabled:
                return ""
            self._prune_unlocked(session_key, current_time)
            entries = list(self._buffers.get(session_key, ()))
        lines = [f"{entry.sender_label}: {entry.text}" for entry in entries]
        return "\n".join(lines)[-20000:]

    async def count(self, session_key: str, now: float | None = None) -> int:
        current_time = time.time() if now is None else now
        async with self._lock:
            self._prune_unlocked(session_key, current_time)
            return len(self._buffers.get(session_key, ()))
