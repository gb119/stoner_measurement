"""Tests for shared controller-connection widget styling."""

from __future__ import annotations

import pytest
from qtpy.QtWidgets import QLabel

from stoner_measurement.ui.theme import contrast_ratio, contrasting_text_colour
from stoner_measurement.ui.widgets.controller_connection import _set_widget_background
from stoner_measurement.ui.widgets.visa_resource_widget import VisaResourceStatus


@pytest.mark.parametrize(
    ("status", "background"),
    [
        (VisaResourceStatus.CONNECTING, "#fff3cd"),
        (VisaResourceStatus.CONNECTED, "#90ee90"),
        (VisaResourceStatus.ERROR, "#f8d7da"),
    ],
)
def test_status_backgrounds_use_contrasting_text(qapp, status, background):
    label = QLabel("Connection address")

    _set_widget_background(label, status)

    stylesheet = label.styleSheet()
    foreground = contrasting_text_colour(background)
    assert f"background-color: {background}" in stylesheet
    assert f"color: {foreground}" in stylesheet
    assert contrast_ratio(foreground, background) >= 4.5


def test_disconnected_status_restores_palette_styling(qapp):
    label = QLabel("Connection address")
    _set_widget_background(label, VisaResourceStatus.CONNECTED)

    _set_widget_background(label, VisaResourceStatus.DISCONNECTED)

    assert label.styleSheet() == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
