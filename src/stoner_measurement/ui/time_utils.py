"""Helpers for formatting user-visible timestamps."""

from __future__ import annotations

from datetime import datetime

from qtpy.QtCore import QLocale, QTime


def format_local_time(value: datetime) -> str:
    """Return a locale-aware time-only string for a user-visible timestamp."""
    time_value = value.timetz().replace(tzinfo=None)
    qt_time = QTime(time_value.hour, time_value.minute, time_value.second)
    rendered = QLocale.system().toString(qt_time, QLocale.FormatType.ShortFormat)
    if rendered:
        return rendered
    return time_value.isoformat(timespec="seconds")
