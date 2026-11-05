"""Script generation reports configuration errors before execution."""

from unittest.mock import MagicMock

import pytest

from stoner_measurement.plugins.trace import DummyPlugin
from stoner_measurement.scan.list_generator import ListScanGenerator


def test_generation_reports_invalid_nested_target_and_preserves_editor(managed_measurement_app, monkeypatch):
    app = managed_measurement_app()
    parent = DummyPlugin()
    child = DummyPlugin()
    child.instance_name = "child_trace"
    child.scan_generator = ListScanGenerator(stages=[("current **", True)], parent=child)
    child.connect = MagicMock()
    app._main_window.dock_panel.load_sequence([(parent, [child])])
    previous = app._main_window.script_tab.text
    dialogs = []
    monkeypatch.setattr(
        "stoner_measurement.app.QMessageBox.warning",
        lambda _, title, message: dialogs.append((title, message)),
    )
    assert app._generate_to_script_tab(switch_to_editor=True) is None
    assert dialogs[0][0] == "Sequence Validation Error"
    assert "child_trace" in dialogs[0][1]
    assert "point 1" in dialogs[0][1]
    assert app._main_window.script_tab.text == previous
    child.connect.assert_not_called()


def test_generation_warns_for_unknown_names_without_evaluating(managed_measurement_app, monkeypatch, caplog):
    app = managed_measurement_app()
    step = DummyPlugin()
    step.scan_generator = ListScanGenerator(stages=[("later_value * 2", True)], parent=step)
    app._main_window.dock_panel.load_sequence([step])
    step.eval_float = MagicMock(side_effect=AssertionError("must not evaluate"))
    dialog = MagicMock()
    monkeypatch.setattr("stoner_measurement.app.QMessageBox.warning", dialog)
    generated = app._generate_to_script_tab(switch_to_editor=True)
    assert generated is not None
    assert "later_value * 2" in generated[0]
    assert "later_value" in caplog.text
    dialog.assert_not_called()
    step.eval_float.assert_not_called()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
