"""Data Manager trace inspection, plotting and background exports."""

from __future__ import annotations

import threading

import pandas as pd
import pytest
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QComboBox, QPushButton, QTableView

from stoner_measurement.core import COLUMN_ROLE_E, COLUMN_ROLE_Y, COLUMN_ROLE_Z, TraceData
from stoner_measurement.plugins.command.save import TdiSaveWriter
from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.ui.data_manager import DataManagerWindow
from stoner_measurement.ui.plotting.host import PlotDisplayHost
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry
from stoner_measurement.ui.trace_plot_dialog import TracePlotDialog


def _install_collected_trace(engine, *, name=None, error=False) -> str:
    plugin = CounterPlugin()
    if name is not None:
        plugin.instance_name = name
    plugin.collect_data = True
    columns = {"x": [10.0, 20.0], "signal": [2.5, 3.5], "stage": [0.0, 1.0]}
    roles = {"signal": COLUMN_ROLE_Y, "stage": COLUMN_ROLE_Z}
    if error:
        columns["error"] = [0.2, 0.3]
        roles["error"] = COLUMN_ROLE_E
    plugin._data = TraceData(  # noqa: SLF001
        pd.DataFrame(columns),
        column_roles=roles,
        names={"x": "Field", "signal": "Signal", "stage": "Stage"},
        units={"x": "T", "signal": "V", "stage": ""},
    )
    engine._namespace[plugin.instance_name] = plugin  # noqa: SLF001
    engine.update_step_plugin_catalog(
        [item for item in engine._namespace.values() if isinstance(item, CounterPlugin)]  # noqa: SLF001
    )
    return f"{plugin.instance_name}.data"


def test_catalogue_row_shows_shape_and_column_tooltip(engine, managed_qt_widget):
    key = _install_collected_trace(engine)
    window = managed_qt_widget(DataManagerWindow(engine))

    item = window._trace_items[key]  # noqa: SLF001
    assert item.text(2) == "2 × 3"
    assert item.toolTip(2).splitlines() == ["Columns:", "Field (T)", "Signal (V)", "Stage"]
    assert window.selected_trace_keys == {key}
    assert set(window._save_actions) == {"tdi", "nexus"}  # noqa: SLF001


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


def test_trace_tab_shows_dataframe_and_retains_selection_as_catalogue_changes(
    engine, managed_qt_widget
):
    key = _install_collected_trace(engine, name="second")
    window = managed_qt_widget(DataManagerWindow(engine))
    tabs = window._tabs  # noqa: SLF001
    tabs.setCurrentIndex(1)
    page = tabs.currentWidget()
    table = page.findChild(QTableView)
    model = table.model()
    assert tabs.tabText(1) == key
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Signal (V)"
    assert model.data(model.index(0, 1)) == "2.5"
    table.setCurrentIndex(model.index(0, 1))

    engine.evaluate_expression(key).df.loc[2] = [30.0, 4.5, 2.0]
    first = _install_collected_trace(engine, name="first")
    window.refresh_traces()
    assert tabs.currentWidget() is page
    assert tabs.tabText(1) == first
    assert model.rowCount() == 3
    assert model.data(model.index(2, 1)) == "4.5"
    assert table.currentIndex() == model.index(0, 1)

    engine.update_step_plugin_catalog([])
    window.refresh_traces()
    assert tabs.count() == 1
    assert not window._plot_action.isEnabled()  # noqa: SLF001


def test_trace_plot_dialog_overlays_different_selected_columns(engine, managed_qt_widget):
    key = _install_collected_trace(engine, error=True)
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry()))
    engine.plot_client = host.service
    window = managed_qt_widget(DataManagerWindow(engine))
    window.show()
    window._tabs.setCurrentIndex(1)  # noqa: SLF001
    window._plot_action.trigger()  # noqa: SLF001
    dialog = window.findChild(TracePlotDialog)
    assert dialog.isVisible()
    assert not dialog.isModal()
    assert not window.isVisible()
    window.show_and_raise()
    assert dialog.isVisible()
    assert not window.isVisible()

    x_combo = dialog.findChild(QComboBox, "xChannel")
    y_combo = dialog.findChild(QComboBox, "yChannel")
    send = next(
        button
        for button in dialog.findChildren(QPushButton)
        if button.text() == "Send to Plot Window"
    )

    send.click()
    x_combo.setCurrentIndex(x_combo.findData("stage"))
    send.click()
    assert dialog.isVisible()

    default, alternate = host.service.series()
    assert default.title == f"{key}: Signal vs Field"
    assert alternate.title == f"{key}: Signal vs Stage"
    widget = host.display_widget
    assert widget.x_data(default.series_id) == [10.0, 20.0]
    assert widget.x_data(alternate.series_id) == [0.0, 1.0]
    assert widget.y_data(alternate.series_id) == [2.5, 3.5]
    x_error, y_error = widget.trace_uncertainties(alternate.series_id)
    assert x_error is None
    assert y_error.tolist() == pytest.approx([0.2, 0.3])

    y_combo.setCurrentIndex(y_combo.findData("stage"))
    send.click()
    new_series = host.service.series()[-1]
    assert widget.y_data(new_series.series_id) == [0.0, 1.0]

    dialog.close()
    assert window.isVisible()
    assert window._tabs.tabText(window._tabs.currentIndex()) == key  # noqa: SLF001


def test_closing_manager_closes_plot_dialog_without_showing_manager(engine, managed_qt_widget):
    _install_collected_trace(engine)
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry()))
    engine.plot_client = host.service
    window = managed_qt_widget(DataManagerWindow(engine))
    window.show()
    window._tabs.setCurrentIndex(1)  # noqa: SLF001
    window._plot_action.trigger()  # noqa: SLF001
    dialog = window.findChild(TracePlotDialog)
    with pytest.MonkeyPatch.context() as patch:
        restored = []
        patch.setattr(window, "show_and_raise", lambda: restored.append(True))
        window.close()
    assert not restored
    assert not dialog.isVisible()
    assert not window.isVisible()


@pytest.mark.parametrize("trace_tab", [False, True])
def test_save_runs_in_background_and_writes_selected_snapshot(
    engine,
    managed_qt_widget,
    monkeypatch,
    qtbot,
    tmp_path,
    trace_tab,
):
    key = _install_collected_trace(engine)
    if trace_tab:
        _install_collected_trace(engine, name="other")
    window = managed_qt_widget(DataManagerWindow(engine))
    if trace_tab:
        tabs = window._tabs  # noqa: SLF001
        tabs.setCurrentIndex(next(i for i in range(tabs.count()) if tabs.tabText(i) == key))
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

    window._save_actions["tdi"].trigger()  # noqa: SLF001
    assert started.wait(timeout=2)
    assert window._active_workers  # noqa: SLF001
    assert engine.evaluate_expression(key).df.shape == (2, 3)
    engine.evaluate_expression(key).df.loc[0, "signal"] = 99.0

    release.set()
    qtbot.waitUntil(lambda: not window._active_workers, timeout=5000)  # noqa: SLF001

    lines = destination.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("TDI Format 2.0")
    assert lines[1].split("\t")[-3:] == ["10.0", "2.5", "0.0"]
    assert "other.data" not in lines[0]
    assert "Saved 1 trace" in window._status_label.text()  # noqa: SLF001


def test_trace_tab_saves_nexus(engine, managed_qt_widget, monkeypatch, qtbot, tmp_path):
    h5py = pytest.importorskip("h5py")
    key = _install_collected_trace(engine)
    window = managed_qt_widget(DataManagerWindow(engine))
    window._tabs.setCurrentIndex(1)  # noqa: SLF001
    destination = tmp_path / "snapshot.nxs"
    monkeypatch.setattr(window, "_choose_destination", lambda _format: destination)
    window._save_actions["nexus"].trigger()  # noqa: SLF001
    qtbot.waitUntil(lambda: not window._active_workers, timeout=5000)  # noqa: SLF001

    with h5py.File(destination) as handle:
        data = handle["entry/data"]
        signal = data[data.attrs["signal"]]
        assert signal.attrs["original_name"] == f"{key}:Signal (V)"
        assert signal[:].tolist() == [2.5, 3.5]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
