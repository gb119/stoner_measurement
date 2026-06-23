"""Helpers for creating OS launcher entries for Stoner Measurement."""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from importlib import resources
except ImportError:  # pragma: no cover
    import importlib_resources as resources  # type: ignore[import-not-found]


APP_NAME = "Stoner Measurement"
LINUX_DESKTOP_FILENAME = "stoner-measurement.desktop"


def _icon_path() -> Path:
    """Return a filesystem path to the packaged application icon."""
    resource = resources.files("stoner_measurement.ui").joinpath("StonerLogo2.png")
    with resources.as_file(resource) as path:
        return path


def _desktop_entry_text() -> str:
    """Build the freedesktop .desktop file content."""
    python_exe = Path(sys.executable)
    module_cmd = f'"{python_exe}" -m stoner_measurement.main'
    icon = _icon_path()
    return "\n".join(
        [
            "[Desktop Entry]",
            "Version=1.0",
            "Type=Application",
            f"Name={APP_NAME}",
            "Comment=Run the Stoner Measurement application",
            f"Exec={module_cmd}",
            f"Icon={icon}",
            "Terminal=false",
            "Categories=Science;",
            "StartupNotify=true",
            "",
        ]
    )


def install_linux_menu_entry(target_dir: str | os.PathLike[str] | None = None) -> Path:
    """Create a Linux desktop entry in the applications menu directory.

    Args:
        target_dir: Optional destination directory. Defaults to
            ~/.local/share/applications.

    Returns:
        Path to the created .desktop file.
    """
    if target_dir is None:
        target = Path.home() / ".local" / "share" / "applications"
    else:
        target = Path(target_dir)

    target.mkdir(parents=True, exist_ok=True)
    desktop_file = target / LINUX_DESKTOP_FILENAME
    desktop_file.write_text(_desktop_entry_text(), encoding="utf-8")
    desktop_file.chmod(0o755)
    return desktop_file


def main() -> int:
    """CLI entry point for desktop integration helpers."""
    if sys.platform.startswith("linux"):
        path = install_linux_menu_entry()
        print(f"Created menu entry: {path}")
        return 0

    print(
        "Automatic menu-entry creation is currently implemented for Linux desktop environments. "
        "For conda installs on Windows, the package recipe provides a Start Menu shortcut."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())