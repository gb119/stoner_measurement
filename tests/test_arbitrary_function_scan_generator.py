"""Tests for ArbitraryFunctionScanGenerator and ArbitraryFunctionScanWidget."""

from __future__ import annotations

import logging

import numpy as np
from PyQt6.QtWidgets import QLabel, QWidget

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
        from stoner_measurement.core.sequence_engine import SEQUENCE_LOGGER_NAME

        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Capture()
        logger = logging.getLogger(SEQUENCE_LOGGER_NAME)
        logger.addHandler(handler)
        try:
            code = "def scan(ix, omega):\n    log.info('hello from ix=%d', ix)\n    return float(ix)\n"
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

    def test_namespace_label_is_present(self, qapp):
        """Widget includes a label advertising the available namespace."""
        widget = ArbitraryFunctionScanWidget(generator=ArbitraryFunctionScanGenerator())
        labels = widget.findChildren(QLabel)
        label_texts = " ".join(lbl.text() for lbl in labels)
        assert "np" in label_texts
        assert "log" in label_texts
