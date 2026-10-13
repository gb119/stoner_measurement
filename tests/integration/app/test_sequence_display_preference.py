"""Sequences retain their authored display across documents and execution."""

import json
from threading import Event, Thread
from types import SimpleNamespace

import numpy as np
import pytest
from qtpy.QtWidgets import QMessageBox

from stoner_measurement.core.plotting.contracts import PlotRequest
from stoner_measurement.core.plotting.producers import xy_update
from stoner_measurement.core.sequence_metadata import (
    metadata_from_flattened,
    sequence_json_from_metadata,
)
from stoner_measurement.core.serializer import rename_identifier_references, sequence_to_json
from stoner_measurement.plugins.command import SaveCommand
from stoner_measurement.plugins.trace import DummyPlugin
from stoner_measurement.ui.plotting.host import PlotDisplayHost
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry


@pytest.fixture(autouse=True)
def _accept_plot_reset(monkeypatch):
    """Choose the explicit reset option for incompatible manual switches."""
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: 0)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda self: next(
            (
                button
                for button in self.buttons()
                if button.text() in {"Clear and switch", "Switch to sequence display"}
            ),
            None,
        ),
    )


def test_display_choice_follows_sequence_tabs_and_saved_copy(qapp, managed_measurement_app):
    app = managed_measurement_app()
    first = app._active_sequence_document
    app._switch_plot_display("polar")
    assert app._engine.preferred_display_plugin == "polar"
    assert first.data["display_plugin"] == "polar"
    assert app._document_is_dirty(first)
    app._main_window.dock_panel.load_sequence([DummyPlugin()])
    app._main_window.dock_panel._sequence_tree.selectAll()
    app._main_window.dock_panel.copy_selected_step()
    assert json.loads(qapp.clipboard().text())["display_plugin"] == "polar"
    app._on_new_measurement()
    second = app._active_sequence_document
    app._switch_plot_display("cartesian")
    assert second.data["display_plugin"] == "cartesian"
    app._main_window.sequence_tabs.setCurrentIndex(0)
    assert app._engine.preferred_display_plugin == "polar"
    assert app._main_window.plot_display_host.factory_id == "polar"
    code, _ = app._generate_to_script_tab(switch_to_editor=False)
    assert 'select_display_plugin("polar")' in code
    app._main_window.sequence_tabs.setCurrentIndex(1)
    assert app._main_window.plot_display_host.factory_id == "cartesian"
    assert first.data["display_plugin"] == "polar"


def test_legacy_document_uses_cartesian_and_failed_activation_retains_sequence(
    managed_measurement_app, monkeypatch
):
    app = managed_measurement_app()
    app._switch_plot_display("polar")
    legacy = app._new_sequence_document({"steps": []})
    app._store_active_sequence()
    app._add_sequence_document(legacy)
    assert app._engine.preferred_display_plugin == "cartesian"
    assert not app._document_is_dirty(legacy)
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args: errors.append(_args))
    broken = app._new_sequence_document({"steps": [], "display_plugin": "missing"})
    assert not app._activate_sequence_document(broken.document_id)
    app._sequence_documents[broken.document_id] = broken
    assert not app._activate_sequence_document(broken.document_id)
    assert errors
    assert app._active_sequence_document is legacy
    assert app._engine.preferred_display_plugin == "cartesian"


def test_worker_selects_required_display_while_engine_busy(engine, managed_qt_widget, qtbot):
    registry = PlotDisplayRegistry()
    registry.discover()
    host = managed_qt_widget(PlotDisplayHost(registry=registry, factory_id="cartesian"))
    engine.plot_display_host = host
    engine.plot_client = host.service
    host.idle_check = lambda: False
    assert not host.switch_display("polar")
    errors = []
    engine.error_output.connect(errors.append)
    finished = []
    engine.script_finished.connect(lambda: finished.append(True))
    engine.run_script("select_display_plugin('polar')\nselected = True")
    qtbot.waitUntil(lambda: bool(finished), timeout=10000)
    assert not errors
    assert engine.namespace["selected"]
    assert host.factory_id == engine.preferred_display_plugin == "polar"


def test_required_selection_failure_rolls_back(engine, managed_qt_widget, qtbot):
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry()))
    engine.plot_display_host = host
    original = host.display
    with pytest.raises(RuntimeError, match="missing"):
        engine.select_display_plugin("missing")
    assert host.display is original
    assert engine.preferred_display_plugin == "cartesian"
    errors = []
    worker = Thread(target=lambda: _select_missing(host, errors))
    worker.start()
    qtbot.waitUntil(lambda: not worker.is_alive(), timeout=10000)
    worker.join()
    assert len(errors) == 1
    assert host.display is original


def _select_missing(host, errors):
    try:
        host.select_display("missing")
    except RuntimeError as exc:
        errors.append(exc)


def test_display_identifier_is_not_rewritten_as_a_plugin_reference():
    data = sequence_to_json([], display_plugin="polar")
    assert rename_identifier_references(data, "polar", "other")["display_plugin"] == "polar"


@pytest.mark.parametrize(
    "choice", ["Use current display for sequence", "Switch to sequence display", "Ignore"]
)
def test_tab_mismatch_offers_three_choices(managed_measurement_app, monkeypatch, choice):
    app = managed_measurement_app()
    app._switch_plot_display("polar")
    app._mark_measurement_clean()
    first = app._active_sequence_document
    app._on_new_measurement()
    app._switch_plot_display("cartesian")
    dialogs = []

    def choose(dialog):
        dialogs.append(dialog)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", choose)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda self: next(button for button in self.buttons() if button.text() == choice),
    )
    app._main_window.sequence_tabs.setCurrentIndex(0)
    assert len(dialogs) == 1
    assert {button.text() for button in dialogs[0].buttons()} == {
        "Use current display for sequence",
        "Switch to sequence display",
        "Ignore",
    }
    preferred = "cartesian" if choice == "Use current display for sequence" else "polar"
    display = "polar" if choice == "Switch to sequence display" else "cartesian"
    assert app._active_sequence_document is first
    assert first.data["display_plugin"] == preferred
    assert app._engine.preferred_display_plugin == preferred
    assert app._main_window.plot_display_host.factory_id == display
    assert app._document_is_dirty(first) == (choice == "Use current display for sequence")
    assert f"select_display_plugin({preferred!r})" in app._engine.generate_sequence_code([], {})


def test_matching_sequence_tab_does_not_prompt(managed_measurement_app, monkeypatch):
    app = managed_measurement_app()
    app._on_new_measurement()
    monkeypatch.setattr(
        QMessageBox, "exec", lambda _self: pytest.fail("matching display must not prompt")
    )
    app._main_window.sequence_tabs.setCurrentIndex(0)


def test_saved_data_metadata_restores_the_preferred_display(engine):
    command = SaveCommand()
    engine.add_plugin("save", command)
    engine.preferred_display_plugin = "polar"
    metadata = metadata_from_flattened(
        command._build_metadata(ns={"sequence": SimpleNamespace(steps=[DummyPlugin()])})
    )
    assert sequence_json_from_metadata(metadata)["display_plugin"] == "polar"


def test_cancelled_worker_selection_does_not_change_display(managed_qt_widget, qapp):
    registry = PlotDisplayRegistry()
    registry.discover()
    host = managed_qt_widget(PlotDisplayHost(registry=registry, factory_id="cartesian"))
    stopped = Event()
    stopped.set()
    errors = []

    def select():
        try:
            host.select_display("polar", stop_event=stopped)
        except RuntimeError as exc:
            errors.append(exc)

    worker = Thread(target=select)
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    qapp.processEvents()
    assert len(errors) == 1
    assert host.factory_id == "cartesian"


def test_selecting_current_plugin_preserves_plot_instance_and_data(
    engine, managed_qt_widget, monkeypatch
):
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry()))
    engine.plot_display_host = host
    engine.plot_client = host.service
    host.service.apply_now(PlotRequest(xy_update("existing", [1, 2], [3, 4])))
    original = host.display
    before = host.export_state()
    monkeypatch.setattr(
        engine, "wait_for_plot_ready", lambda **_kwargs: pytest.fail("same plugin must not wait")
    )
    engine.select_display_plugin("cartesian")
    assert host.display is original
    after = host.export_state()
    assert after.axes == before.axes
    assert after.renderer_settings == before.renderer_settings
    assert len(after.series) == 1
    assert after.series[0].update.series_id == "existing"
    for name, values in before.series[0].update.data.channels.items():
        np.testing.assert_array_equal(after.series[0].update.data.channels[name], values)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
