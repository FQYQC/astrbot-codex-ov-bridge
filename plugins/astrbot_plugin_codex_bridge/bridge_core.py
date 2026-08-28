from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CODEX_PATH = Path("/home/ubuntu/.local/bin/codex")
CODEX_MODEL = "gpt-5.6-luna"
CODEX_WORKSPACE = Path("/home/ubuntu/personal-ai/agent-workspace")
CODEX_HOME = Path("/home/ubuntu/personal-ai/astrbot/codex-home")
THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


class CodexBridgeError(RuntimeError):
    """An intentionally detail-free bridge error suitable for caller handling."""


class CodexTimeoutError(CodexBridgeError):
    pass


@dataclass(frozen=True)
class CodexResult:
    thread_id: str
    text: str


class SessionStore:
    """Atomic, private storage for AstrBot session -> Codex thread mappings."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._guard = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _read_unlocked(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CodexBridgeError("session mapping is unavailable") from exc
        if not isinstance(value, dict):
            raise CodexBridgeError("session mapping is invalid")
        result: dict[str, str] = {}
        for key, thread_id in value.items():
            if isinstance(key, str) and isinstance(thread_id, str):
                if THREAD_ID_RE.fullmatch(thread_id):
                    result[key] = thread_id
        return result

    def _write_unlocked(self, value: dict[str, str]) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=".sessions.", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    async def get(self, session_key: str) -> str | None:
        async with self._guard:
            return self._read_unlocked().get(session_key)

    async def set(self, session_key: str, thread_id: str) -> None:
        if not THREAD_ID_RE.fullmatch(thread_id):
            raise CodexBridgeError("Codex returned an invalid thread identifier")
        async with self._guard:
            value = self._read_unlocked()
            value[session_key] = thread_id
            self._write_unlocked(value)

    async def delete(self, session_key: str) -> bool:
        async with self._guard:
            value = self._read_unlocked()
            existed = value.pop(session_key, None) is not None
            if existed:
                self._write_unlocked(value)
            return existed

    async def has(self, session_key: str) -> bool:
        return await self.get(session_key) is not None


class CodexRunner:
    def __init__(
        self,
        timeout_seconds: int = 180,
        codex_path: Path = CODEX_PATH,
        model: str = CODEX_MODEL,
        workspace: Path = CODEX_WORKSPACE,
    ) -> None:
        self.timeout_seconds = max(10, min(int(timeout_seconds), 600))
        self.codex_path = codex_path
        self.model = model
        self.workspace = workspace

    def build_command(self, thread_id: str | None) -> list[str]:
        common_config = [
            "--ignore-user-config",
            "--model",
            self.model,
            "--config",
            'approval_policy="on-request"',
        ]
        if thread_id:
            if not THREAD_ID_RE.fullmatch(thread_id):
                raise CodexBridgeError("stored thread identifier is invalid")
            return [
                str(self.codex_path),
                "exec",
                "resume",
                *common_config,
                "--config",
                'sandbox_mode="workspace-write"',
                "--json",
                thread_id,
                "-",
            ]
        return [
            str(self.codex_path),
            "exec",
            *common_config,
            "--sandbox",
            "workspace-write",
            "--cd",
            str(self.workspace),
            "--json",
            "--color",
            "never",
            "-",
        ]

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        env = {
            "HOME": "/home/ubuntu",
            "CODEX_HOME": str(CODEX_HOME),
            "PATH": "/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "NO_COLOR": "1",
        }
        if os.environ.get("SSL_CERT_FILE"):
            env["SSL_CERT_FILE"] = os.environ["SSL_CERT_FILE"]
        return env

    @staticmethod
    def parse_jsonl(stdout: bytes, existing_thread_id: str | None) -> CodexResult:
        thread_id = existing_thread_id
        final_message: str | None = None
        failed = False

        for raw_line in stdout.splitlines():
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type", ""))
            if event_type == "thread.started":
                candidate = event.get("thread_id")
                if candidate is None and isinstance(event.get("thread"), dict):
                    candidate = event["thread"].get("id")
                if isinstance(candidate, str) and THREAD_ID_RE.fullmatch(candidate):
                    thread_id = candidate
            elif event_type in {"turn.failed", "error"}:
                failed = True
            elif event_type == "agent_message":
                candidate = event.get("text") or event.get("message")
                if isinstance(candidate, str):
                    final_message = candidate
            elif event_type in {"item.completed", "item.updated"}:
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    candidate = item.get("text") or item.get("message")
                    if not isinstance(candidate, str):
                        content = item.get("content")
                        if isinstance(content, list):
                            parts = [
                                part.get("text", "")
                                for part in content
                                if isinstance(part, dict)
                                and isinstance(part.get("text"), str)
                            ]
                            candidate = "".join(parts)
                    if isinstance(candidate, str) and candidate.strip():
                        final_message = candidate

        if failed:
            raise CodexBridgeError("Codex reported a failed turn")
        if not thread_id:
            raise CodexBridgeError("Codex did not start a thread")
        if not final_message or not final_message.strip():
            raise CodexBridgeError("Codex did not return a final message")
        return CodexResult(thread_id=thread_id, text=final_message.strip())

    async def run(self, prompt: str, thread_id: str | None = None) -> CodexResult:
        if not self.codex_path.is_file():
            raise CodexBridgeError("Codex CLI is unavailable")
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        command = self.build_command(thread_id)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace,
                env=self._safe_environment(),
                start_new_session=True,
                limit=2 * 1024 * 1024,
            )
        except OSError as exc:
            raise CodexBridgeError("Codex CLI could not be started") from exc

        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), timeout=5)
            except (ProcessLookupError, TimeoutError):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            raise CodexTimeoutError("Codex timed out") from exc

        if process.returncode != 0:
            raise CodexBridgeError("Codex exited unsuccessfully")
        return self.parse_jsonl(stdout, thread_id)

    async def is_logged_in(self) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.codex_path),
                "login",
                "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._safe_environment(),
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
        except (OSError, TimeoutError):
            return False
        return process.returncode == 0 and b"Logged in" in stdout


class CodexBridgeService:
    """Serialize each session while allowing bounded cross-session concurrency."""

    def __init__(
        self,
        runner: CodexRunner,
        store: SessionStore,
        max_concurrency: int = 2,
    ) -> None:
        self.runner = runner
        self.store = store
        self._global_limit = asyncio.Semaphore(max(1, min(max_concurrency, 2)))
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _session_lock(self, session_key: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._session_locks.setdefault(session_key, asyncio.Lock())

    async def ask(self, session_key: str, prompt: str) -> CodexResult:
        lock = await self._session_lock(session_key)
        async with lock:
            thread_id = await self.store.get(session_key)
            async with self._global_limit:
                result = await self.runner.run(prompt, thread_id)
            if result.thread_id != thread_id:
                await self.store.set(session_key, result.thread_id)
            return result


def split_qq_message(text: str, limit: int = 1400) -> list[str]:
    limit = max(200, min(int(limit), 3000))
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = max(
            remaining.rfind("\n", 0, limit + 1),
            remaining.rfind("。", 0, limit + 1),
            remaining.rfind(" ", 0, limit + 1),
        )
        if cut < limit // 2:
            cut = limit
        else:
            cut += 1
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
