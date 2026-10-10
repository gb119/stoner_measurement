"""Display choices, selected checkmarks and refusal feedback in the View menu."""

from types import SimpleNamespace

import pytest
from qtpy.QtGui import QAction
from qtpy.QtWidgets import QMainWindow, QMessageBox

from stoner_measurement.app import MeasurementApp
from stoner_measurement.core.plotting.contracts import PlotRequest
from stoner_measurement.core.plotting.producers import xy_update
from stoner_measurement.ui.plotting.host import PlotDisplayHost
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry


class MenuWindow(QMainWindow):
    """Construct actual menus without starting unrelated instrument panels."""

    _build_menu_bar = MeasurementApp._build_menu_bar
    _switch_plot_display = MeasurementApp._switch_plot_display
    _refresh_plot_display_menu = MeasurementApp._refresh_plot_display_menu

    def __getattr__(self, name):
        if name.startswith("_act_"):
            action = QAction(name, self)
            setattr(self, name, action)
            return action
        raise AttributeError(name)


@pytest.mark.parametrize("allowed", [True, False])
def test_view_menu_selects_discovered_factories_and_restores_checkmark(
    allowed, managed_qt_widget, monkeypatch
):
    host = SimpleNamespace(
        factory_id="cartesian",
        diagnostics=[],
        switch_requires_reset=False,
        registry=SimpleNamespace(
            factories={
                "cartesian": SimpleNamespace(name="Cartesian traces"),
                "other": SimpleNamespace(name="Other display"),
            }
        ),
    )
    calls, warnings = [], []

    def switch(name):
        calls.append(name)
        if allowed:
            host.factory_id = name
        else:
            host.diagnostics.append("Display replacement requires an idle measurement engine.")
        return allowed

    host.switch_display = switch
    window = managed_qt_widget(MenuWindow())
    window._main_window = SimpleNamespace(plot_display_host=host)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    window._build_menu_bar()
    view = next(action.menu() for action in window.menuBar().actions() if action.text() == "&View")
    submenu = next(action.menu() for action in view.actions() if action.text() == "Plot display")
    assert [action.text() for action in submenu.actions()] == ["Cartesian traces", "Other display"]
    assert window._plot_display_actions["cartesian"].isChecked()
    window._plot_display_actions["other"].trigger()
    assert calls == ["other"]
    assert window._plot_display_actions["other"].isChecked() is allowed
    assert window._plot_display_actions["cartesian"].isChecked() is not allowed
    assert bool(warnings) is not allowed


@pytest.mark.parametrize("clear", [False, True])
def test_incompatible_menu_switch_offers_clear_or_cancel(managed_qt_widget, monkeypatch, clear):
    window = managed_qt_widget(MenuWindow())
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry()))
    window._main_window = SimpleNamespace(plot_display_host=host)
    window._build_menu_bar()
    host.service.apply_now(PlotRequest(xy_update("trace", [0, 1], [2, 3])))
    original = host.display_widget
    dialogs, warnings = [], []

    def choose(dialog):
        dialogs.append(dialog)
        assert dialog.defaultButton().text() == "Cancel"
        assert dialog.escapeButton() is dialog.defaultButton()
        assert "Acquired measurement data is retained" in dialog.informativeText()
        assert dialog.detailedText()
        label = "Clear and switch" if clear else "Cancel"
        dialog._test_selection = next(
            button for button in dialog.buttons() if button.text() == label
        )
        return 0

    monkeypatch.setattr(QMessageBox, "exec", choose)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda dialog: dialog._test_selection)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    window._plot_display_actions["cartesian_3d"].trigger()
    assert len(dialogs) == 1 and not warnings
    assert host.factory_id == ("cartesian_3d" if clear else "cartesian")
    assert window._plot_display_actions[host.factory_id].isChecked()
    if clear:
        assert not host.export_state().series
        assert not host.export_state().markers
        assert host.display_widget is not original
        with pytest.raises(KeyError):
            host.service.data_snapshot("trace")
    else:
        assert host.display_widget is original
        assert list(host.service.data_snapshot("trace").channels["y"]) == [2, 3]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
