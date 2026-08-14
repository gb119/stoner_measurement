"""Focused tests for the X-ray control panel and live geometry synoptic."""

from __future__ import annotations

from dataclasses import replace

import pytest
from qtpy.QtCore import QPointF
from qtpy.QtGui import QFont

from stoner_measurement.ui.widgets import VisaResourceStatus
from stoner_measurement.ui.xray_panel import XrayControlPanel
from stoner_measurement.xray_control import XrayControllerEngine, XrayMotionMode


@pytest.fixture
def panel(monkeypatch, managed_qt_widget):
    engine = XrayControllerEngine()
    monkeypatch.setattr(XrayControllerEngine, "_singleton", engine)
    widget = managed_qt_widget(XrayControlPanel())
    yield widget
    engine.shutdown()


def test_simulated_connection_updates_live_snapshot_and_synoptic(panel):
    panel._transport_combo.setCurrentText("Simulated")  # noqa: SLF001
    panel._on_connect()  # noqa: SLF001
    panel._engine.connected_driver.motion_time_scale = 0.0  # type: ignore[union-attr]  # noqa: SLF001
    panel._motion_enabled.setChecked(True)  # noqa: SLF001
    panel._mode_combo.setCurrentIndex(  # noqa: SLF001
        panel._mode_combo.findData(XrayMotionMode.COUPLED)  # noqa: SLF001
    )
    panel._offset_spin.setValue(1.0)  # noqa: SLF001
    panel._apply_motion_configuration()  # noqa: SLF001

    state = panel._engine.move_to(20.0)  # noqa: SLF001
    panel._on_state_updated(state)  # noqa: SLF001

    assert panel._theta_label.text() == "20.0000 deg"  # noqa: SLF001
    assert panel._two_theta_label.text() == "41.0000 deg"  # noqa: SLF001
    assert panel._geometry._theta_deg == pytest.approx(20.0)  # noqa: SLF001
    assert panel._geometry._two_theta_deg == pytest.approx(41.0)  # noqa: SLF001
    assert not panel._geometry.grab().isNull()  # noqa: SLF001


def test_panel_exposes_three_motion_sets(panel):
    assert [panel._mode_combo.itemData(index) for index in range(3)] == [  # noqa: SLF001
        XrayMotionMode.THETA,
        XrayMotionMode.COUPLED,
        XrayMotionMode.TWO_THETA,
    ]


def test_connection_tab_exposes_instruments_and_colours_device_status(panel):
    assert [
        panel._instrument_combo.itemText(index)  # noqa: SLF001
        for index in range(panel._instrument_combo.count())  # noqa: SLF001
    ] == ["Wharfdale", "Simulated"]

    panel._instrument_combo.setCurrentText("Simulated")  # noqa: SLF001
    assert panel._address_edit.text() == "Built-in simulator"  # noqa: SLF001
    assert panel._address_edit.isReadOnly()  # noqa: SLF001
    panel._on_connect()  # noqa: SLF001
    assert panel._address_edit.status is VisaResourceStatus.CONNECTED  # noqa: SLF001


def test_connection_tab_exposes_live_polling_rate(panel):
    panel._polling_rate_spin.setValue(2.5)  # noqa: SLF001

    assert panel._engine.polling_rate_hz == pytest.approx(2.5)  # noqa: SLF001


def test_panel_count_time_tracks_engine_overrides_and_restoration(panel):
    panel._engine.set_count_duration(3.25)  # noqa: SLF001
    assert panel._duration_spin.value() == pytest.approx(3.25)  # noqa: SLF001

    panel._engine.set_count_duration(1.5)  # noqa: SLF001
    assert panel._duration_spin.value() == pytest.approx(1.5)  # noqa: SLF001


def test_synoptic_status_and_hide_action(panel):
    panel._instrument_combo.setCurrentText("Simulated")  # noqa: SLF001
    panel._on_connect()  # noqa: SLF001
    panel._engine.connected_driver.motion_time_scale = 0.0  # type: ignore[union-attr]  # noqa: SLF001
    panel._motion_enabled.setChecked(True)  # noqa: SLF001
    panel._apply_motion_configuration()  # noqa: SLF001

    state = panel._engine.move_to(2.0)  # noqa: SLF001
    panel._on_state_updated(state)  # noqa: SLF001

    assert "At target: yes" in panel._synoptic_at_target_label.text()  # noqa: SLF001
    assert "theta=1" in panel._synoptic_speed_label.text()  # noqa: SLF001
    assert "2-theta=2" in panel._synoptic_speed_label.text()  # noqa: SLF001
    panel.show()
    panel._hide_button.click()  # noqa: SLF001
    assert not panel.isVisible()


def test_synoptic_shows_latest_count_rate_in_top_right(panel):
    geometry = panel._geometry  # noqa: SLF001
    geometry.resize(500, 320)
    state = replace(panel._engine.get_engine_state(), count_rate_hz=1234.567)  # noqa: SLF001
    panel._on_state_updated(state)  # noqa: SLF001

    frame = geometry._count_rate_frame  # noqa: SLF001
    assert geometry._count_rate_value.text() == "1235"  # noqa: SLF001
    assert frame.x() == geometry.width() - frame.width() - 8
    assert frame.y() == 8


def test_positive_two_theta_draws_detector_clockwise_below_straight_through(panel):
    geometry = panel._geometry  # noqa: SLF001
    geometry.set_geometry(theta_deg=10.0, two_theta_deg=20.0, offset_deg=0.0)
    centre = QPointF(100.0, 100.0)

    detector = geometry._detector_position(centre, 50.0)  # noqa: SLF001

    assert detector.x() > centre.x()
    assert detector.y() > centre.y()


def test_synoptic_font_tracks_application_font_plus_two_points(panel):
    application_font = QFont(panel._geometry.font())  # noqa: SLF001
    application_font.setPointSizeF(11.0)
    panel._geometry.setFont(application_font)  # noqa: SLF001

    assert panel._geometry._synoptic_font().pointSizeF() == pytest.approx(13.0)  # noqa: SLF001


def test_synoptic_sample_is_half_the_original_length(panel):
    assert panel._geometry._SAMPLE_HALF_LENGTH == pytest.approx(21.0)  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
