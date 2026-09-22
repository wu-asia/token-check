"""Command-line interface for Codex Usage Monitor."""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from monitor.log_parser import unavailable_snapshot
from monitor.usage_model import UsageSnapshot
from monitor.usage_reader import read_usage


VERSION = "0.1.0"


def _percent(value: int | None) -> str:
    return f"{value}%" if value is not None else "N/A"


def format_reset_at(reset_at: datetime | None, now: datetime) -> str:
    if reset_at is None:
        return "N/A"
    local_reset = reset_at.astimezone()
    local_now = now.astimezone()
    return local_reset.strftime("%H:%M") if local_reset.date() == local_now.date() else local_reset.strftime("%Y-%m-%d %H:%M")


def format_reset_in(reset_at: datetime | None, now: datetime) -> str:
    if reset_at is None:
        return "N/A"
    seconds = max(0, int((reset_at - now).total_seconds()))
    total_minutes = math.ceil(seconds / 60)
    days, remaining_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining_minutes, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def render_status(snapshot: UsageSnapshot, *, now: datetime | None = None) -> str:
    display_now = now or datetime.now().astimezone()
    source = snapshot.source.value
    if not snapshot.verified:
        source += " (unverified)"
    return "\n".join((
        "Codex Usage Monitor",
        "",
        "5-hour",
        f"Used:       {_percent(snapshot.five_hour_used)}",
        f"Remaining:  {_percent(snapshot.five_hour_remaining)}",
        f"Reset at:   {format_reset_at(snapshot.five_hour_reset_at, display_now)}",
        f"Reset in:   {format_reset_in(snapshot.five_hour_reset_at, display_now)}",
        "",
        "Weekly",
        f"Used:       {_percent(snapshot.weekly_used)}",
        f"Remaining:  {_percent(snapshot.weekly_remaining)}",
        f"Reset at:   {format_reset_at(snapshot.weekly_reset_at, display_now)}",
        f"Reset in:   {format_reset_in(snapshot.weekly_reset_at, display_now)}",
        "",
        "Source:",
        source,
        "Status:",
        snapshot.status.value,
        "",
        "Last update:",
        snapshot.timestamp.astimezone().strftime("%H:%M:%S"),
    ))


def run_diagnostics() -> int:
    script = Path(__file__).parent / "diagnostics" / "diagnostics.py"
    try:
        completed = subprocess.run([sys.executable, str(script)], check=False)
        return completed.returncode
    except OSError:
        print("Unable to run diagnostics", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex Usage Monitor command-line interface")
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--status", action="store_true", help="show current Codex usage")
    commands.add_argument("--diagnostics", action="store_true", help="run read-only data-source diagnostics")
    commands.add_argument("--version", action="store_true", help="show monitor version")
    args = parser.parse_args(argv)

    if args.version:
        print(f"Codex Usage Monitor {VERSION}")
        return 0
    if args.diagnostics:
        return run_diagnostics()

    try:
        snapshot = read_usage()
    except Exception:
        snapshot = unavailable_snapshot(datetime.now().astimezone())
    print(render_status(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
