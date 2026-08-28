#!/usr/bin/env python3
"""Fail when Git-tracked files look like runtime secrets or credentials."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


DENIED_NAMES = {"auth.json", "codex_auth.json"}
DENIED_SUFFIXES = {".token", ".private"}
CONTENT_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+=_-]{64,}(?![A-Za-z0-9])"),
)


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"])
    return [Path(item.decode("utf-8")) for item in output.split(b"\0") if item]


def main() -> None:
    violations: list[str] = []
    for path in tracked_files():
        lowered = path.name.lower()
        if lowered in DENIED_NAMES or path.suffix.lower() in DENIED_SUFFIXES:
            violations.append(f"denied secret filename: {path}")
            continue
        if lowered.endswith(".env") and not lowered.endswith(".env.example"):
            violations.append(f"private environment file: {path}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "sha256:" in line or "replace-with-" in line:
                continue
            if any(pattern.search(line) for pattern in CONTENT_PATTERNS):
                violations.append(f"credential-like content: {path}:{line_number}")
    if violations:
        for violation in violations:
            print(violation)
        raise SystemExit(1)
    print(f"secret_scan_ok=true tracked_files={len(tracked_files())}")


if __name__ == "__main__":
    main()
