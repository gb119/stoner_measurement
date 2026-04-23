"""Tests for logging support in the sequence engine, base plugin, and log viewer."""

from __future__ import annotations

import logging

import pytest

from stoner_measurement.core.sequence_engine import (
    SEQUENCE_LOGGER_NAME,
    SequenceEngine,
    _QtLogHandler,
)
from stoner_measurement.plugins.trace import DummyPlugin

# ---------------------------------------------------------------------------
# _QtLogHandler
# ---------------------------------------------------------------------------


class TestQtLogHandler:
    def test_is_logging_handler(self, qapp):
        handler = _QtLogHandler()
        assert isinstance(handler, logging.Handler)

    def test_default_level_is_debug(self, qapp):
        handler = _QtLogHandler()
        assert handler.level == logging.DEBUG

    def test_custom_level(self, qapp):
        handler = _QtLogHandler(level=logging.WARNING)
        assert handler.level == logging.WARNING

    def test_emit_fires_signal(self, qapp):
        received = []
        handler = _QtLogHandler()
        handler.record_emitted.connect(received.append)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        assert len(received) == 1
        assert received[0] is record


# ---------------------------------------------------------------------------
# SequenceEngine logging integration
# ---------------------------------------------------------------------------


class TestSequenceEngineLogging:
    def test_namespace_has_log(self, engine):
        assert "log" in engine.namespace

    def test_log_is_logger_instance(self, engine):
        assert isinstance(engine.namespace["log"], logging.Logger)

    def test_log_has_correct_name(self, engine):
        assert engine.namespace["log"].name == SEQUENCE_LOGGER_NAME

    def test_log_handler_attached(self, engine):
        logger = logging.getLogger(SEQUENCE_LOGGER_NAME)
        assert engine.log_handler in logger.handlers

    def test_log_handler_removed_on_shutdown(self, qapp):
        eng = SequenceEngine()
        handler = eng.log_handler
        eng.shutdown()
        logger = logging.getLogger(SEQUENCE_LOGGER_NAME)
        assert handler not in logger.handlers

    def test_log_handler_property_returns_handler(self, engine):
        from stoner_measurement.core.sequence_engine import _QtLogHandler
        assert isinstance(engine.log_handler, _QtLogHandler)

    def test_log_record_emitted_via_handler(self, engine):
        received = []
        engine.log_handler.record_emitted.connect(received.append)
        engine.namespace["log"].info("test message from engine")
        assert len(received) == 1
        assert received[0].getMessage() == "test message from engine"


# ---------------------------------------------------------------------------
# BasePlugin.log property
# ---------------------------------------------------------------------------


class TestBasePluginLog:
    def test_log_when_detached_returns_logger(self):
        plugin = DummyPlugin()
        assert isinstance(plugin.log, logging.Logger)

    def test_log_when_detached_not_sequence_logger(self):
        plugin = DummyPlugin()
        # Detached logger should not be the sequence logger (no engine attached).
        assert plugin.log.name != SEQUENCE_LOGGER_NAME

    def test_log_when_attached_returns_namespace_logger(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        assert plugin.log is engine.namespace["log"]

    def test_log_when_detached_after_removal(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        engine.remove_plugin("dummy")
        # After removal, log should revert to fallback (not the namespace logger).
        assert plugin.log is not engine.namespace["log"]
        assert isinstance(plugin.log, logging.Logger)


# ---------------------------------------------------------------------------
# LogViewerWindow
# ---------------------------------------------------------------------------


class TestLogViewerWindow:
    def test_creates_window(self, qapp):
        from stoner_measurement.ui.log_viewer import LogViewerWindow
        viewer = LogViewerWindow()
        assert viewer is not None

    def test_window_title(self, qapp):
        from stoner_measurement.ui.log_viewer import LogViewerWindow
        viewer = LogViewerWindow()
        assert viewer.windowTitle() == "Log Viewer"

    def test_append_record_does_not_raise(self, qapp):
        from stoner_measurement.ui.log_viewer import LogViewerWindow
        viewer = LogViewerWindow()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="info message",
            args=(),
            exc_info=None,
        )
        viewer.append_record(record)  # should not raise

    def test_clear_does_not_raise(self, qapp):
        from stoner_measurement.ui.log_viewer import LogViewerWindow
        viewer = LogViewerWindow()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="warn",
            args=(),
            exc_info=None,
        )
        viewer.append_record(record)
        viewer.clear()  # should not raise

    def test_show_and_raise_makes_visible(self, qapp):
        from stoner_measurement.ui.log_viewer import LogViewerWindow
        viewer = LogViewerWindow()
        viewer.show_and_raise()
        assert viewer.isVisible()
        viewer.hide()

    def test_stays_on_top_hint(self, qapp):
        from PyQt6.QtCore import Qt

        from stoner_measurement.ui.log_viewer import LogViewerWindow
        viewer = LogViewerWindow()
        flags = viewer.windowFlags()
        assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)

    def test_all_log_levels_append_without_error(self, qapp):
        from stoner_measurement.ui.log_viewer import LogViewerWindow
        viewer = LogViewerWindow()
        for level in (
            logging.DEBUG, logging.INFO, logging.WARNING,
            logging.ERROR, logging.CRITICAL,
        ):
            record = logging.LogRecord(
                name="test",
                level=level,
                pathname="",
                lineno=0,
                msg=f"level {level}",
                args=(),
                exc_info=None,
            )
            viewer.append_record(record)  # should not raise

    @pytest.mark.parametrize(
        ("mode", "expected", "unexpected"),
        [
            ("comms", "TX *IDN?", "regular message"),
            ("tx", "TX *IDN?", "RX answer"),
            ("rx", "RX answer", "TX *IDN?"),
            ("no-comms", "regular message", "TX *IDN?"),
        ],
    )
    def test_traffic_filter_modes(self, qapp, mode, expected, unexpected):
        from stoner_measurement.ui.log_viewer import LogViewerWindow

        viewer = LogViewerWindow()

        tx_record = logging.LogRecord(
            name="stoner_measurement.sequence.comms.Keithley2400",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="TX *IDN?",
            args=(),
            exc_info=None,
        )
        tx_record.sm_traffic_channel = "instrument_comms"
        tx_record.sm_traffic_direction = "TX"

        rx_record = logging.LogRecord(
            name="stoner_measurement.sequence.comms.Keithley2400",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="RX answer",
            args=(),
            exc_info=None,
        )
        rx_record.sm_traffic_channel = "instrument_comms"
        rx_record.sm_traffic_direction = "RX"

        regular_record = logging.LogRecord(
            name="stoner_measurement.sequence",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="regular message",
            args=(),
            exc_info=None,
        )

        viewer.append_record(tx_record)
        viewer.append_record(rx_record)
        viewer.append_record(regular_record)

        mode_index = viewer._traffic_filter.findData(mode)
        assert mode_index >= 0
        viewer._traffic_filter.setCurrentIndex(mode_index)

        output_text = viewer._output.toPlainText()
        assert expected in output_text
        assert unexpected not in output_text
