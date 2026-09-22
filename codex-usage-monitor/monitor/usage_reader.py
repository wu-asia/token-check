"""Read the documented, official Codex App Server rate-limit surface."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from monitor.codex_detector import CodexInstallation, detect_codex
from monitor.log_parser import parse_rate_limit_payload, unavailable_snapshot
from monitor.usage_model import DataSource, SnapshotStatus, UsageSnapshot


APP_SERVER_TIMEOUT_SECONDS = 15.0


class AppServerReadError(RuntimeError):
    """A safe, credential-free description of a read-only App Server failure."""


def _wait_for_message(messages: queue.Queue[dict[str, Any]], identifier: int, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AppServerReadError("App Server response timed out")
        try:
            message = messages.get(timeout=remaining)
        except queue.Empty as error:
            raise AppServerReadError("App Server response timed out") from error
        if message.get("id") == identifier:
            if "error" in message:
                raise AppServerReadError("App Server rejected the read request")
            return message


def read_rate_limits_from_app_server(executable: str) -> Mapping[str, Any]:
    """Issue only `initialize`, `initialized`, and `account/rateLimits/read` over stdio."""
    try:
        process = subprocess.Popen(
            [executable, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
    except OSError as error:
        raise AppServerReadError("Unable to start Codex App Server") from error

    messages: queue.Queue[dict[str, Any]] = queue.Queue()

    def receive() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                messages.put(parsed)

    thread = threading.Thread(target=receive, daemon=True)
    thread.start()

    def send(message: Mapping[str, Any]) -> None:
        if process.stdin is None:
            raise AppServerReadError("App Server input is unavailable")
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    try:
        send({"method": "initialize", "id": 0, "params": {"clientInfo": {
            "name": "codex_usage_monitor",
            "title": "Codex Usage Monitor",
            "version": "0.1.0",
        }}})
        _wait_for_message(messages, 0, APP_SERVER_TIMEOUT_SECONDS)
        send({"method": "initialized", "params": {}})
        send({"method": "account/rateLimits/read", "id": 1, "params": {}})
        response = _wait_for_message(messages, 1, APP_SERVER_TIMEOUT_SECONDS)
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise AppServerReadError("App Server returned an invalid rate-limit response")
        return result
    except (BrokenPipeError, OSError, ValueError) as error:
        raise AppServerReadError("Unable to read Codex rate limits") from error
    finally:
        if process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


class UsageReader:
    """Safe facade returning a snapshot rather than propagating environment failures."""

    def __init__(
        self,
        detector: Callable[[], CodexInstallation] = detect_codex,
        rate_limit_reader: Callable[[str], Mapping[str, Any]] = read_rate_limits_from_app_server,
    ) -> None:
        self._detector = detector
        self._rate_limit_reader = rate_limit_reader

    def read_usage(self) -> UsageSnapshot:
        captured_at = datetime.now(timezone.utc)
        try:
            installation = self._detector()
            if not installation.cli_path:
                return unavailable_snapshot(captured_at)
            payload = self._rate_limit_reader(installation.cli_path)
            return parse_rate_limit_payload(payload, timestamp=datetime.now(timezone.utc))
        except (AppServerReadError, OSError, PermissionError, ValueError, json.JSONDecodeError):
            return unavailable_snapshot(captured_at)
        except Exception:
            # The GUI/CLI caller must never be taken down by unexpected local changes.
            return UsageSnapshot(
                **{**unavailable_snapshot(captured_at).__dict__, "status": SnapshotStatus.UNAVAILABLE,
                 "source": DataSource.UNKNOWN}
            )


def read_usage() -> UsageSnapshot:
    """Read the current official Codex rate limits, or a safe unavailable snapshot."""
    return UsageReader().read_usage()
