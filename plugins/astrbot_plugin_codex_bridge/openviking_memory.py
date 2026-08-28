"""OpenViking-backed memory with isolated QQ-user and QQ-group principals."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SENSITIVE_TERMS_RE = re.compile(
    r"(?i)(authorization\s*:|bearer\s+[a-z0-9._~-]+|oauth|refresh[_ -]?token|"
    r"access[_ -]?token|set-cookie|cookie\s*:|onebot.{0,20}token|root_api_key|"
    r"api[_ -]?key|auth\.json|codex_auth\.json)"
)
LONG_SECRET_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_+/=-]{48,}(?![A-Za-z0-9])")
SAFE_ID_RE = re.compile(r"^[a-z0-9_]{8,64}$")


class OpenVikingMemoryError(RuntimeError):
    pass


def safe_identifier(prefix: str, raw: str) -> str:
    digest = hashlib.sha256((prefix + "\0" + raw).encode("utf-8")).hexdigest()[:32]
    return prefix + "_" + digest


def safe_memory_text(text: str, limit: int) -> str | None:
    cleaned = text.replace("\x00", "").strip()[:limit]
    if not cleaned:
        return None
    if SENSITIVE_TERMS_RE.search(cleaned) or LONG_SECRET_RE.search(cleaned):
        return None
    return cleaned


def safe_group_memory_text(sender_label: str, text: str, limit: int = 2000) -> str | None:
    """Build a group-memory line without storing event IDs or unsafe secrets."""
    safe_text = safe_memory_text(text, limit)
    if not safe_text or safe_text.startswith("/"):
        return None
    safe_text = safe_text.replace("<", "＜").replace(">", "＞")
    label = " ".join(str(sender_label).replace("\x00", "").split())[:40]
    label = safe_memory_text(label, 40) or ""
    label = label.replace("<", "＜").replace(">", "＞")
    if not label or label.isdecimal():
        label = "群成员"
    return f"{label}: {safe_text}"


class PrivateUserKeyStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpenVikingMemoryError("memory credentials are unavailable") from exc
        if not isinstance(value, dict):
            raise OpenVikingMemoryError("memory credentials are invalid")
        return {
            key: secret
            for key, secret in value.items()
            if isinstance(key, str)
            and SAFE_ID_RE.fullmatch(key)
            and isinstance(secret, str)
            and len(secret) >= 32
        }

    def _write(self, value: dict[str, str]) -> None:
        fd, temporary_name = tempfile.mkstemp(prefix=".memory-users.", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    async def get(self, user_id: str) -> str | None:
        async with self._lock:
            return self._read().get(user_id)

    async def set(self, user_id: str, api_key: str) -> None:
        async with self._lock:
            value = self._read()
            value[user_id] = api_key
            self._write(value)


class OpenVikingMemory:
    def __init__(
        self,
        data_dir: Path,
        base_url: str,
        account_id: str,
        admin_api_key: str,
        timeout_seconds: int = 20,
    ) -> None:
        parsed = urllib.parse.urlparse(base_url.rstrip("/"))
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise OpenVikingMemoryError("OpenViking URL must be local HTTP")
        if not SAFE_ID_RE.fullmatch(account_id) or len(admin_api_key) < 32:
            raise OpenVikingMemoryError("OpenViking configuration is invalid")
        self.base_url = base_url.rstrip("/")
        self.account_id = account_id
        self.admin_api_key = admin_api_key
        self.timeout_seconds = max(3, min(int(timeout_seconds), 60))
        self.keys = PrivateUserKeyStore(data_dir / "memory_users.json")
        self._provision_locks: dict[str, asyncio.Lock] = {}
        self._provision_guard = asyncio.Lock()

    @classmethod
    def from_environment(cls, data_dir: Path) -> OpenVikingMemory | None:
        if os.environ.get("OPENVIKING_ENABLED", "0") != "1":
            return None
        return cls(
            data_dir=data_dir,
            base_url=os.environ.get("OPENVIKING_URL", "http://127.0.0.1:1933"),
            account_id=os.environ.get("OPENVIKING_ACCOUNT_ID", ""),
            admin_api_key=os.environ.get("OPENVIKING_ADMIN_API_KEY", ""),
        )

    def _request_sync(
        self,
        path: str,
        api_key: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        actor_peer_id: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
        if actor_peer_id:
            headers["X-OpenViking-Actor-Peer"] = actor_peer_id
        request = urllib.request.Request(
            self.base_url + path, data=body, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                return response.status, parsed if isinstance(parsed, dict) else {}
        except urllib.error.HTTPError as exc:
            try:
                parsed = json.loads(exc.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = {}
            return exc.code, parsed if isinstance(parsed, dict) else {}
        except (OSError, TimeoutError) as exc:
            raise OpenVikingMemoryError("OpenViking request failed") from exc

    async def _request(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        return await asyncio.to_thread(self._request_sync, *args, **kwargs)

    async def _user_lock(self, user_id: str) -> asyncio.Lock:
        async with self._provision_guard:
            return self._provision_locks.setdefault(user_id, asyncio.Lock())

    async def _principal_key(self, prefix: str, raw_id: str) -> tuple[str, str]:
        user_id = safe_identifier(prefix, raw_id)
        existing = await self.keys.get(user_id)
        if existing:
            return user_id, existing
        lock = await self._user_lock(user_id)
        async with lock:
            existing = await self.keys.get(user_id)
            if existing:
                return user_id, existing
            quoted_account = urllib.parse.quote(self.account_id, safe="")
            status, response = await self._request(
                f"/api/v1/admin/accounts/{quoted_account}/users",
                self.admin_api_key,
                method="POST",
                payload={"user_id": user_id, "role": "user"},
            )
            if status in {400, 409}:
                quoted_user = urllib.parse.quote(user_id, safe="")
                status, response = await self._request(
                    f"/api/v1/admin/accounts/{quoted_account}/users/{quoted_user}/key",
                    self.admin_api_key,
                    method="POST",
                    payload={},
                )
            if status != 200:
                raise OpenVikingMemoryError("OpenViking user provisioning failed")
            api_key = str(response.get("result", {}).get("user_key", "")).strip()
            if len(api_key) < 32:
                raise OpenVikingMemoryError("OpenViking did not return a user key")
            await self.keys.set(user_id, api_key)
            return user_id, api_key

    async def user_key(self, sender_id: str) -> tuple[str, str]:
        return await self._principal_key("qq", sender_id)

    async def group_key(self, session_key: str) -> tuple[str, str]:
        return await self._principal_key("group", session_key)

    @staticmethod
    def _extract_context(response: dict[str, Any], max_chars: int = 4000) -> str:
        result: Any = response.get("result", response)
        candidates: list[str] = []
        if isinstance(result, str):
            candidates.append(result)
        elif isinstance(result, dict):
            for key in ("context", "content", "text", "rendered", "digest"):
                if isinstance(result.get(key), str):
                    candidates.append(result[key])
            for collection_key in ("items", "results", "memories"):
                collection = result.get(collection_key)
                if isinstance(collection, list):
                    for item in collection[:4]:
                        if isinstance(item, str):
                            candidates.append(item)
                        elif isinstance(item, dict):
                            for key in ("abstract", "overview", "content", "text"):
                                if isinstance(item.get(key), str):
                                    candidates.append(item[key])
                                    break
        combined = "\n".join(part.strip() for part in candidates if part.strip())
        return combined[:max_chars]

    async def recall(self, sender_id: str, session_key: str, query: str) -> str:
        safe_query = safe_memory_text(query, 4000)
        if not safe_query:
            return ""
        user_id, api_key = await self.user_key(sender_id)
        memory_session = safe_identifier("session", session_key)
        status, response = await self._request(
            "/api/v1/search/search",
            api_key,
            method="POST",
            actor_peer_id=user_id,
            payload={
                "query": safe_query,
                "session_id": memory_session,
                "limit": 4,
                "mode": "context",
                "query_expansion": "off",
                "max_tokens": 512,
                "purpose": "chat",
                "detail": "abstract",
                "peer_scope": "actor",
                "rewrite": False,
            },
        )
        if status != 200:
            raise OpenVikingMemoryError("OpenViking recall failed")
        return self._extract_context(response)

    async def recall_group(self, session_key: str, query: str) -> str:
        safe_query = safe_memory_text(query, 4000)
        if not safe_query:
            return ""
        group_id, api_key = await self.group_key(session_key)
        memory_session = safe_identifier("group_session", session_key)
        status, response = await self._request(
            "/api/v1/search/search",
            api_key,
            method="POST",
            actor_peer_id=group_id,
            payload={
                "query": safe_query,
                "session_id": memory_session,
                "limit": 6,
                "mode": "context",
                "query_expansion": "off",
                "max_tokens": 1024,
                "purpose": "chat",
                "detail": "abstract",
                "peer_scope": "actor",
                "rewrite": False,
            },
        )
        if status != 200:
            raise OpenVikingMemoryError("OpenViking group recall failed")
        return self._extract_context(response, 12000)

    async def recent_group_messages(
        self, session_key: str, max_chars: int = 20000
    ) -> str:
        """Read the exact retained message tail from the isolated group session."""
        group_id, api_key = await self.group_key(session_key)
        memory_session = safe_identifier("group_session", session_key)
        quoted_session = urllib.parse.quote(memory_session, safe="")
        status, response = await self._request(
            f"/api/v1/sessions/{quoted_session}/context?token_budget=24000",
            api_key,
            actor_peer_id=group_id,
        )
        if status == 404:
            return ""
        if status != 200:
            raise OpenVikingMemoryError("OpenViking group context failed")
        result = response.get("result", {})
        messages = result.get("messages", []) if isinstance(result, dict) else []
        if not isinstance(messages, list):
            return ""
        lines: list[str] = []
        for item in messages[-120:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", ""))
            parts = item.get("parts", [])
            if not isinstance(parts, list):
                continue
            text = "".join(
                str(part.get("text", ""))
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
            safe_text = safe_memory_text(text, 6000)
            if not safe_text:
                continue
            safe_text = safe_text.replace("<", "＜").replace(">", "＞")
            if role == "assistant":
                safe_text = "机器人: " + safe_text
            lines.append(safe_text)
        return "\n".join(lines)[-max(1000, min(int(max_chars), 30000)) :]

    async def _commit_group_session(
        self, session_id: str, api_key: str
    ) -> None:
        quoted_session = urllib.parse.quote(session_id, safe="")
        status, _ = await self._request(
            f"/api/v1/sessions/{quoted_session}/commit",
            api_key,
            method="POST",
            payload={
                "retention_mode": "turn_budget",
                "keep_recent_turn_count": 100,
                "retained_message_token_budget": 20000,
                "min_raw_tail_steps": 20,
                "telemetry": False,
            },
        )
        if status != 200:
            raise OpenVikingMemoryError("OpenViking group commit failed")

    async def remember_group_message(
        self,
        session_key: str,
        sender_label: str,
        message: str,
    ) -> None:
        safe_message = safe_group_memory_text(sender_label, message)
        if not safe_message:
            return
        group_id, api_key = await self.group_key(session_key)
        session_id = safe_identifier("group_session", session_key)
        quoted_session = urllib.parse.quote(session_id, safe="")
        status, _ = await self._request(
            f"/api/v1/sessions/{quoted_session}/messages",
            api_key,
            method="POST",
            payload={
                "role": "user",
                "peer_id": group_id,
                "content": safe_message,
                "message_kind": "user_query",
                "telemetry": False,
            },
        )
        if status != 200:
            raise OpenVikingMemoryError("OpenViking group message write failed")
        await self._commit_group_session(session_id, api_key)

    async def remember_group_turn(
        self,
        session_key: str,
        sender_label: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        safe_user = safe_group_memory_text(sender_label, user_message, 8000)
        safe_assistant = safe_memory_text(assistant_message, 12000)
        if not safe_user or not safe_assistant:
            return
        group_id, api_key = await self.group_key(session_key)
        session_id = safe_identifier("group_session", session_key)
        quoted_session = urllib.parse.quote(session_id, safe="")
        for role, content, message_kind in (
            ("user", safe_user, "user_query"),
            ("assistant", safe_assistant, "assistant_step"),
        ):
            status, _ = await self._request(
                f"/api/v1/sessions/{quoted_session}/messages",
                api_key,
                method="POST",
                payload={
                    "role": role,
                    "peer_id": group_id,
                    "content": content,
                    "message_kind": message_kind,
                    "telemetry": False,
                },
            )
            if status != 200:
                raise OpenVikingMemoryError("OpenViking group turn write failed")
        await self._commit_group_session(session_id, api_key)

    async def remember(
        self,
        sender_id: str,
        session_key: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        safe_user = safe_memory_text(user_message, 8000)
        safe_assistant = safe_memory_text(assistant_message, 12000)
        if not safe_user or not safe_assistant:
            return
        user_id, api_key = await self.user_key(sender_id)
        session_id = safe_identifier("session", session_key)
        quoted_session = urllib.parse.quote(session_id, safe="")
        for role, content, message_kind in (
            ("user", safe_user, "user_query"),
            ("assistant", safe_assistant, "assistant_step"),
        ):
            status, _ = await self._request(
                f"/api/v1/sessions/{quoted_session}/messages",
                api_key,
                method="POST",
                payload={
                    "role": role,
                    "peer_id": user_id,
                    "content": content,
                    "message_kind": message_kind,
                    "telemetry": False,
                },
            )
            if status != 200:
                raise OpenVikingMemoryError("OpenViking message write failed")
        status, _ = await self._request(
            f"/api/v1/sessions/{quoted_session}/commit",
            api_key,
            method="POST",
            payload={
                "retention_mode": "turn_budget",
                "keep_recent_turn_count": 4,
                "retained_message_token_budget": 3000,
                "min_raw_tail_steps": 2,
                "telemetry": False,
            },
        )
        if status != 200:
            raise OpenVikingMemoryError("OpenViking commit failed")
