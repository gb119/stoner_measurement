"""Data Manager trace-list and background-save behaviour."""

from __future__ import annotations

import threading

import pandas as pd
import pytest
from qtpy.QtCore import Qt

from stoner_measurement.core import COLUMN_ROLE_Y, COLUMN_ROLE_Z, TraceData
from stoner_measurement.plugins.command.save import TdiSaveWriter
from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.ui.data_manager import DataManagerWindow


def _install_collected_trace(engine) -> str:
    plugin = CounterPlugin()
    plugin.collect_data = True
    plugin._data = TraceData(  # noqa: SLF001
        pd.DataFrame(
            {"x": [10.0, 20.0], "signal": [2.5, 3.5], "stage": [0.0, 1.0]}
        ),
        column_roles={"signal": COLUMN_ROLE_Y, "stage": COLUMN_ROLE_Z},
        names={"x": "Field", "signal": "Signal", "stage": "Stage"},
        units={"x": "T", "signal": "V", "stage": ""},
    )
    engine._namespace[plugin.instance_name] = plugin  # noqa: SLF001
    engine.update_step_plugin_catalog([plugin])
    return f"{plugin.instance_name}.data"


def test_catalogue_row_shows_shape_and_column_tooltip(engine, managed_qt_widget):
    key = _install_collected_trace(engine)
    window = managed_qt_widget(DataManagerWindow(engine))

    item = window._trace_items[key]  # noqa: SLF001
    assert item.text(2) == "2 × 3"
    assert item.toolTip(2).splitlines() == ["Columns:", "Field (T)", "Signal (V)", "Stage"]
    assert window.selected_trace_keys == {key}
    assert set(window._save_buttons) == {"tdi", "nexus"}  # noqa: SLF001


def test_refresh_preserves_selection_and_updates_shape(engine, managed_qt_widget):
    key = _install_collected_trace(engine)
    window = managed_qt_widget(DataManagerWindow(engine))
    window._trace_items[key].setCheckState(0, Qt.CheckState.Unchecked)  # noqa: SLF001

    plugin = engine.evaluate_expression(key)
    plugin.df.loc[len(plugin.df)] = [30.0, 4.5, 2.0]
    window.refresh_traces()

    assert window._trace_items[key].text(2) == "3 × 3"  # noqa: SLF001
    assert window.selected_trace_keys == set()


def test_close_button_hides_reusable_window(qapp, engine, managed_qt_widget):
    window = managed_qt_widget(DataManagerWindow(engine))
    window.show()
    qapp.processEvents()

    window._btn_close.click()  # noqa: SLF001
    qapp.processEvents()

    assert not window.isVisible()


def test_save_runs_in_background_and_writes_selected_snapshot(
    engine,
    managed_qt_widget,
    monkeypatch,
    qtbot,
    tmp_path,
):
    key = _install_collected_trace(engine)
    window = managed_qt_widget(DataManagerWindow(engine))
    destination = tmp_path / "snapshot.txt"
    monkeypatch.setattr(window, "_choose_destination", lambda _format: destination)

    started = threading.Event()
    release = threading.Event()
    original_write = TdiSaveWriter.write

    def delayed_write(writer, *, dest, payload):
        started.set()
        assert release.wait(timeout=5)
        original_write(writer, dest=dest, payload=payload)

    monkeypatch.setattr(TdiSaveWriter, "write", delayed_write)

    window._save_selected("tdi")  # noqa: SLF001
    assert started.wait(timeout=2)
    assert window._active_workers  # noqa: SLF001
    assert engine.evaluate_expression(key).df.shape == (2, 3)
    engine.evaluate_expression(key).df.loc[0, "signal"] = 99.0

    release.set()
    qtbot.waitUntil(lambda: not window._active_workers, timeout=5000)  # noqa: SLF001

    lines = destination.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("TDI Format 2.0")
    assert lines[1].split("\t")[-3:] == ["10.0", "2.5", "0.0"]
    assert "Saved 1 trace" in window._status_label.text()  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
