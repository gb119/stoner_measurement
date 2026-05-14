"""Tests for the log viewer widgets and filtering behaviour."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QSettings

from stoner_measurement.ui.log_viewer import LogSourcesWidget, LogViewerWindow


def _make_record(
    name: str,
    level: int,
    message: str,
    *,
    channel: str = "",
    direction: str = "",
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.sm_traffic_channel = channel
    record.sm_traffic_direction = direction
    return record


def _configure_test_settings(qapp, tmp_path) -> None:
    qapp.setOrganizationName("stoner-measurement-tests")
    qapp.setApplicationName("log-viewer")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings().clear()
    QSettings().sync()


class TestLogSourcesWidget:
    def test_register_source_groups_items(self, qapp):
        widget = LogSourcesWidget()
        widget.register_source("stoner_measurement.sequence")
        widget.register_source("stoner_measurement.sequence.comms.Keithley2400")
        widget.register_source("stoner_measurement.plugins.trace.dummy.DummyPlugin")

        assert widget._group_items["sequence"].childCount() == 1
        assert widget._group_items["instruments"].child(0).text(0) == "Keithley2400"
        assert widget._group_items["plugins"].child(0).text(0) == "DummyPlugin"

    def test_pending_selection_applies_to_later_sources(self, qapp):
        widget = LogSourcesWidget()
        wanted = {"stoner_measurement.plugins.trace.dummy.DummyPlugin"}
        widget.set_selected_prefixes(wanted)

        widget.register_source("stoner_measurement.sequence")
        widget.register_source("stoner_measurement.plugins.trace.dummy.DummyPlugin")

        assert widget.selected_prefixes == wanted


class TestLogViewerWindowFiltering:
    def test_filters_by_level_and_source(self, qapp):
        viewer = LogViewerWindow()
        info_record = _make_record("stoner_measurement.sequence", logging.INFO, "sequence info")
        warning_record = _make_record(
            "stoner_measurement.plugins.trace.dummy.DummyPlugin",
            logging.WARNING,
            "plugin warning",
        )
        error_record = _make_record(
            "stoner_measurement.sequence.comms.Keithley2400",
            logging.ERROR,
            "instrument error",
            channel="instrument_comms",
            direction="TX",
        )

        viewer.append_record(info_record)
        viewer.append_record(warning_record)
        viewer.append_record(error_record)

        viewer._display_level.setCurrentIndex(viewer._display_level.findData(logging.WARNING))
        viewer._display_sources.set_selected_prefixes({"stoner_measurement.plugins.trace.dummy.DummyPlugin"})
        viewer._on_filter_changed()

        output_text = viewer._output.toPlainText()
        assert "plugin warning" in output_text
        assert "sequence info" not in output_text
        assert "instrument error" not in output_text

    def test_restores_saved_settings(self, qapp, tmp_path):
        _configure_test_settings(qapp, tmp_path)

        first = LogViewerWindow()
        first._display_level.setCurrentIndex(first._display_level.findData(logging.ERROR))
        first._traffic_filter.setCurrentIndex(first._traffic_filter.findData("no-comms"))
        first._display_sources.set_selected_prefixes({"stoner_measurement.sequence"})
        first._btn_display_sources.setChecked(True)
        first._btn_file_logging.setChecked(True)
        first._file_enabled.setChecked(True)
        first._file_path.setText(str(tmp_path / "saved.log"))
        first._file_mode.setCurrentIndex(first._file_mode.findData(False))
        first._file_level.setCurrentIndex(first._file_level.findData(logging.CRITICAL))
        first._file_sources.set_selected_prefixes({"stoner_measurement.plugins.trace.dummy.DummyPlugin"})
        first._save_settings()

        second = LogViewerWindow()

        assert second._display_level.currentData() == logging.ERROR
        assert second._traffic_filter.currentData() == "no-comms"
        assert second._display_sources.selected_prefixes == {"stoner_measurement.sequence"}
        assert second._btn_display_sources.isChecked()
        assert second._btn_file_logging.isChecked()
        assert second._file_enabled.isChecked()
        assert second._file_path.text() == str(tmp_path / "saved.log")
        assert second._file_mode.currentData() is False
        assert second._file_level.currentData() == logging.CRITICAL
        assert second._file_sources.selected_prefixes == {
            "stoner_measurement.plugins.trace.dummy.DummyPlugin"
        }


class TestLogViewerFileLogging:
    def test_writes_matching_records_to_file(self, qapp, tmp_path):
        _configure_test_settings(qapp, tmp_path)
        viewer = LogViewerWindow()

        matching_record = _make_record(
            "stoner_measurement.plugins.trace.dummy.DummyPlugin",
            logging.ERROR,
            "file target",
        )
        ignored_record = _make_record(
            "stoner_measurement.sequence.comms.Keithley2400",
            logging.INFO,
            "ignore me",
            channel="instrument_comms",
            direction="RX",
        )
        viewer._on_source_registered(matching_record.name)
        viewer._on_source_registered(ignored_record.name)

        file_path = tmp_path / "viewer.log"
        viewer._file_enabled.setChecked(True)
        viewer._file_path.setText(str(file_path))
        viewer._file_level.setCurrentIndex(viewer._file_level.findData(logging.WARNING))
        viewer._file_sources.set_selected_prefixes({matching_record.name})
        viewer._apply_file_logging()

        viewer.append_record(ignored_record)
        viewer.append_record(matching_record)
        viewer._stop_file_logging()

        log_text = file_path.read_text(encoding="utf-8")
        assert "file target" in log_text
        assert "ignore me" not in log_text
        assert viewer._file_status.text() == "Not logging"
