"""Focused tests for TracePlugin behavior."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from stoner_measurement.plugins.trace import TracePlugin, TraceStatus


class _SimpleTrace(TracePlugin):
    """Minimal TracePlugin that yields a fixed number of (i, i^2) points."""

    @property
    def name(self) -> str:
        return "SimpleTrace"

    def execute(
        self, parameters: dict[str, Any]
    ) -> Generator[tuple[float, float]]:
        n = int(parameters.get("n", 5))
        for i in range(n):
            yield float(i), float(i * i)


class TestTracePlugin:
    def test_plugin_type(self, qapp):
        p = _SimpleTrace()
        assert p.plugin_type == "trace"

    def test_channel_names_default(self, qapp):
        p = _SimpleTrace()
        assert p.channel_names == ["SimpleTrace"]

    def test_x_label_default(self, qapp):
        assert _SimpleTrace().x_label == "x"

    def test_y_label_default(self, qapp):
        assert _SimpleTrace().y_label == "y"

    def test_execute_yields_tuples(self, qapp):
        p = _SimpleTrace()
        pts = list(p.execute({"n": 4}))
        assert len(pts) == 4
        for x, y in pts:
            assert isinstance(x, float)
            assert isinstance(y, float)

    def test_execute_values(self, qapp):
        p = _SimpleTrace()
        pts = list(p.execute({"n": 3}))
        assert pts == [(0.0, 0.0), (1.0, 1.0), (2.0, 4.0)]

    def test_execute_multichannel_default_wraps_execute(self, qapp):
        p = _SimpleTrace()
        pts = list(p.execute_multichannel({"n": 3}))
        assert len(pts) == 3
        assert all(ch == "SimpleTrace" for ch, _, _ in pts)
        assert [(x, y) for _, x, y in pts] == [(0.0, 0.0), (1.0, 1.0), (2.0, 4.0)]

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

    def test_data_attribute_initially_empty(self, qapp):
        p = _SimpleTrace()
        assert p.data == {}

    def test_data_attribute_populated_after_measure(self, qapp):
        import numpy as np

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
        import numpy as np

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

    def test_measure_returns_complete_list(self, qapp):
        """measure() must return a dict mapping channel to TraceData."""
        import numpy as np
        import pandas as pd

        p = _SimpleTrace()
        result = p.measure({"n": 5})
        assert isinstance(result, dict)
        td = result["SimpleTrace"]
        assert len(td.x) == 5
        assert isinstance(td.x, np.ndarray)
        assert isinstance(td.df, pd.DataFrame)
        assert p.status is TraceStatus.DATA_AVAILABLE

    def test_num_traces_default_one(self, qapp):
        assert _SimpleTrace().num_traces == 1

    def test_trace_title_default_is_name(self, qapp):
        p = _SimpleTrace()
        assert p.trace_title == p.name

    def test_x_units_default_empty(self, qapp):
        assert _SimpleTrace().x_units == ""

    def test_y_units_default_empty(self, qapp):
        assert _SimpleTrace().y_units == ""

    def test_trace_scan_alias_for_scan_generator(self, qapp):
        p = _SimpleTrace()
        assert p.trace_scan is p.scan_generator

    def test_num_traces_reflects_channel_count(self, qapp):
        class _TwoChannel(_SimpleTrace):
            @property
            def channel_names(self):
                return ["ch1", "ch2"]

        p = _TwoChannel()
        assert p.num_traces == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
