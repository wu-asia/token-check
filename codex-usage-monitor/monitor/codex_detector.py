"""Read-only discovery of the locally installed Codex clients."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CodexInstallation:
    cli_path: str | None
    cli_version: str | None
    desktop_installed: bool
    desktop_running: bool


def _desktop_details() -> tuple[bool, bool]:
    if sys.platform != "win32":
        return False, False
    command = (
        "$package = Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 PackageFullName; if ($package) { $package | ConvertTo-Json -Compress }; "
        "$process = Get-Process -Name ChatGPT -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if ($process) { 'RUNNING' }"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, False
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    installed = any(line.startswith("{") for line in lines)
    return installed, "RUNNING" in lines


def detect_codex() -> CodexInstallation:
    """Return availability metadata without changing Codex state or reading secrets."""
    executable = shutil.which("codex")
    version: str | None = None
    if executable:
        try:
            completed = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=5, check=False
            )
            version = (completed.stdout or completed.stderr).strip() or None
        except (OSError, subprocess.SubprocessError):
            version = None
    desktop_installed, desktop_running = _desktop_details()
    return CodexInstallation(executable, version, desktop_installed, desktop_running)
