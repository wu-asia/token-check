"""Phase-1, read-only discovery of potential Codex usage data sources.

The program never starts an interactive Codex session, connects to App Server,
uses a network endpoint, or reports file contents or authentication material.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


KEYWORDS = (
    "usage", "rate_limit", "ratelimit", "remaining", "reset", "reset_at",
    "weekly", "5-hour", "five_hour", "quota", "limit",
)
TEXT_EXTENSIONS = {".json", ".jsonl", ".log", ".txt", ".toml", ".yaml", ".yml", ".sqlite", ".db"}
SENSITIVE_TERMS = ("access_token", "refresh_token", "session_token", "cookie", "authorization", "bearer", "api_key")
SENSITIVE_PATH_TERMS = SENSITIVE_TERMS + ("auth", "token", "credential", "session", "local storage")
IGNORED_PATH_PARTS = {"node_modules", ".tmp", "extensions", "zxcvbndata", "subresource filter"}
MAX_FILES_PER_ROOT = 2_000
MAX_BYTES_PER_FILE = 1_048_576


@dataclass(frozen=True)
class Candidate:
    path: Path
    size: int
    modified_at: datetime
    terms: tuple[str, ...]


@dataclass
class RootResult:
    label: str
    path: Path
    exists: bool
    readable: bool = False
    errors: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_sensitive_path(path: Path) -> bool:
    """Do not inspect files under known credential-like names or folders."""
    return any(term in part.lower() for part in path.parts for term in SENSITIVE_PATH_TERMS)


def is_irrelevant_bundle_path(path: Path) -> bool:
    return any(part.lower() in IGNORED_PATH_PARTS for part in path.parts)


def matching_terms(path: Path) -> tuple[str, ...]:
    """Return only matching keyword labels from a bounded read, never values."""
    if path.suffix.lower() not in TEXT_EXTENSIONS or is_sensitive_path(path):
        return ()
    try:
        with path.open("rb") as source:
            sample = source.read(MAX_BYTES_PER_FILE).decode("utf-8", errors="ignore").lower()
    except (OSError, UnicodeError):
        return ()
    return tuple(keyword for keyword in KEYWORDS if re.search(re.escape(keyword), sample, re.IGNORECASE))


def walk_root(label: str, root: Path) -> RootResult:
    result = RootResult(label=label, path=root, exists=root.exists())
    if not result.exists:
        return result
    try:
        result.readable = os.access(root, os.R_OK)
        inspected = 0
        for path in root.rglob("*"):
            if inspected >= MAX_FILES_PER_ROOT:
                result.errors.append(f"scan limit reached ({MAX_FILES_PER_ROOT} files)")
                break
            if not path.is_file() or is_sensitive_path(path) or is_irrelevant_bundle_path(path):
                continue
            inspected += 1
            terms = matching_terms(path)
            if terms:
                stat = path.stat()
                result.candidates.append(Candidate(
                    path=path,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                    terms=terms,
                ))
    except PermissionError:
        result.errors.append("permission denied")
    except OSError as error:
        result.errors.append(f"read error: {type(error).__name__}")
    return result


def desktop_is_running() -> bool:
    if sys.platform != "win32":
        return False
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ChatGPT.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return "ChatGPT.exe" in completed.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def desktop_details() -> tuple[bool, str | None, str | None]:
    """Read MSIX registration metadata only; it never opens application data."""
    if sys.platform != "win32":
        return False, None, None
    command = (
        "$package = Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 Version, PackageFullName; "
        "if ($package) { $package | ConvertTo-Json -Compress }"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=10, check=False,
        )
        package = json.loads(completed.stdout) if completed.stdout.strip() else None
        if not package:
            return False, None, None
        return True, str(package.get("Version") or "unknown"), str(package.get("PackageFullName") or "unknown")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return False, None, None


def cli_details() -> tuple[str | None, str | None]:
    executable = shutil.which("codex")
    if not executable:
        return None, None
    try:
        completed = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10, check=False)
        return executable, (completed.stdout or completed.stderr).strip() or "version unavailable"
    except (OSError, subprocess.SubprocessError):
        return executable, "version command failed"


def command_supports_app_server() -> bool:
    """Check command help only; never starts or connects to App Server."""
    executable = shutil.which("codex")
    if not executable:
        return False
    try:
        completed = subprocess.run(
            [executable, "app-server", "--help"], capture_output=True, text=True, timeout=10, check=False,
        )
        return completed.returncode == 0 and "app server" in completed.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def roots_to_check() -> list[tuple[str, Path]]:
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    packages_dir = local / "Packages"
    package_roots = list(packages_dir.glob("OpenAI.Codex_*")) if packages_dir.exists() else []
    roots = [("Codex CLI home", home / ".codex"), ("Codex local application data", local / "OpenAI" / "Codex")]
    for package in package_roots:
        for state in ("LocalState", "LocalCache", "RoamingState"):
            roots.append((f"MSIX {state}", package / state))
    return roots


def log_directories(results: list[RootResult]) -> list[Path]:
    directories: list[Path] = []
    for result in results:
        if not result.exists or is_sensitive_path(result.path) or is_irrelevant_bundle_path(result.path):
            continue
        try:
            directories.extend(
                path for path in result.path.rglob("*")
                if path.is_dir() and path.name.lower() in {"log", "logs"} and not is_irrelevant_bundle_path(path)
            )
        except OSError:
            continue
    return sorted(set(directories))


def evidence_status(results: list[RootResult]) -> str:
    return "Local / Unverified" if any(result.candidates for result in results) else "Unknown"


def build_report(results: list[RootResult]) -> str:
    cli_path, cli_version = cli_details()
    desktop_installed, desktop_version, package_name = desktop_details()
    app_server_available = command_supports_app_server()
    local_evidence = evidence_status(results)
    # Detecting a protocol or local keyword is not equivalent to reading a usage value.
    source = "Unknown"
    lines = [
        "Codex Usage Monitor — Phase 1 read-only diagnostics report",
        f"Generated (UTC): {utc_now().isoformat()}",
        "",
        "Safety boundary: no network calls, App Server connection/RPC, interactive Codex command, or Codex write.",
        "Filtered from inspection/reporting: " + ", ".join(SENSITIVE_TERMS) + ".",
        "File contents and matched values are never included in this report.",
        "",
        f"Codex CLI: {'found' if cli_path else 'not found'}" + (f" — {cli_path} ({cli_version})" if cli_path else ""),
        f"Codex Desktop installed: {'yes' if desktop_installed else 'not found'}" + (
            f" — version {desktop_version}; package {package_name}" if desktop_installed else ""
        ),
        f"Codex Desktop running: {'yes' if desktop_is_running() else 'no'}",
        f"Official CLI App Server capability: {'detected' if app_server_available else 'not detected'}",
        "Official protocol candidate: account/rateLimits/read (not invoked).",
        f"Local keyword evidence: {local_evidence}",
        f"Data Source: {source}",
        "Verification: no usage value was queried or parsed during Phase 1.",
        "",
        "Requested fields (Available / Not Found / Unknown):",
        "  five_hour_used: Unknown",
        "  five_hour_remaining: Unknown",
        "  five_hour_reset_at: Unknown",
        "  weekly_used: Unknown",
        "  weekly_remaining: Unknown",
        "  weekly_reset_at: Unknown",
        "",
        "Discovered log directories:",
    ]
    logs = log_directories(results)
    lines.extend(f"- {directory}" for directory in logs) if logs else lines.append("- none found")
    lines.extend(["", "Roots examined:"])
    for result in results:
        lines.append(f"- {result.label}: {result.path}")
        lines.append(f"  exists={result.exists}; readable={result.readable}; candidate_files={len(result.candidates)}")
        lines.extend(f"  note: {error}" for error in result.errors)
        for candidate in result.candidates[:50]:
            lines.append(
                f"  candidate: {candidate.path} | {candidate.size} bytes | {candidate.modified_at.isoformat()} | "
                f"terms={', '.join(candidate.terms)}"
            )
        if len(result.candidates) > 50:
            lines.append(f"  note: {len(result.candidates) - 50} additional candidate files omitted")
    lines.extend([
        "",
        "Interpretation: local keyword matches are possible sources only, not verified official usage data.",
        "Phase 1 stopped here. No GUI, tray, notifications, history, usage reader, or packaging was implemented.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Codex local usage-source diagnostics")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("diagnostics_report.txt"))
    args = parser.parse_args()
    results = [walk_root(label, path) for label, path in roots_to_check()]
    report = build_report(results)
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    except OSError as error:
        print(f"Unable to write report: {error}", file=sys.stderr)
        return 1
    print(f"Diagnostics report written to: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
