"""Tests for the DummyPlugin."""

from __future__ import annotations

import math
from unittest.mock import patch

import numpy as np
import pytest

from stoner_measurement.plugins.trace import DummyPlugin, TraceStatus
from stoner_measurement.scan import SteppedScanGenerator, WaveformType


def _make_scan(plugin, end=0.4, step=0.1):
    """Return a SteppedScanGenerator with one stage and assign it to *plugin*."""
    gen = SteppedScanGenerator(start=0.0, stages=[(end, step, True)], parent=plugin)
    plugin.scan_generator = gen
    return gen


def _register_tab_widgets(qtbot, tabs):
    """Register config-tab widgets with qtbot for safe teardown."""
    for _title, widget in tabs:
        qtbot.addWidget(widget)
    return tabs


def _measure_pairs(plugin, parameters):
    """Measure once and return conventional x/y pairs for model assertions."""
    trace = plugin.measure(parameters)[plugin.name]
    return list(zip(trace.x, trace.y, strict=True))


class TestDummyPlugin:
    def test_name(self):
        plugin = DummyPlugin()
        assert plugin.name == "Dummy"

    def test_execute_uses_scan_generator(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)  # 5 points: 0.0…0.4
        data = _measure_pairs(plugin, {})
        assert len(data) == 5

    def test_execute_empty_scan_yields_default_points(self, qapp):
        plugin = DummyPlugin()
        # Default FunctionScanGenerator generates 501 points
        data = _measure_pairs(plugin, {})
        assert len(data) == 501

    def test_execute_yields_all_points_regardless_of_measure_flag(self, qapp):
        plugin = DummyPlugin()
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(0.2, 0.1, False), (0.4, 0.1, True)],
            parent=plugin,
        )
        plugin.scan_generator = gen
        data = _measure_pairs(plugin, {})
        # All five configured scan points are represented in the dataset.
        assert len(data) == 5

    def test_execute_yields_tuples(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)
        data = _measure_pairs(plugin, {})
        for item in data:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_execute_amplitude(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.4, step=0.1)
        # Explicit I_c=1.0 > all scan points (0…0.4), so all V must be 0
        data = _measure_pairs(plugin, {"I_c": "1.0", "R_n": "1.0", "V_n": "0.0", "Rounding": "0.0"})
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
        data = _measure_pairs(plugin, {"I_c": "1.0", "R_n": "1.0", "V_n": "0.0", "Rounding": "0.0"})
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

    def test_config_tabs_returns_three_tabs(self, qapp, qtbot):
        plugin = DummyPlugin()
        tabs = _register_tab_widgets(qtbot, plugin.config_tabs())
        assert len(tabs) == 3

    def test_config_tabs_titles(self, qapp, qtbot):
        plugin = DummyPlugin()
        tabs = _register_tab_widgets(qtbot, plugin.config_tabs())
        titles = [t for t, _ in tabs]
        assert titles == [
            "Scan",
            "Settings",
            "About",
        ]

    def test_config_tabs_widgets_are_qwidgets(self, qapp, qtbot):
        from qtpy.QtWidgets import QWidget

        plugin = DummyPlugin()
        for _title, widget in _register_tab_widgets(qtbot, plugin.config_tabs()):
            assert isinstance(widget, QWidget)

    def test_config_tabs_caches_widgets(self, qapp, qtbot):
        """Subsequent calls to config_tabs() return the same widget instances."""
        plugin = DummyPlugin()
        tabs1 = _register_tab_widgets(qtbot, plugin.config_tabs())
        tabs2 = plugin.config_tabs()
        for (t1, w1), (t2, w2) in zip(tabs1, tabs2):
            assert t1 == t2
            assert w1 is w2

    def test_monitor_widget_returns_none(self):
        plugin = DummyPlugin()
        assert plugin.monitor_widget() is None

    def test_has_scan_generator(self, qapp):
        from stoner_measurement.scan import FunctionScanGenerator

        plugin = DummyPlugin()
        assert isinstance(plugin.scan_generator, FunctionScanGenerator)

    def test_scan_tab_is_first(self, qapp, qtbot):
        plugin = DummyPlugin()
        tabs = _register_tab_widgets(qtbot, plugin.config_tabs())
        assert "Scan" in tabs[0][0]
        assert "Type" not in tabs[0][0]

    def test_scan_tab_widget_is_qwidget(self, qapp, qtbot):
        from qtpy.QtWidgets import QWidget

        plugin = DummyPlugin()
        tabs = _register_tab_widgets(qtbot, plugin.config_tabs())
        assert isinstance(tabs[0][1], QWidget)

    def test_statistics_checkbox_is_on_scan_tab(self, qapp, qtbot):
        """The shared trace statistics switch should live on the common Scan tab."""
        from qtpy.QtWidgets import QCheckBox

        plugin = DummyPlugin()
        tabs = _register_tab_widgets(qtbot, plugin.config_tabs())
        scan_widget = tabs[0][1]
        checkboxes = scan_widget.findChildren(QCheckBox)
        texts = [cb.text() for cb in checkboxes]
        assert "Report channel average and standard deviation outputs" in texts

    def test_transpose_checkbox_follows_statistics_checkbox(self, qapp, qtbot):
        from qtpy.QtWidgets import QCheckBox

        plugin = DummyPlugin()
        tabs = _register_tab_widgets(qtbot, plugin.config_tabs())
        checkboxes = tabs[0][1].findChildren(QCheckBox)
        texts = [checkbox.text() for checkbox in checkboxes]

        assert texts.index("Transpose X and primary Y channels") == (
            texts.index("Report channel average and standard deviation outputs") + 1
        )
        transpose = next(
            checkbox
            for checkbox in checkboxes
            if checkbox.text() == "Transpose X and primary Y channels"
        )
        transpose.setChecked(True)
        assert plugin._transpose is True

    def test_statistics_checkbox_is_not_on_settings_tab(self, qapp, qtbot):
        """The shared trace statistics switch should no longer be injected into Settings."""
        from qtpy.QtWidgets import QCheckBox

        plugin = DummyPlugin()
        tabs = _register_tab_widgets(qtbot, plugin.config_tabs())
        settings_widget = tabs[1][1]
        assert all(
            cb.text() != "Report channel average and standard deviation outputs"
            for cb in settings_widget.findChildren(QCheckBox)
        )

    def test_about_tab_is_last(self, qapp, qtbot):
        plugin = DummyPlugin()
        tabs = _register_tab_widgets(qtbot, plugin.config_tabs())
        assert "About" in tabs[-1][0]

    def test_about_html_returns_string(self, qapp):
        plugin = DummyPlugin()
        html = plugin._about_html()
        assert isinstance(html, str)
        assert "<h3>" in html

    def test_plugin_config_tabs_returns_widget(self, qapp, qtbot):
        from qtpy.QtWidgets import QWidget

        plugin = DummyPlugin()
        widget = plugin._plugin_config_tabs()
        qtbot.addWidget(widget)
        assert isinstance(widget, QWidget)

    def test_plugin_config_uses_expression_si_spinboxes(self, qapp, qtbot):
        """Physical settings share the SI-aware expression editor."""
        from stoner_measurement.ui.widgets import SISpinBox

        plugin = DummyPlugin()
        widget = plugin._plugin_config_tabs()
        qtbot.addWidget(widget)
        spins = widget.findChildren(SISpinBox)

        assert [spin.opts["suffix"] for spin in spins] == ["A", "Ω", "V", "V", "K"]
        spins[0].lineEdit().setText("base_current * 2")
        spins[0].editingFinished.emit()
        assert plugin._critical_current == "base_current * 2"
        spins[3].lineEdit().setText("offset_sigma")
        spins[3].editingFinished.emit()
        assert plugin._voltage_offset_scale == "offset_sigma"

    def test_set_scan_generator_class(self, qapp):
        from stoner_measurement.scan import FunctionScanGenerator

        plugin = DummyPlugin()
        plugin.set_scan_generator_class(FunctionScanGenerator)
        assert isinstance(plugin.scan_generator, FunctionScanGenerator)

    def test_set_scan_generator_class_noop_if_same(self, qapp):
        from stoner_measurement.scan import FunctionScanGenerator

        plugin = DummyPlugin()
        gen_before = plugin.scan_generator
        plugin.set_scan_generator_class(FunctionScanGenerator)
        assert plugin.scan_generator is gen_before

    def test_scan_generator_changed_signal(self, qapp):
        plugin = DummyPlugin()
        received = []
        plugin.scan_generator_changed.connect(lambda: received.append(True))
        plugin.set_scan_generator_class(SteppedScanGenerator)
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
        import pandas as pd

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
        # New DataFrame-backed API
        assert isinstance(td.df, pd.DataFrame)
        assert "V" in td.df.columns

    def test_measure_tracedata_has_column_roles(self, qapp):
        from stoner_measurement.core import COLUMN_ROLE_Y

        plugin = DummyPlugin()
        _make_scan(plugin, end=0.2, step=0.1)
        result = plugin.measure({})
        td = result["Dummy"]
        assert td.get_columns_by_role(COLUMN_ROLE_Y) == ["V"]

    def test_measure_transposes_x_and_primary_y_roles(self, qapp):
        from stoner_measurement.core import COLUMN_ROLE_X, COLUMN_ROLE_Y

        plugin = DummyPlugin()
        plugin._set_transpose(True)
        _make_scan(plugin, end=0.2, step=0.1)

        td = plugin.measure({})["Dummy"]

        assert td.get_columns_by_role(COLUMN_ROLE_X) == ["V"]
        assert td.get_columns_by_role(COLUMN_ROLE_Y) == ["x"]

    def test_measure_status_data_available_after_completion(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=0.2, step=0.1)
        plugin.measure({})
        assert plugin.status is TraceStatus.DATA_AVAILABLE

    def test_reported_values_disabled_by_default(self, qapp):
        plugin = DummyPlugin()
        assert plugin.reported_values() == {}

    def test_reported_values_enabled_lists_channel_stats(self, qapp):
        plugin = DummyPlugin()
        plugin._set_report_channel_statistics(True)
        values = plugin.reported_values()
        assert "dummy:Dummy mean" in values
        assert "dummy:Dummy std" in values

    def test_measure_updates_channel_statistics_when_enabled(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=2.0, step=1.0)  # I = [0, 1, 2]
        plugin._set_report_channel_statistics(True)
        plugin.measure({"I_c": "1.0", "R_n": "1.0", "V_n": "0.0", "Rounding": "0.0"})
        stats = plugin.channel_statistics["Dummy"]
        expected = np.array([0.0, 0.0, math.sqrt(3.0)])
        assert stats["mean"] == pytest.approx(float(np.mean(expected)))
        assert stats["std"] == pytest.approx(float(np.std(expected)))

    # ------------------------------------------------------------------
    # Trace detail properties
    # ------------------------------------------------------------------

    def test_x_units(self, qapp):
        assert DummyPlugin().x_units == "A"

    def test_y_units(self, qapp):
        assert DummyPlugin().y_units == "V"

    def test_x_label(self, qapp):
        assert DummyPlugin().x_label == "I"

    def test_y_label(self, qapp):
        assert DummyPlugin().y_label == "V"

    def test_default_noise_level(self, qapp):
        assert DummyPlugin()._noise_level == "1.0E-8"

    def test_default_voltage_offset_scale_is_zero(self, qapp):
        assert DummyPlugin()._voltage_offset_scale == "0.0"

    def test_execute_zero_noise_is_exact(self, qapp):
        """V_n=0.0 must give exact RSJ values (no noise added)."""
        plugin = DummyPlugin()
        gen = SteppedScanGenerator(start=0.0, stages=[(2.0, 1.0, True)], parent=plugin)
        plugin.scan_generator = gen
        data = _measure_pairs(plugin, {"I_c": "1.0", "R_n": "1.0", "V_n": "0.0", "Rounding": "0.0"})
        v_vals = [v for _i, v in data]
        assert abs(v_vals[0]) < 1e-9  # I=0  → V=0
        assert abs(v_vals[1]) < 1e-9  # I=1  → V=0 (at I_c)
        assert abs(v_vals[2] - math.sqrt(3)) < 1e-9  # I=2 → sqrt(3)

    def test_execute_noise_shifts_voltages(self, qapp):
        """Non-zero V_n should produce voltages that differ from the noiseless values."""
        plugin = DummyPlugin()
        gen = SteppedScanGenerator(start=2.0, stages=[(2.0, 1.0, True)], parent=plugin)
        plugin.scan_generator = gen
        noiseless = _measure_pairs(plugin, {"I_c": 0.0, "R_n": 1.0, "V_n": "0.0"})

        np.random.seed(0)
        noisy = _measure_pairs(plugin, {"I_c": 0.0, "R_n": 1.0, "V_n": "1.0"})

        # With noise scale=1.0 (much larger than typical RSJ voltages) the
        # noisy and noiseless voltages should almost certainly differ.
        assert any(abs(nv - v) > 1e-12 for (_, nv), (_, v) in zip(noisy, noiseless))

    def test_execute_noise_uses_v_n_parameter(self, qapp):
        """V_n passed in parameters overrides _noise_level attribute."""
        plugin = DummyPlugin()
        plugin._noise_level = "0.0"  # default noiseless
        gen = SteppedScanGenerator(start=2.0, stages=[(2.0, 1.0, True)], parent=plugin)
        plugin.scan_generator = gen
        np.random.seed(1)
        noisy = _measure_pairs(plugin, {"I_c": 0.0, "R_n": 1.0, "V_n": "100.0"})
        # With V_n=100 V the noise dominates; voltages should not all be
        # exactly equal to the noiseless RSJ value (I=2 → V=2 for I_c=0).
        noiseless_v = 2.0
        assert any(abs(v - noiseless_v) > 1e-6 for _i, v in noisy)

    def test_zero_voltage_offset_scale_skips_random_draw(self, qapp):
        plugin = DummyPlugin()
        _make_scan(plugin, end=2.0, step=1.0)

        with patch("stoner_measurement.plugins.trace.dummy.np.random.normal") as normal:
            data = _measure_pairs(
                plugin,
                {
                    "I_c": "0.0",
                    "R_n": "1.0",
                    "V_n": "0.0",
                    "V_offset": "0.0",
                    "Rounding": "0.0",
                },
            )

        normal.assert_not_called()
        assert [voltage for _current, voltage in data] == pytest.approx([0.0, 1.0, 2.0])

    def test_voltage_offset_is_one_constant_draw_per_measurement(self, qapp):
        plugin = DummyPlugin()
        plugin._voltage_offset_scale = "0.5"
        _make_scan(plugin, end=2.0, step=1.0)

        with patch(
            "stoner_measurement.plugins.trace.dummy.np.random.normal", return_value=0.25
        ) as normal:
            data = _measure_pairs(
                plugin,
                {
                    "I_c": "0.0",
                    "R_n": "1.0",
                    "V_n": "0.0",
                    "Rounding": "0.0",
                },
            )

        normal.assert_called_once_with(0.0, 0.5)
        assert [voltage for _current, voltage in data] == pytest.approx([0.25, 1.25, 2.25])

    def test_default_normal_resistance(self, qapp):
        assert DummyPlugin()._normal_resistance == "5.0E-3"

    def test_execute_negative_current_rsj(self, qapp):
        """RSJ output for negative currents should have negative voltage."""
        plugin = DummyPlugin()
        gen = SteppedScanGenerator(
            start=-2.0,
            stages=[(-0.0, 1.0, True)],
            parent=plugin,
        )
        plugin.scan_generator = gen
        data = _measure_pairs(plugin, {"I_c": "1.0", "R_n": "1.0", "V_n": "0.0", "Rounding": "0.0"})
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
        data1 = _measure_pairs(
            plugin, {"I_c": "1.0", "R_n": "1.0", "V_n": "0.0", "Rounding": "0.0"}
        )
        data2 = _measure_pairs(
            plugin, {"I_c": "1.0", "R_n": "2.0", "V_n": "0.0", "Rounding": "0.0"}
        )
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
            plugin.engine_namespace["base_current"] = 0.25
            assert abs(plugin._eval_expr("base_current * 2") - 0.5) < 1e-9
            # A plain numeric string also works
            assert abs(plugin._eval_expr("1e-3") - 0.001) < 1e-9
        finally:
            engine.shutdown()

    def test_eval_expr_fallback_to_float_when_detached(self, qapp):
        """When not attached to an engine, _eval_expr falls back to float()."""
        plugin = DummyPlugin()
        assert abs(plugin._eval_expr("1.5") - 1.5) < 1e-9
        assert abs(plugin._eval_expr("1e-3") - 0.001) < 1e-9

    def test_scan_spinbox_expression_is_evaluated_when_values_are_generated(
        self, qapp, engine
    ):
        """Scan settings retain expressions until the generator needs values."""
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        plugin.engine_namespace["scan_amplitude"] = 2.5
        plugin.scan_generator.waveform = WaveformType.SINE
        plugin.scan_generator.amplitude = "scan_amplitude"
        plugin.scan_generator.offset = 0.0
        plugin.scan_generator.phase = 0.0
        plugin.scan_generator.exponent = 1.0
        plugin.scan_generator.periods = 1.0
        plugin.scan_generator.num_points = 4

        values = plugin.scan_generator.generate()

        assert max(abs(values)) == pytest.approx(2.165063509461097)

    # ------------------------------------------------------------------
    # JSON serialisation — settings tab
    # ------------------------------------------------------------------

    def test_to_json_includes_settings(self, qapp):
        plugin = DummyPlugin()
        d = plugin.to_json()
        assert d["critical_current"] == "0.5E-3"
        assert d["normal_resistance"] == "5.0E-3"
        assert d["noise_level"] == "1.0E-8"
        assert d["voltage_offset_scale"] == "0.0"
        assert d["report_channel_statistics"] is False
        assert d["transpose"] is False

    def test_to_json_reflects_changed_settings(self, qapp):
        plugin = DummyPlugin()
        plugin._critical_current = "2.5"
        plugin._normal_resistance = "0.5"
        plugin._noise_level = "1e-3"
        plugin._voltage_offset_scale = "2e-6"
        d = plugin.to_json()
        assert d["critical_current"] == "2.5"
        assert d["normal_resistance"] == "0.5"
        assert d["noise_level"] == "1e-3"
        assert d["voltage_offset_scale"] == "2e-6"

    def test_round_trip_restores_settings(self, qapp):
        import json

        from stoner_measurement.plugins.base_plugin import BasePlugin

        plugin = DummyPlugin()
        plugin._critical_current = "2.5"
        plugin._normal_resistance = "0.5"
        plugin._noise_level = "1e-3"
        plugin._voltage_offset_scale = "2e-6"
        plugin._set_report_channel_statistics(True)
        plugin._set_transpose(True)

        restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
        assert isinstance(restored, DummyPlugin)
        assert restored._critical_current == "2.5"
        assert restored._normal_resistance == "0.5"
        assert restored._noise_level == "1e-3"
        assert restored._voltage_offset_scale == "2e-6"
        assert restored._report_channel_statistics is True
        assert restored._transpose is True

    def test_round_trip_default_settings(self, qapp):
        import json

        from stoner_measurement.plugins.base_plugin import BasePlugin

        plugin = DummyPlugin()
        restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
        assert isinstance(restored, DummyPlugin)
        assert restored._critical_current == "0.5E-3"
        assert restored._normal_resistance == "5.0E-3"
        assert restored._noise_level == "1.0E-8"
        assert restored._voltage_offset_scale == "0.0"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
