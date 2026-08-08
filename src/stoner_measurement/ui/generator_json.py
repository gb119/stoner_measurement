"""Shared JSON file-dialog helpers for scan and sweep configuration widgets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qtpy.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QWidget,
)

_JSON_FILTER = "JSON files (*.json);;All files (*)"


def set_generator_file_button_icons(
    owner: QWidget,
    new_button: QPushButton,
    load_button: QPushButton,
    save_button: QPushButton,
) -> None:
    """Apply Qt's platform-standard document, open, and save icons."""
    style = owner.style()
    new_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileIcon))
    load_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
    save_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
    for button, label in (
        (new_button, "New/Clear"),
        (load_button, "Load"),
        (save_button, "Save"),
    ):
        button.setText("")
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


def load_generator_json(parent: QWidget, caption: str) -> dict[str, Any] | None:
    """Ask the user for a JSON file and return its top-level object."""
    filename, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        caption,
        "",
        _JSON_FILTER,
    )
    if not filename:
        return None
    try:
        data = json.loads(Path(filename).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("The JSON file must contain an object at its top level.")
    except (OSError, ValueError) as exc:
        QMessageBox.warning(parent, "Unable to load configuration", str(exc))
        return None
    return data


def save_generator_json(parent: QWidget, caption: str, data: dict[str, Any]) -> bool:
    """Ask the user for a destination and write *data* as formatted JSON."""
    filename, _selected_filter = QFileDialog.getSaveFileName(
        parent,
        caption,
        "",
        _JSON_FILTER,
    )
    if not filename:
        return False
    path = Path(filename)
    if path.suffix.lower() != ".json":
        path = path.with_suffix(".json")
    try:
        path.write_text(f"{json.dumps(data, indent=2, sort_keys=True)}\n", encoding="utf-8")
    except OSError as exc:
        QMessageBox.warning(parent, "Unable to save configuration", str(exc))
        return False
    return True
