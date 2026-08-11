"""Focused tests for TracePlugin behavior."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
from qtpy.QtCore import Qt

from stoner_measurement.core import COLUMN_ROLE_Y, TraceData
from stoner_measurement.plugins.trace import TracePlugin, TraceStatus


class _SimpleTrace(TracePlugin):
    """Minimal TracePlugin that returns a fixed complete trace."""

    @property
    def name(self) -> str:
        return "SimpleTrace"

    def _measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        n = int(parameters.get("n", 5))
        x = np.arange(n, dtype=float)
        frame = pd.DataFrame({"y": x**2}, index=pd.Index(x, name="x"))
        return {
            self.name: TraceData(
                frame,
                column_roles={"y": COLUMN_ROLE_Y},
                names={"x": "x", "y": "y"},
                units={"x": "", "y": ""},
            )
        }


class TestTracePlugin:
    def test_plugin_type(self, qapp):
        p = _SimpleTrace()
        assert p.plugin_type == "trace"

    def test_trace_names_default(self, qapp):
        p = _SimpleTrace()
        assert p.trace_names == ["SimpleTrace"]

    def test_x_label_default(self, qapp):
        assert _SimpleTrace().x_label == "x"

    def test_y_label_default(self, qapp):
        assert _SimpleTrace().y_label == "y"

    def test_config_widget_default(self, qapp):
        from qtpy.QtWidgets import QWidget

        p = _SimpleTrace()
        w = p.config_widget()
        assert isinstance(w, QWidget)

    def test_monitor_widget_default_none(self, qapp):
        assert _SimpleTrace().monitor_widget() is None

    def test_scan_generator_attribute(self, qapp):
        from stoner_measurement.scan import FunctionScanGenerator

        p = _SimpleTrace()
        assert isinstance(p.scan_generator, FunctionScanGenerator)

    def test_config_tabs_scan_tab_is_first(self, qapp):
        p = _SimpleTrace()
        tabs = p.config_tabs()
        assert len(tabs) >= 2
        assert "Scan" in tabs[0][0]
        assert "Type" not in tabs[0][0]

    def test_config_tabs_settings_tab_is_second(self, qapp):
        p = _SimpleTrace()
        tabs = p.config_tabs()
        assert "Settings" in tabs[1][0]

    def test_scan_page_contains_generator_type_selector(self, qapp):
        """Generator type selector is embedded in the Scan page."""
        from qtpy.QtWidgets import QComboBox

        p = _SimpleTrace()
        tabs = p.config_tabs()
        scan_page = tabs[0][1]
        combos = scan_page.findChildren(QComboBox)
        assert len(combos) >= 1

    def test_scan_page_uses_humanised_generator_names(self, qapp):
        from qtpy.QtWidgets import QComboBox

        p = _SimpleTrace()
        scan_page = p.config_tabs()[0][1]
        combo = next(iter(scan_page.findChildren(QComboBox)), None)

        assert combo is not None
        labels = [combo.itemText(i) for i in range(combo.count())]
        assert "Function Scan Generator" in labels
        assert "Ramp Scan Generator" in labels
        assert "Arbitrary Function Scan Generator" in labels

    def test_scan_page_contains_comment_editor(self, qapp):
        from qtpy.QtWidgets import QLabel, QLineEdit

        p = _SimpleTrace()
        scan_page = p.config_tabs()[0][1]
        comment_label = next(
            label for label in scan_page.findChildren(QLabel) if label.text() == "Comment:"
        )
        assert comment_label is not None
        edits = scan_page.findChildren(QLineEdit)
        assert len(edits) >= 2

    def test_scan_page_does_not_show_plugin_type(self, qapp):
        from qtpy.QtWidgets import QLabel

        p = _SimpleTrace()
        scan_page = p.config_tabs()[0][1]
        labels = [label.text() for label in scan_page.findChildren(QLabel)]
        assert "Plugin type:" not in labels

    def test_config_tabs_scan_widget_is_qwidget(self, qapp):
        from qtpy.QtWidgets import QWidget

        p = _SimpleTrace()
        tabs = p.config_tabs()
        assert isinstance(tabs[0][1], QWidget)

    def test_set_scan_generator_class(self, qapp):
        from stoner_measurement.scan import SteppedScanGenerator

        p = _SimpleTrace()
        p.set_scan_generator_class(SteppedScanGenerator)
        assert isinstance(p.scan_generator, SteppedScanGenerator)

    def test_scan_generator_class_list_includes_new_generators(self, qapp):
        from stoner_measurement.scan import (
            ArbitraryFunctionScanGenerator,
            RampScanGenerator,
        )

        p = _SimpleTrace()
        assert RampScanGenerator in p._scan_generator_classes
        assert ArbitraryFunctionScanGenerator in p._scan_generator_classes

    def test_scan_generator_changed_emitted(self, qapp):
        from stoner_measurement.scan import SteppedScanGenerator

        p = _SimpleTrace()
        received = []
        p.scan_generator_changed.connect(lambda: received.append(True))
        p.set_scan_generator_class(SteppedScanGenerator)
        assert len(received) == 1

    def test_scan_tab_container_refreshes_on_change(self, qapp):
        from qtpy.QtWidgets import QWidget

        from stoner_measurement.plugins.trace import _ScanTabContainer
        from stoner_measurement.scan import SteppedScanGenerator

        p = _SimpleTrace()
        container = _ScanTabContainer(p)
        p.set_scan_generator_class(SteppedScanGenerator)
        assert isinstance(container, QWidget)

    def test_scan_page_and_generator_container_pack_contents_at_top(self, qapp):
        from stoner_measurement.plugins.trace import _ScanTabContainer
        from stoner_measurement.scan import ListScanGenerator

        p = _SimpleTrace()
        p.set_scan_generator_class(ListScanGenerator)
        scan_page = p.config_tabs()[0][1]
        scan_container = scan_page.findChild(_ScanTabContainer)

        assert scan_page.layout().alignment() & Qt.AlignmentFlag.AlignTop
        assert scan_container is not None
        assert scan_container.layout().alignment() & Qt.AlignmentFlag.AlignTop

    def test_statistics_switch_is_immediately_above_scan_generator(self, qapp):
        from qtpy.QtWidgets import QWidget

        from stoner_measurement.plugins.trace import _ScanTabContainer

        p = _SimpleTrace()
        scan_page = p.config_tabs()[0][1]
        statistics = scan_page.findChild(QWidget, "trace_statistics_options")
        scan_container = scan_page.findChild(_ScanTabContainer)
        layout = scan_page.layout()

        assert statistics is not None
        assert scan_container is not None
        assert layout.indexOf(statistics) + 1 == layout.indexOf(scan_container)

    def test_data_attribute_initially_empty(self, qapp):
        p = _SimpleTrace()
        assert p.data == {}

    def test_data_attribute_populated_after_measure(self, qapp):
        p = _SimpleTrace()
        result = p.measure({"n": 4})
        assert p.data is result
        assert list(p.data.keys()) == ["SimpleTrace"]
        td = p.data["SimpleTrace"]
        assert isinstance(td.x, np.ndarray)
        assert isinstance(td.y, np.ndarray)
        assert len(td.x) == 4

    def test_status_initial_idle(self, qapp):
        p = _SimpleTrace()
        assert p.status is TraceStatus.IDLE

    def test_status_changed_signal(self, qapp):
        p = _SimpleTrace()
        received = []
        p.status_changed.connect(received.append)
        p._set_status(TraceStatus.MEASURING)
        assert received == [TraceStatus.MEASURING]

    def test_status_changed_not_emitted_when_same(self, qapp):
        p = _SimpleTrace()
        received = []
        p.status_changed.connect(received.append)
        p._set_status(TraceStatus.IDLE)
        assert received == []

    def test_set_status_updates_status(self, qapp):
        p = _SimpleTrace()
        p._set_status(TraceStatus.CONFIGURING)
        assert p.status is TraceStatus.CONFIGURING

    def test_connect_default_noop(self, qapp):
        p = _SimpleTrace()
        p.connect()
        assert p.status is TraceStatus.IDLE

    def test_configure_default_noop(self, qapp):
        p = _SimpleTrace()
        p.configure()

    def test_disconnect_resets_status_to_idle(self, qapp):
        p = _SimpleTrace()
        p._set_status(TraceStatus.DATA_AVAILABLE)
        p.disconnect()
        assert p.status is TraceStatus.IDLE

    def test_measure_returns_channel_x_y_triples(self, qapp):
        p = _SimpleTrace()
        result = p.measure({"n": 3})
        assert isinstance(result, dict)
        assert list(result.keys()) == ["SimpleTrace"]
        td = result["SimpleTrace"]
        assert isinstance(td.x, np.ndarray)
        assert isinstance(td.y, np.ndarray)
        assert len(td.x) == 3
        assert len(td.y) == 3

    def test_measure_status_is_measuring_during_acquisition(self, qapp):
        p = _SimpleTrace()
        statuses_during: list[TraceStatus] = []
        p.status_changed.connect(statuses_during.append)
        p.measure({"n": 2})
        assert statuses_during[0] is TraceStatus.MEASURING

    def test_measure_status_data_available_after_completion(self, qapp):
        p = _SimpleTrace()
        p.measure({"n": 2})
        assert p.status is TraceStatus.DATA_AVAILABLE

    def test_measure_failure_sets_error_and_clears_stale_data(self, qapp):
        class _FailingTrace(_SimpleTrace):
            def _measure(self, parameters):
                del parameters
                raise RuntimeError("acquisition failed")

        p = _FailingTrace()
        p.data = {"stale": TraceData()}
        with pytest.raises(RuntimeError, match="acquisition failed"):
            p.measure({})
        assert p.status is TraceStatus.ERROR
        assert p.data == {}

    def test_measure_returns_complete_list(self, qapp):
        """measure() must return a dict mapping channel to TraceData."""
        p = _SimpleTrace()
        result = p.measure({"n": 5})
        assert isinstance(result, dict)
        td = result["SimpleTrace"]
        assert len(td.x) == 5
        assert isinstance(td.x, np.ndarray)
        assert isinstance(td.df, pd.DataFrame)
        assert p.status is TraceStatus.DATA_AVAILABLE

    def test_x_units_default_empty(self, qapp):
        assert _SimpleTrace().x_units == ""

    def test_y_units_default_empty(self, qapp):
        assert _SimpleTrace().y_units == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
