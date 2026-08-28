"""Safe staging for QQ file components inside the Codex workspace."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import os
import re
import shutil
import socket
import stat
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import aiohttp


SAFE_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


class AttachmentError(RuntimeError):
    """Intentionally detail-free attachment failure."""


class AttachmentTooLargeError(AttachmentError):
    pass


class PublicOnlyResolver(aiohttp.abc.AbstractResolver):
    """Resolve HTTP hosts while rejecting loopback and private destinations."""

    @staticmethod
    def is_public_address(address: str) -> bool:
        try:
            return ipaddress.ip_address(address).is_global
        except ValueError:
            return False

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(
                host,
                port,
                family=family,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise AttachmentError("attachment host resolution failed") from exc
        results: list[dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for resolved_family, _, proto, _, sockaddr in infos:
            address = str(sockaddr[0])
            if not self.is_public_address(address):
                raise AttachmentError("attachment URL points to a non-public host")
            marker = (int(resolved_family), address)
            if marker in seen:
                continue
            seen.add(marker)
            results.append(
                {
                    "hostname": host,
                    "host": address,
                    "port": port,
                    "family": resolved_family,
                    "proto": proto,
                    "flags": socket.AI_NUMERICHOST,
                }
            )
        if not results:
            raise AttachmentError("attachment host has no public address")
        return results

    async def close(self) -> None:
        return None


class AttachmentManager:
    def __init__(
        self,
        root: Path,
        max_file_bytes: int = 20 * 1024 * 1024,
        max_files: int = 3,
        retention_seconds: int = 7 * 24 * 60 * 60,
    ) -> None:
        self.root = root
        self.max_file_bytes = max(1024, min(int(max_file_bytes), 50 * 1024 * 1024))
        self.max_files = max(1, min(int(max_files), 5))
        self.retention_seconds = max(3600, int(retention_seconds))
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.cleanup_stale()

    @staticmethod
    def _session_directory_name(session_key: str) -> str:
        digest = hashlib.sha256(("attachment\0" + session_key).encode()).hexdigest()
        return "session_" + digest[:24]

    @staticmethod
    def _safe_suffix(name: str) -> str:
        suffix = Path(str(name).replace("\x00", "")).suffix
        return suffix.lower() if SAFE_SUFFIX_RE.fullmatch(suffix) else ".bin"

    def _destination(self, session_key: str, original_name: str) -> Path:
        directory = self.root / self._session_directory_name(session_key)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
        return directory / ("upload_" + uuid.uuid4().hex + self._safe_suffix(original_name))

    @staticmethod
    def _open_exclusive(path: Path):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        return os.fdopen(fd, "wb")

    async def _copy_local(self, source_value: str, destination: Path) -> int:
        if source_value.startswith("file://"):
            parsed = urlparse(source_value)
            if parsed.hostname not in {None, "", "localhost"}:
                raise AttachmentError("local attachment URI is invalid")
            source_value = unquote(parsed.path)
        try:
            source = Path(source_value).resolve(strict=True)
            source_stat = source.stat()
        except OSError as exc:
            raise AttachmentError("local attachment is unavailable") from exc
        if not stat.S_ISREG(source_stat.st_mode):
            raise AttachmentError("local attachment is not a regular file")
        if source_stat.st_size > self.max_file_bytes:
            raise AttachmentTooLargeError("attachment exceeds the size limit")

        try:
            with source.open("rb") as input_handle, self._open_exclusive(
                destination
            ) as output_handle:
                shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
                output_handle.flush()
                os.fsync(output_handle.fileno())
            copied_size = destination.stat().st_size
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise AttachmentError("local attachment copy failed") from exc
        if copied_size > self.max_file_bytes:
            destination.unlink(missing_ok=True)
            raise AttachmentTooLargeError("attachment exceeds the size limit")
        return copied_size

    async def _download(self, url: str, destination: Path) -> int:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise AttachmentError("attachment URL is invalid")
        timeout = aiohttp.ClientTimeout(total=90, connect=15, sock_read=30)
        connector = aiohttp.TCPConnector(
            resolver=PublicOnlyResolver(),
            ssl=True,
            limit=2,
            ttl_dns_cache=0,
        )
        downloaded = 0
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                trust_env=False,
            ) as session:
                async with session.get(url, allow_redirects=True, max_redirects=3) as response:
                    if response.status != 200:
                        raise AttachmentError("attachment download failed")
                    declared = int(response.headers.get("content-length", "0") or "0")
                    if declared > self.max_file_bytes:
                        raise AttachmentTooLargeError("attachment exceeds the size limit")
                    with self._open_exclusive(destination) as output_handle:
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            downloaded += len(chunk)
                            if downloaded > self.max_file_bytes:
                                raise AttachmentTooLargeError(
                                    "attachment exceeds the size limit"
                                )
                            output_handle.write(chunk)
                        output_handle.flush()
                        os.fsync(output_handle.fileno())
        except AttachmentError:
            destination.unlink(missing_ok=True)
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
            destination.unlink(missing_ok=True)
            raise AttachmentError("attachment download failed") from exc
        return downloaded

    async def stage(self, session_key: str, components: list[Any]) -> list[Path]:
        if not components:
            return []
        if len(components) > self.max_files:
            raise AttachmentError("too many attachments")
        staged: list[Path] = []
        total_size = 0
        try:
            for component in components:
                name = str(getattr(component, "name", "") or "file")
                destination = self._destination(session_key, name)
                file_value = str(getattr(component, "file_", "") or "")
                url = str(getattr(component, "url", "") or "")
                if file_value:
                    size = await self._copy_local(file_value, destination)
                elif url:
                    size = await self._download(url, destination)
                else:
                    raise AttachmentError("attachment has no usable source")
                staged.append(destination)
                total_size += size
                if total_size > self.max_file_bytes * 2:
                    raise AttachmentTooLargeError("attachments exceed the total size limit")
        except Exception:
            for path in staged:
                path.unlink(missing_ok=True)
            raise
        return staged

    def cleanup_stale(self, now: float | None = None) -> None:
        cutoff = (time.time() if now is None else now) - self.retention_seconds
        for path in self.root.rglob("*"):
            try:
                if (path.is_file() or path.is_symlink()) and path.lstat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                continue
        directories = sorted(
            (path for path in self.root.rglob("*") if path.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        )
        for directory in directories:
            try:
                directory.rmdir()
            except OSError:
                continue
