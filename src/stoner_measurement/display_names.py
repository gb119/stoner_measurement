"""Helpers for deriving human-friendly class display names."""

from __future__ import annotations

import re
from collections.abc import Sequence

_DISPLAY_NAME_FIRST_PASS = re.compile(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[A-Z])(?=[A-Z][a-z])")
_DISPLAY_NAME_SECOND_PASS = re.compile(r"(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])")


def class_display_name(cls: type, explicit_attr_names: Sequence[str] = ("DISPLAY_NAME",)) -> str:
    """Return a human-friendly label for *cls*.

    Args:
        cls (type):
            Class whose name should be converted for display.
        explicit_attr_names (Sequence[str]):
            Ordered class attributes to check first for an explicit display
            label before falling back to splitting the class name.

    Returns:
        (str):
            Human-friendly label suitable for UI picker text.
    """
    for attr_name in explicit_attr_names:
        explicit = getattr(cls, attr_name, None)
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
    label = _DISPLAY_NAME_FIRST_PASS.sub(" ", cls.__name__).strip()
    label = _DISPLAY_NAME_SECOND_PASS.sub(" ", label)
    return " ".join(label.split())
