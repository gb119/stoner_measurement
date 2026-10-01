"""Display choices, selected checkmarks and refusal feedback in the View menu."""

from types import SimpleNamespace

import pytest
from qtpy.QtGui import QAction
from qtpy.QtWidgets import QMainWindow, QMessageBox

from stoner_measurement.app import MeasurementApp


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
