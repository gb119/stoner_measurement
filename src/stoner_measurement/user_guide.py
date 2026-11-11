"""Open the packaged Windows user guide without requiring network access."""

from __future__ import annotations

import hashlib
import importlib.resources
import os
import sys

from platformdirs import user_cache_path

HELP_FILENAME = "stoner_measurement.chm"


def open_user_guide() -> None:
    """Open the bundled CHM, raising OSError when it is unavailable.

    Keep a content-addressed local copy alive after launching the external
    viewer, including when package resources come from a temporary extraction.
    """
    if sys.platform != "win32":
        raise OSError("The compiled User Guide requires Windows.")
    resource = importlib.resources.files("stoner_measurement").joinpath("help", HELP_FILENAME)
    if not resource.is_file():
        raise FileNotFoundError(
            "This installation does not include the compiled User Guide. "
            "Install an application package built with the CHM documentation."
        )
    content = resource.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    directory = user_cache_path("stoner_measurement", appauthor=False) / "help" / digest
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / HELP_FILENAME
    if not target.is_file() or target.read_bytes() != content:
        target.write_bytes(content)
    os.startfile(str(target))
