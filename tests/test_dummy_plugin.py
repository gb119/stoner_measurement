"""Tests for the DummyPlugin."""

from __future__ import annotations

import math

import numpy as np
import pytest

from stoner_measurement.plugins.trace import DummyPlugin
from stoner_measurement.plugins.trace import TraceStatus
from stoner_measurement.scan import SteppedScanGenerator


def _make_scan(plugin, end=0.4, step=0.1):
    """Return a SteppedScanGenerator with one stage and assign it to *plugin*."""
    gen = SteppedScanGenerator(
        start=0.0, stages=[(end, step, True)], parent=plugin
    )
    plugin.scan_generator = gen
    return gen


class TestDummyPlugin:
    def test_name(self):
        plugin = DummyPlugin()
        assert plugin.name == "Dummy"

    def test_execute_uses_scan_generator(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)  # 5 points: 0.0…0.4
        data = list(plugin.execute({}))
        assert len(data) == 5

    def test_execute_empty_scan_yields_start_point(self, qapp):
        plugin = DummyPlugin()
        # Default scan generator has no stages but still yields the start point (0.0)
        data = list(plugin.execute({}))
        assert len(data) == 1
        assert data[0][0] == 0.0  # start point

    def test_execute_only_measured_points_yielded(self, qapp):
        plugin = DummyPlugin()
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(0.2, 0.1, False), (0.4, 0.1, True)],
            parent=plugin,
        )
        plugin.scan_generator = gen
        data = list(plugin.execute({}))
        xs = [x for x, _ in data]
        # Positioning stage (0.0→0.2) not measured; measuring stage (0.2→0.4) is
        assert all(x > 0.19 for x in xs)

    def test_execute_yields_tuples(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)
        data = list(plugin.execute({}))
        for item in data:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_execute_amplitude(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)
        # Default I_c=1.0 > all scan points (0…0.4), so all V must be 0
        data = list(plugin.execute({}))
        for _i, v in data:
            assert v == 0.0

    def test_execute_rsj_values(self, qapp):
        plugin = DummyPlugin()
        # I_c=1.0, R_n=1.0; scan: 0, 1, 2  (start=0, stage end=2, step=1)
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(2.0, 1.0, True)],
            parent=plugin,
        )
        plugin.scan_generator = gen
        data = list(plugin.execute({"I_c": "1.0", "R_n": "1.0"}))
        assert len(data) == 3
        i_vals = [i for i, _v in data]
        v_vals = [v for _i, v in data]
        # I=0: |0|<1 → V=0
        assert abs(v_vals[0]) < 1e-9
        # I=1: |1|==I_c → V=sign(1)*1*sqrt(1-1)=0
        assert abs(v_vals[1]) < 1e-9
        # I=2: |2|>1 → V=1*sqrt(4-1)=sqrt(3)
        assert abs(v_vals[2] - math.sqrt(3)) < 1e-9
        assert i_vals == pytest.approx([0.0, 1.0, 2.0])

    def test_config_tabs_returns_three_tabs(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        assert len(tabs) == 3

    def test_config_tabs_titles(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        titles = [t for t, _ in tabs]
        assert titles == [
            "Dummy \u2013 Scan",
            "Dummy \u2013 Settings",
            "Dummy \u2013 About",
        ]

    def test_config_tabs_widgets_are_qwidgets(self, qapp):
        from PyQt6.QtWidgets import QWidget
        plugin = DummyPlugin()
        for _title, widget in plugin.config_tabs():
            assert isinstance(widget, QWidget)

    def test_config_tabs_caches_widgets(self, qapp):
        """Subsequent calls to config_tabs() return the same widget instances."""
        plugin = DummyPlugin()
        tabs1 = plugin.config_tabs()
        tabs2 = plugin.config_tabs()
        for (t1, w1), (t2, w2) in zip(tabs1, tabs2):
            assert t1 == t2
            assert w1 is w2

    def test_monitor_widget_returns_none(self):
        plugin = DummyPlugin()
        assert plugin.monitor_widget() is None

    def test_has_scan_generator(self, qapp):
        plugin = DummyPlugin()
        assert isinstance(plugin.scan_generator, SteppedScanGenerator)

    def test_scan_tab_is_first(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        assert "Scan" in tabs[0][0]
        assert "Type" not in tabs[0][0]

    def test_scan_tab_widget_is_qwidget(self, qapp):
        from PyQt6.QtWidgets import QWidget
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        assert isinstance(tabs[0][1], QWidget)

    def test_about_tab_is_third(self, qapp):
        plugin = DummyPlugin()
        tabs = plugin.config_tabs()
        assert "About" in tabs[2][0]

    def test_about_html_returns_string(self, qapp):
        plugin = DummyPlugin()
        html = plugin._about_html()
        assert isinstance(html, str)
        assert "<h3>" in html

    def test_plugin_config_tabs_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget
        plugin = DummyPlugin()
        assert isinstance(plugin._plugin_config_tabs(), QWidget)

    def test_set_scan_generator_class(self, qapp):
        from stoner_measurement.scan import FunctionScanGenerator
        plugin = DummyPlugin()
        plugin.set_scan_generator_class(FunctionScanGenerator)
        assert isinstance(plugin.scan_generator, FunctionScanGenerator)

    def test_set_scan_generator_class_noop_if_same(self, qapp):
        plugin = DummyPlugin()
        gen_before = plugin.scan_generator
        plugin.set_scan_generator_class(SteppedScanGenerator)
        assert plugin.scan_generator is gen_before

    def test_scan_generator_changed_signal(self, qapp):
        from stoner_measurement.scan import FunctionScanGenerator
        plugin = DummyPlugin()
        received = []
        plugin.scan_generator_changed.connect(lambda: received.append(True))
        plugin.set_scan_generator_class(FunctionScanGenerator)
        assert len(received) == 1

    # ------------------------------------------------------------------
    # Lifecycle API
    # ------------------------------------------------------------------

    def test_connect_sets_idle_status(self, qapp):
        plugin = DummyPlugin()
        plugin.connect()
        assert plugin.status is TraceStatus.IDLE

    def test_configure_is_noop(self, qapp):
        plugin = DummyPlugin()
        plugin.configure()  # should not raise

    def test_disconnect_sets_idle_status(self, qapp):
        plugin = DummyPlugin()
        plugin._set_status(TraceStatus.DATA_AVAILABLE)
        plugin.disconnect()
        assert plugin.status is TraceStatus.IDLE

    def test_measure_yields_data(self, qapp):
        import numpy as np

        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)
        result = plugin.measure({})
        assert isinstance(result, dict)
        assert list(result.keys()) == ["Dummy"]
        td = result["Dummy"]
        assert isinstance(td.x, np.ndarray)
        assert isinstance(td.y, np.ndarray)
        assert len(td.x) == 5
        assert len(td.y) == 5

    def test_measure_status_data_available_after_completion(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.2, step=0.1)
        plugin.measure({})
        assert plugin.status is TraceStatus.DATA_AVAILABLE

    # ------------------------------------------------------------------
    # Trace detail properties
    # ------------------------------------------------------------------

    def test_num_traces(self, qapp):
        assert DummyPlugin().num_traces == 1

    def test_trace_title(self, qapp):
        assert DummyPlugin().trace_title == "RSJ I-V"

    def test_x_units(self, qapp):
        assert DummyPlugin().x_units == "A"

    def test_y_units(self, qapp):
        assert DummyPlugin().y_units == "V"

    def test_trace_scan_is_scan_generator(self, qapp):
        plugin = DummyPlugin()
        assert plugin.trace_scan is plugin.scan_generator

    def test_x_label(self, qapp):
        assert DummyPlugin().x_label == "I"

    def test_y_label(self, qapp):
        assert DummyPlugin().y_label == "V"

    def test_default_noise_level(self, qapp):
        assert DummyPlugin()._noise_level == "0.0"

    def test_execute_zero_noise_is_exact(self, qapp):
        """V_n=0.0 must give exact RSJ values (no noise added)."""
        plugin = DummyPlugin()
        gen = SteppedScanGenerator(
            start=0.0, stages=[(2.0, 1.0, True)], parent=plugin
        )
        plugin.scan_generator = gen
        data = list(plugin.execute({"I_c": "1.0", "R_n": "1.0", "V_n": "0.0"}))
        v_vals = [v for _i, v in data]
        assert abs(v_vals[0]) < 1e-9       # I=0  → V=0
        assert abs(v_vals[1]) < 1e-9       # I=1  → V=0 (at I_c)
        assert abs(v_vals[2] - math.sqrt(3)) < 1e-9  # I=2 → sqrt(3)

    def test_execute_noise_shifts_voltages(self, qapp):
        """Non-zero V_n should produce voltages that differ from the noiseless values."""
        plugin = DummyPlugin()
        gen = SteppedScanGenerator(
            start=2.0, stages=[(2.0, 1.0, True)], parent=plugin
        )
        plugin.scan_generator = gen
        noiseless = list(plugin.execute({"I_c": 0.0, "R_n": 1.0, "V_n": "0.0"}))

        np.random.seed(0)
        noisy = list(plugin.execute({"I_c": 0.0, "R_n": 1.0, "V_n": "1.0"}))

        # With noise scale=1.0 (much larger than typical RSJ voltages) the
        # noisy and noiseless voltages should almost certainly differ.
        assert any(
            abs(nv - v) > 1e-12 for (_, nv), (_, v) in zip(noisy, noiseless)
        )

    def test_execute_noise_uses_v_n_parameter(self, qapp):
        """V_n passed in parameters overrides _noise_level attribute."""
        plugin = DummyPlugin()
        plugin._noise_level = "0.0"  # default noiseless
        gen = SteppedScanGenerator(
            start=2.0, stages=[(2.0, 1.0, True)], parent=plugin
        )
        plugin.scan_generator = gen
        np.random.seed(1)
        noisy = list(plugin.execute({"I_c": 0.0, "R_n": 1.0, "V_n": "100.0"}))
        # With V_n=100 V the noise dominates; voltages should not all be
        # exactly equal to the noiseless RSJ value (I=2 → V=2 for I_c=0).
        noiseless_v = 2.0
        assert any(abs(v - noiseless_v) > 1e-6 for _i, v in noisy)

    def test_default_normal_resistance(self, qapp):
        assert DummyPlugin()._normal_resistance == "1.0"

    def test_execute_negative_current_rsj(self, qapp):
        """RSJ output for negative currents should have negative voltage."""
        plugin = DummyPlugin()
        gen = SteppedScanGenerator(
            start=-2.0,
            stages=[(-0.0, 1.0, True)],
            parent=plugin,
        )
        plugin.scan_generator = gen
        data = list(plugin.execute({"I_c": "1.0", "R_n": "1.0"}))
        # I=-2: V = -sqrt(4-1) = -sqrt(3)
        i_neg2 = next((v for i, v in data if abs(i - (-2.0)) < 1e-9), None)
        assert i_neg2 is not None
        assert abs(i_neg2 - (-math.sqrt(3))) < 1e-9

    def test_execute_rsj_r_n_scaling(self, qapp):
        """Doubling R_n should double the voltage above I_c."""
        plugin = DummyPlugin()
        gen = SteppedScanGenerator(
            start=2.0,
            stages=[(2.0, 1.0, True)],
            parent=plugin,
        )
        plugin.scan_generator = gen
        data1 = list(plugin.execute({"I_c": "1.0", "R_n": "1.0"}))
        data2 = list(plugin.execute({"I_c": "1.0", "R_n": "2.0"}))
        assert abs(data2[0][1] - 2.0 * data1[0][1]) < 1e-9

    def test_eval_expr_uses_engine_when_attached(self, qapp):
        """When attached to a SequenceEngine, _eval_expr goes through self.eval()."""
        from stoner_measurement.core.sequence_engine import SequenceEngine
        plugin = DummyPlugin()
        engine = SequenceEngine()
        engine.add_plugin("dummy", plugin)
        try:
            # The engine namespace has numpy functions; 'sqrt(4.0)' should give 2.0
            assert abs(plugin._eval_expr("sqrt(4.0)") - 2.0) < 1e-9
            # A plain numeric string also works
            assert abs(plugin._eval_expr("1e-3") - 0.001) < 1e-9
        finally:
            engine.shutdown()

    def test_eval_expr_fallback_to_float_when_detached(self, qapp):
        """When not attached to an engine, _eval_expr falls back to float()."""
        plugin = DummyPlugin()
        assert abs(plugin._eval_expr("1.5") - 1.5) < 1e-9
        assert abs(plugin._eval_expr("1e-3") - 0.001) < 1e-9
