"""Tests for ArbitraryFunctionScanGenerator and ArbitraryFunctionScanWidget."""

from __future__ import annotations

import logging

import numpy as np
import pytest
from qtpy.QtCore import QSettings, Qt
from qtpy.QtWidgets import QLabel, QSizePolicy, QWidget

import stoner_measurement.scan.arbitrary_function_generator as arbitrary_function_module
from stoner_measurement.core.sequence_engine import SEQUENCE_LOGGER_NAME
from stoner_measurement.scan import (
    ArbitraryFunctionScanGenerator,
    ArbitraryFunctionScanWidget,
    BaseScanGenerator,
)


class TestArbitraryFunctionScanGenerator:
    def test_generate_default_has_expected_length(self, qapp):
        gen = ArbitraryFunctionScanGenerator(num_points=32)
        values = gen.generate()
        assert len(values) == 32
        assert np.isfinite(values).all()

    def test_generate_custom_scan_function(self, qapp):
        code = "def scan(ix, omega):\n    return ix * omega\n"
        gen = ArbitraryFunctionScanGenerator(num_points=5, code=code)
        values = gen.generate()
        omega = (2.0 * np.pi) / 5.0
        assert np.allclose(values, [0.0, omega, 2 * omega, 3 * omega, 4 * omega])

    def test_syntax_error_sets_error_state(self, qapp):
        gen = ArbitraryFunctionScanGenerator(code="def scan(ix, omega)\n    return ix\n")
        assert gen.syntax_error_line is not None
        assert gen.syntax_error_message
        assert np.isnan(gen.generate()).all()

    def test_runtime_error_yields_nan_values(self, qapp):
        code = "def scan(ix, omega):\n    return 1 / (ix - 2)\n"
        gen = ArbitraryFunctionScanGenerator(num_points=5, code=code)
        values = gen.generate()
        assert np.isnan(values[2])
        assert np.isfinite(values[[0, 1, 3, 4]]).all()

    def test_runtime_error_reporting(self, qapp, capsys):
        code = "def scan(ix, omega):\n    return 1 / (ix - 2)\n"
        gen = ArbitraryFunctionScanGenerator(num_points=5, code=code)

        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture()
        logger = logging.getLogger(SEQUENCE_LOGGER_NAME)
        logger.addHandler(handler)
        try:
            values = gen.generate()
        finally:
            logger.removeHandler(handler)

        captured = capsys.readouterr()
        assert np.isnan(values[2])
        assert any(
            "Error evaluating arbitrary scan function at ix=2" in r.getMessage() for r in records
        )
        assert "Error evaluating arbitrary scan function at ix=2" in captured.err

    def test_compile_error_reporting(self, qapp, capsys):
        code = "def scan(ix, omega)\n    return ix\n"
        gen = ArbitraryFunctionScanGenerator(num_points=5, code=code)

        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture()
        logger = logging.getLogger(SEQUENCE_LOGGER_NAME)
        logger.addHandler(handler)
        try:
            values = gen.generate()
        finally:
            logger.removeHandler(handler)

        captured = capsys.readouterr()
        assert np.isnan(values).all()
        assert any("Failed to compile arbitrary scan function" in r.getMessage() for r in records)
        assert "Failed to compile arbitrary scan function" in captured.err

    def test_scan_function_can_use_builtin_abs(self, qapp):
        code = "def scan(ix, omega):\n    return abs(ix - 5)\n"
        gen = ArbitraryFunctionScanGenerator(num_points=11, code=code)
        values = gen.generate()
        assert values[5] == 0.0
        assert values[0] == 5.0

    def test_scan_function_can_use_numpy_via_np(self, qapp):
        code = "def scan(ix, omega):\n    return np.sqrt(float(ix))\n"
        gen = ArbitraryFunctionScanGenerator(num_points=4, code=code)
        values = gen.generate()
        assert np.allclose(values, [0.0, 1.0, np.sqrt(2.0), np.sqrt(3.0)])

    def test_scan_function_can_use_log(self, qapp):
        """scan() can call log.debug() without raising errors."""
        code = "def scan(ix, omega):\n    log.debug('point %d', ix)\n    return float(ix)\n"
        gen = ArbitraryFunctionScanGenerator(num_points=5, code=code)
        values = gen.generate()
        assert np.allclose(values, [0.0, 1.0, 2.0, 3.0, 4.0])

    def test_log_object_is_correct_logger(self, qapp):
        """The log object injected into the namespace is the sequence logger."""
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture()
        logger = logging.getLogger(SEQUENCE_LOGGER_NAME)
        logger.addHandler(handler)
        try:
            code = (
                "def scan(ix, omega):\n    log.info('hello from ix=%d', ix)\n    return float(ix)\n"
            )
            gen = ArbitraryFunctionScanGenerator(num_points=3, code=code)
            gen.generate()
        finally:
            logger.removeHandler(handler)

        assert len(records) == 3
        assert all(r.levelno == logging.INFO for r in records)

    def test_measure_flags_all_true(self, qapp):
        gen = ArbitraryFunctionScanGenerator(num_points=9)
        flags = gen.measure_flags()
        assert flags.dtype == bool
        assert flags.tolist() == [True] * 9

    def test_to_json_and_from_json_round_trip(self, qapp):
        code = "def scan(ix, omega):\n    return ix\n"
        gen = ArbitraryFunctionScanGenerator(num_points=21, code=code)
        restored = ArbitraryFunctionScanGenerator._from_json_data(gen.to_json())
        assert restored.num_points == 21
        assert restored.code == code

    def test_base_from_json_dispatch(self, qapp):
        gen = ArbitraryFunctionScanGenerator(num_points=12)
        restored = BaseScanGenerator.from_json(gen.to_json())
        assert isinstance(restored, ArbitraryFunctionScanGenerator)
        assert restored.num_points == 12

    def test_config_widget_returns_arbitrary_widget(self, qapp):
        gen = ArbitraryFunctionScanGenerator()
        widget = gen.config_widget()
        assert isinstance(widget, ArbitraryFunctionScanWidget)


class TestArbitraryFunctionScanWidget:
    def test_is_qwidget(self, qapp):
        widget = ArbitraryFunctionScanWidget(generator=ArbitraryFunctionScanGenerator())
        assert isinstance(widget, QWidget)

    def test_points_spinbox_updates_generator(self, qapp):
        gen = ArbitraryFunctionScanGenerator(num_points=10)
        widget = ArbitraryFunctionScanWidget(generator=gen)
        widget._points_spin.setValue(22)
        assert gen.num_points == 22

    def test_editor_updates_generator_code_and_syntax_marker(self, qapp):
        gen = ArbitraryFunctionScanGenerator()
        widget = ArbitraryFunctionScanWidget(generator=gen)
        widget._editor.set_text("def scan(ix, omega)\n    return ix\n")
        assert gen.syntax_error_line is not None
        assert widget._editor.syntax_error_line == gen.syntax_error_line

    def test_plot_curve_matches_generator_values(self, qapp):
        gen = ArbitraryFunctionScanGenerator(num_points=16)
        widget = ArbitraryFunctionScanWidget(generator=gen)
        widget._editor.set_text("def scan(ix, omega):\n    return np.cos(ix * omega)\n")
        _x, y = widget._curve.getData()
        assert np.allclose(y, gen.values)

    def test_current_point_marker_tracks_iteration(self, qapp):
        gen = ArbitraryFunctionScanGenerator(num_points=8)
        widget = ArbitraryFunctionScanWidget(generator=gen)
        next(iter(gen))
        x, y = widget._current_marker.getData()
        assert x is not None and y is not None
        assert x.tolist() == [0.0]
        assert y[0] == gen.values[0]

    def test_namespace_label_is_present(self, qapp):
        """Widget includes a label advertising the available namespace."""
        widget = ArbitraryFunctionScanWidget(generator=ArbitraryFunctionScanGenerator())
        labels = widget.findChildren(QLabel)
        label_texts = " ".join(lbl.text() for lbl in labels)
        assert "np" in label_texts
        assert "log" in label_texts

    def test_fixed_preset_applies_requested_code_and_point_count(self, qapp):
        gen = ArbitraryFunctionScanGenerator(
            num_points=20,
            code="def scan(ix, omega):\n    return ix\n",
        )
        widget = ArbitraryFunctionScanWidget(generator=gen)
        widget._preset_buttons[0].click()
        assert gen.num_points == 1000
        assert gen.code == (
            "def scan(ix, omega):\n"
            '    """Example arbitrary scan: one sine period over the scan length."""\n'
            "    t=ix*omega\n"
            "    max_field=3\n"
            "    return max_field*np.sin(10*t)*(1-np.exp(-t**2/10))\n"
        )
        assert widget._editor.text() == gen.code

    def test_preset_button_faces_match_requested_layout(self, qapp):
        widget = ArbitraryFunctionScanWidget(generator=ArbitraryFunctionScanGenerator())
        assert len(widget._preset_buttons) == 6
        assert widget._preset_buttons[0].text() == ""
        assert not widget._preset_buttons[0].icon().isNull()
        assert [button.text() for button in widget._preset_buttons[1:]] == [
            "1",
            "2",
            "3",
            "4",
            "5",
        ]

    def test_editor_prefers_at_least_five_lines(self, qapp):
        widget = ArbitraryFunctionScanWidget(generator=ArbitraryFunctionScanGenerator())
        assert widget._editor.minimumHeight() >= 5 * widget._editor.fontMetrics().lineSpacing()

    def test_preset_buttons_are_compact_and_fixed_width(self, qapp):
        widget = ArbitraryFunctionScanWidget(generator=ArbitraryFunctionScanGenerator())
        for button in widget._preset_buttons:
            assert button.size().width() == 64
            assert button.size().height() == 44
            assert button.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed

    def test_preview_caps_height_at_four_by_three_when_space_is_available(self, qapp):
        widget = ArbitraryFunctionScanWidget(generator=ArbitraryFunctionScanGenerator())
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
        qapp,
        qtbot,
        tmp_path,
        monkeypatch,
    ):
        settings = QSettings(
            str(tmp_path / "arbitrary-function-presets.ini"),
            QSettings.Format.IniFormat,
        )
        monkeypatch.setattr(arbitrary_function_module, "_preset_settings", lambda: settings)
        stored_code = "def scan(ix, omega):\n    return np.cos(3 * ix * omega)\n"
        gen = ArbitraryFunctionScanGenerator(num_points=321, code=stored_code)
        widget = ArbitraryFunctionScanWidget(generator=gen)
        qtbot.mouseClick(
            widget._preset_buttons[1],
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
        )
        stored_tooltip = widget._preset_buttons[1].toolTip()
        assert "321 points" in stored_tooltip
        assert "return np.cos(3 * ix * omega)" in stored_tooltip

        recalled = ArbitraryFunctionScanGenerator()
        recalled_widget = ArbitraryFunctionScanWidget(generator=recalled)
        assert recalled_widget._preset_buttons[1].toolTip() == stored_tooltip
        recalled_widget._preset_buttons[1].click()
        assert recalled.code == stored_code
        assert recalled.num_points == 321
        assert recalled_widget._editor.text() == stored_code

    # ------------------------------------------------------------------
    # units — JSON round-trip
    # ------------------------------------------------------------------

    def test_units_to_json_round_trip(self, qapp):
        gen = ArbitraryFunctionScanGenerator()
        gen.units = "K"
        d = gen.to_json()
        assert d["units"] == "K"
        restored = ArbitraryFunctionScanGenerator._from_json_data(d)
        assert restored.units == "K"

    def test_units_missing_from_json_defaults_empty(self, qapp):
        gen = ArbitraryFunctionScanGenerator()
        d = gen.to_json()
        d.pop("units", None)
        restored = ArbitraryFunctionScanGenerator._from_json_data(d)
        assert restored.units == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
