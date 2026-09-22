"""Local, non-sensitive settings for the history recorder."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DATA_ROOT = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "CodexUsageMonitor"
    if getattr(sys, "frozen", False)
    else PROJECT_ROOT
)
DEFAULT_SETTINGS_PATH = APP_DATA_ROOT / "config" / "settings.json"


@dataclass(frozen=True)
class RecordingSettings:
    """Recorder settings. Any positive whole-minute custom interval is valid."""

    enabled: bool = True
    interval_minutes: int = 5

    def __post_init__(self) -> None:
        if self.interval_minutes <= 0:
            raise ValueError("interval_minutes must be positive")


class SettingsStore:
    """Own only this application's settings file; never reads Codex settings."""

    def __init__(self, path: Path = DEFAULT_SETTINGS_PATH) -> None:
        self.path = path

    def load_recording_settings(self) -> RecordingSettings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            recording = payload["recording"]
            enabled = recording["enabled"]
            interval = recording["interval_minutes"]
            if not isinstance(enabled, bool) or isinstance(interval, bool) or not isinstance(interval, int):
                raise ValueError("invalid recording settings types")
            return RecordingSettings(enabled=enabled, interval_minutes=interval)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return RecordingSettings()

    def save_recording_settings(self, settings: RecordingSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "recording": {
                "enabled": settings.enabled,
                "interval_minutes": settings.interval_minutes,
            }
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
