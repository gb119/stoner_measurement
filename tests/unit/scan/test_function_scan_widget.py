"""Function scan controls and preview with deterministic Qt teardown."""

from __future__ import annotations

import numpy as np
import pytest
from qtpy.QtCore import QSettings, Qt
from qtpy.QtWidgets import QSizePolicy, QWidget

import stoner_measurement.scan.function_generator as function_generator_module
from stoner_measurement.scan import FunctionScanGenerator, FunctionScanWidget, WaveformType


@pytest.fixture
def make_widget(managed_qt_widget):
    """Keep every preview, including recalled presets, alive until teardown."""

    def create(**kwargs):
        return managed_qt_widget(FunctionScanWidget(**kwargs))

    return create


class TestFunctionScanWidget:
    def test_instantiates(self, make_widget):
        gen = FunctionScanGenerator()
        widget = make_widget(generator=gen)
        assert widget is not None

    def test_is_qwidget(self, make_widget):
        gen = FunctionScanGenerator()
        widget = make_widget(generator=gen)
        assert isinstance(widget, QWidget)

    def test_get_generator(self, make_widget):
        gen = FunctionScanGenerator()
        widget = make_widget(generator=gen)
        assert widget.get_generator() is gen

    def test_amplitude_spinbox_updates_generator(self, make_widget):
        gen = FunctionScanGenerator(amplitude=1.0)
        widget = make_widget(generator=gen)
        widget._amplitude_spin.setValue(3.5)
        assert abs(gen.amplitude - 3.5) < 1e-9

    def test_offset_spinbox_updates_generator(self, make_widget):
        gen = FunctionScanGenerator(offset=0.0)
        widget = make_widget(generator=gen)
        widget._offset_spin.setValue(2.0)
        assert abs(gen.offset - 2.0) < 1e-9

    def test_phase_spinbox_updates_generator(self, make_widget):
        gen = FunctionScanGenerator(phase=0.0)
        widget = make_widget(generator=gen)
        widget._phase_spin.setValue(90.0)
        assert abs(gen.phase - 90.0) < 1e-9

    def test_points_spinbox_updates_generator(self, make_widget):
        gen = FunctionScanGenerator(num_points=100)
        widget = make_widget(generator=gen)
        widget._points_spin.setValue(50)
        assert gen.num_points == 50

    def test_waveform_combo_updates_generator(self, make_widget):
        gen = FunctionScanGenerator(waveform=WaveformType.SINE)
        widget = make_widget(generator=gen)
        triangle_index = list(WaveformType).index(WaveformType.TRIANGLE)
        widget._waveform_combo.setCurrentIndex(triangle_index)
        assert gen.waveform is WaveformType.TRIANGLE

    def test_plot_curve_data_matches_generator_after_change(self, make_widget):
        gen = FunctionScanGenerator(num_points=20)
        widget = make_widget(generator=gen)
        widget._amplitude_spin.setValue(2.0)
        _x, y = widget._curve.getData()
        assert np.allclose(y, gen.values)

    def test_initial_plot_curve_data_matches_generator(self, make_widget):
        gen = FunctionScanGenerator(num_points=10)
        widget = make_widget(generator=gen)
        _x, y = widget._curve.getData()
        assert np.allclose(y, gen.values)

    def test_external_generator_change_refreshes_plot(self, make_widget):
        """Changing a generator parameter from outside still updates the plot."""
        gen = FunctionScanGenerator(num_points=10)
        widget = make_widget(generator=gen)
        gen.amplitude = 5.0  # triggers values_changed → _refresh_plot
        _x, y = widget._curve.getData()
        assert np.allclose(y, gen.values)

    def test_unresolved_expression_logs_and_renders_nan_preview(
        self, make_widget, caplog, monkeypatch
    ):
        """An unresolved runtime expression produces a stable NaN waveform."""
        gen = FunctionScanGenerator(num_points=10)
        widget = make_widget(generator=gen)

        with caplog.at_level("WARNING", logger="stoner_measurement.scan.function_generator"):
            widget._amplitude_spin.setValue("x")

        x_values, y_values = widget._curve.getData()
        assert gen.amplitude == "x"
        assert len(x_values) == len(y_values) == gen.num_points
        assert np.isnan(y_values).all()
        assert "using NaNs" in caplog.text

        monkeypatch.setattr(
            gen,
            "eval_float",
            lambda value: 2.0 if value == "x" else float(value),
        )
        assert np.isfinite(gen.values).all()

    def test_current_point_marker_tracks_iteration(self, make_widget):
        gen = FunctionScanGenerator(num_points=5)
        widget = make_widget(generator=gen)
        next(iter(gen))
        x, y = widget._current_marker.getData()
        assert x is not None and y is not None
        assert x.tolist() == [0.0]
        assert y[0] == pytest.approx(gen.values[0])

    def test_periods_spinbox_updates_generator(self, make_widget):
        gen = FunctionScanGenerator(periods=1.0)
        widget = make_widget(generator=gen)
        widget._periods_spin.setValue(2.5)
        assert abs(gen.periods - 2.5) < 1e-9

    def test_periods_spinbox_initial_value(self, make_widget):
        gen = FunctionScanGenerator(periods=0.5)
        widget = make_widget(generator=gen)
        assert abs(widget._periods_spin.value() - 0.5) < 1e-9

    def test_exponent_spinbox_updates_generator(self, make_widget):
        gen = FunctionScanGenerator(exponent=1.0)
        widget = make_widget(generator=gen)
        widget._exponent_spin.setValue(3.0)
        assert abs(gen.exponent - 3.0) < 1e-9

    def test_exponent_spinbox_initial_value(self, make_widget):
        gen = FunctionScanGenerator(exponent=2.0)
        widget = make_widget(generator=gen)
        assert abs(widget._exponent_spin.value() - 2.0) < 1e-9

    @pytest.mark.parametrize(
        ("button_index", "waveform", "num_points", "periods"),
        [
            (0, WaveformType.SQUARE, 8, 4.0),
            (1, WaveformType.TRIANGLE, 101, 1.0),
            (2, WaveformType.SINE, 101, 1.0),
        ],
    )
    def test_builtin_preset_applies_all_settings(
        self,
        make_widget,
        button_index,
        waveform,
        num_points,
        periods,
    ):
        gen = FunctionScanGenerator(
            waveform=WaveformType.SAWTOOTH,
            amplitude=3.0,
            offset=2.0,
            phase=30.0,
            exponent=2.0,
            periods=2.0,
            num_points=20,
        )
        widget = make_widget(generator=gen)
        widget._preset_buttons[button_index].click()
        assert gen.waveform is waveform
        assert gen.amplitude == pytest.approx(1e-3)
        assert gen.offset == pytest.approx(0.0)
        assert gen.phase == pytest.approx(0.0)
        assert gen.exponent == pytest.approx(1.0)
        assert gen.periods == pytest.approx(periods)
        assert gen.num_points == num_points

    def test_preset_button_faces_match_requested_layout(self, make_widget):
        widget = make_widget(generator=FunctionScanGenerator())
        assert len(widget._preset_buttons) == 6
        assert all(button.text() == "" for button in widget._preset_buttons[:3])
        assert all(not button.icon().isNull() for button in widget._preset_buttons[:3])
        assert [button.text() for button in widget._preset_buttons[3:]] == ["1", "2", "3"]

    def test_parameter_controls_use_requested_two_column_grid(self, make_widget):
        widget = make_widget(generator=FunctionScanGenerator())
        expected_positions = {
            widget._amplitude_spin: (0, 1),
            widget._offset_spin: (0, 3),
            widget._points_spin: (1, 1),
            widget._periods_spin: (1, 3),
            widget._phase_spin: (2, 1),
            widget._exponent_spin: (2, 3),
        }
        for control, expected_position in expected_positions.items():
            index = widget._parameter_grid.indexOf(control)
            row, column, _row_span, _column_span = widget._parameter_grid.getItemPosition(index)
            assert (row, column) == expected_position

    def test_preset_buttons_have_compact_minimum_and_can_grow(self, make_widget):
        widget = make_widget(generator=FunctionScanGenerator())
        for button in widget._preset_buttons:
            assert button.minimumWidth() == 64
            assert button.minimumHeight() == 44
            assert button.maximumWidth() > button.minimumWidth()
            assert button.maximumHeight() > button.minimumHeight()
            assert button.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed

    def test_preview_caps_height_at_four_by_three_when_space_is_available(self, make_widget, qapp):
        widget = make_widget(generator=FunctionScanGenerator())
        widget.resize(800, 1200)
        widget.show()
        qapp.processEvents()
        assert widget._plot_container.height() > widget._plot_widget.height()
        assert widget._plot_widget.width() / widget._plot_widget.height() == pytest.approx(
            4.0 / 3.0,
            abs=0.01,
        )

    def test_user_preset_ctrl_click_stores_and_ordinary_click_recalls(
        self,
        make_widget,
        qtbot,
        tmp_path,
        monkeypatch,
    ):
        settings = QSettings(
            str(tmp_path / "function-generator-presets.ini"),
            QSettings.Format.IniFormat,
        )
        monkeypatch.setattr(function_generator_module, "_preset_settings", lambda: settings)
        gen = FunctionScanGenerator(
            waveform=WaveformType.SAWTOOTH,
            amplitude=0.025,
            offset=-0.004,
            phase=12.0,
            exponent=1.5,
            periods=2.5,
            num_points=77,
        )
        widget = make_widget(generator=gen)
        qtbot.mouseClick(
            widget._preset_buttons[3],
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
        )
        stored_tooltip = widget._preset_buttons[3].toolTip()
        assert "Sawtooth" in stored_tooltip
        assert "77 points" in stored_tooltip
        assert "2.5 periods" in stored_tooltip
        assert "amplitude 0.025" in stored_tooltip

        recalled = FunctionScanGenerator()
        recalled_widget = make_widget(generator=recalled)
        assert recalled_widget._preset_buttons[3].toolTip() == stored_tooltip
        recalled_widget._preset_buttons[3].click()
        assert recalled.waveform is WaveformType.SAWTOOTH
        assert recalled.amplitude == pytest.approx(0.025)
        assert recalled.offset == pytest.approx(-0.004)
        assert recalled.phase == pytest.approx(12.0)
        assert recalled.exponent == pytest.approx(1.5)
        assert recalled.periods == pytest.approx(2.5)
        assert recalled.num_points == 77

    # ------------------------------------------------------------------
    # units — widget suffix propagation
    # ------------------------------------------------------------------

    def test_units_applied_to_amplitude_and_offset_spinboxes(self, make_widget):
        gen = FunctionScanGenerator()
        widget = make_widget(generator=gen)
        gen.units = "V"
        assert widget._amplitude_spin.opts["suffix"] == "V"
        assert widget._offset_spin.opts["suffix"] == "V"

    def test_units_not_applied_to_phase_or_exponent_spinboxes(self, make_widget):
        gen = FunctionScanGenerator()
        widget = make_widget(generator=gen)
        gen.units = "T"
        assert widget._phase_spin.opts.get("suffix", "") != "T"
        assert widget._exponent_spin.opts.get("suffix", "") != "T"

    def test_units_initialised_from_generator_at_construction(self, make_widget):
        gen = FunctionScanGenerator()
        gen.units = "A"
        widget = make_widget(generator=gen)
        assert widget._amplitude_spin.opts["suffix"] == "A"

    def test_units_to_json_round_trip(self, make_widget):
        gen = FunctionScanGenerator()
        gen.units = "V"
        d = gen.to_json()
        assert d["units"] == "V"
        restored = FunctionScanGenerator._from_json_data(d)
        assert restored.units == "V"

    def test_units_missing_from_json_defaults_empty(self, make_widget):
        gen = FunctionScanGenerator()
        d = gen.to_json()
        d.pop("units", None)
        restored = FunctionScanGenerator._from_json_data(d)
        assert restored.units == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
