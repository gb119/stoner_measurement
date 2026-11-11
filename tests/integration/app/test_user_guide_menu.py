"""The Help menu and F1 share the offline guide action."""

import pytest
from qtpy.QtCore import Qt

import stoner_measurement.app as app_module


def test_menu_and_f1_open_user_guide(managed_measurement_app, monkeypatch, qtbot):
    calls = []
    monkeypatch.setattr(app_module, "open_user_guide", lambda: calls.append(True))
    app = managed_measurement_app()
    app.show()
    app.activateWindow()
    help_menu = next(a.menu() for a in app.menuBar().actions() if a.text() == "&Help")
    assert app._act_user_guide in help_menu.actions()
    app._act_user_guide.trigger()
    assert calls == [True]
    qtbot.waitUntil(app.isActiveWindow)
    qtbot.keyClick(app, Qt.Key.Key_F1)
    assert calls == [True, True]


def test_guide_launch_error_is_reported(managed_measurement_app, monkeypatch):
    def fail():
        raise OSError("Guide unavailable")

    messages = []
    monkeypatch.setattr(app_module, "open_user_guide", fail)
    monkeypatch.setattr(app_module.QMessageBox, "warning", lambda *args: messages.append(args))
    app = managed_measurement_app()
    app._act_user_guide.trigger()
    assert messages[0][1:] == ("User Guide", "Guide unavailable")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
