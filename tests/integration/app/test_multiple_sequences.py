"""Integration tests for serialized multi-sequence document tabs."""

from __future__ import annotations

import json

import pytest
from qtpy.QtWidgets import QFileDialog, QMessageBox

from stoner_measurement.app import MeasurementApp
from stoner_measurement.plugins.trace import DummyPlugin


def test_startup_creates_one_sequence_document_and_tab(qapp):
    app = MeasurementApp()
    try:
        assert app._main_window.sequence_tabs.count() == 1
        assert len(app._sequence_documents) == 1
        assert app._active_sequence_document is not None
        assert app._active_sequence_document.document_id == app._active_sequence_id
    finally:
        app._engine.shutdown()


def test_new_sequence_snapshots_outgoing_tree_and_switch_restores_it(qapp):
    app = MeasurementApp()
    try:
        first_id = app._active_sequence_id
        first_index = app._main_window.sequence_tabs.currentIndex()
        app._main_window.dock_panel.load_sequence([DummyPlugin()])

        app._on_new_measurement()

        assert app._main_window.sequence_tabs.count() == 2
        assert app._active_sequence_id != first_id
        assert len(app._sequence_documents[first_id].data["steps"]) == 1

        app._main_window.sequence_tabs.setCurrentIndex(first_index)

        restored = app._main_window.dock_panel.sequence_steps
        assert len(restored) == 1
        assert isinstance(restored[0], DummyPlugin)
    finally:
        app._engine.shutdown()


def test_dirty_sequence_close_cancel_keeps_tab_open(qapp, monkeypatch):
    app = MeasurementApp()
    try:
        app._main_window.dock_panel.load_sequence([DummyPlugin()])
        index = app._main_window.sequence_tabs.currentIndex()
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *_args: QMessageBox.StandardButton.Cancel,
        )

        app._close_sequence_tab(index)

        assert app._main_window.sequence_tabs.count() == 1
        assert len(app._sequence_documents) == 1
        assert len(app._main_window.dock_panel.sequence_steps) == 1
    finally:
        app._engine.shutdown()


def test_close_all_checks_documents_in_tab_order_and_stops_on_cancel(qapp, monkeypatch):
    app = MeasurementApp()
    try:
        app._on_new_measurement()
        app._on_new_measurement()
        ordered_ids = [
            app._main_window.sequence_tabs.tabData(index)
            for index in range(app._main_window.sequence_tabs.count())
        ]
        checked: list[str] = []
        monkeypatch.setattr(app, "_store_active_sequence", lambda: None)

        def confirm(document):
            checked.append(document.document_id)
            return len(checked) < 2

        monkeypatch.setattr(app, "_confirm_close_sequence", confirm)

        assert app._confirm_close_all_sequences() is False
        assert checked == ordered_ids[:2]
    finally:
        app._engine.shutdown()


def test_inactive_document_can_be_saved_without_loading_it(qapp, tmp_path):
    app = MeasurementApp()
    try:
        first = app._active_sequence_document
        assert first is not None
        app._main_window.dock_panel.load_sequence([DummyPlugin()])
        app._store_active_sequence()
        app._on_new_measurement()
        assert app._active_sequence_document is not first
        destination = tmp_path / "first.json"

        assert app._save_sequence_document_to(first, destination) is True

        assert json.loads(destination.read_text(encoding="utf-8")) == first.data
        assert app._document_is_dirty(first) is False
        assert app._active_sequence_document is not first
    finally:
        app._engine.shutdown()


def test_opening_an_already_open_path_focuses_existing_tab(qapp, monkeypatch, tmp_path):
    app = MeasurementApp()
    try:
        sequence_path = tmp_path / "sequence.json"
        sequence_path.write_text(
            json.dumps(app._active_sequence_document.data),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *_args: (str(sequence_path), "JSON Files"),
        )

        app._on_open_measurement()
        opened_id = app._active_sequence_id
        app._main_window.sequence_tabs.setCurrentIndex(0)
        app._on_open_measurement()

        assert app._main_window.sequence_tabs.count() == 2
        assert app._active_sequence_id == opened_id
    finally:
        app._engine.shutdown()


def test_sequence_tabs_are_disabled_while_engine_is_active(qapp):
    app = MeasurementApp()
    try:
        app._on_engine_status_changed("Running")
        assert app._main_window.sequence_tabs.isEnabled() is False

        app._on_engine_status_changed("Idle")
        assert app._main_window.sequence_tabs.isEnabled() is True
    finally:
        app._engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
