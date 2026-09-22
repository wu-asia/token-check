"""Windows desktop entry point used by the PyInstaller build."""

from ui.main_window import run


if __name__ == "__main__":
    raise SystemExit(run())
