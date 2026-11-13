"""Per-sensor NI scale choices, direction and machine YAML persistence."""

from copy import deepcopy

import pytest
import yaml

from stoner_measurement.instruments.lakeshore import Lakeshore335
from stoner_measurement.instruments.oxford import OxfordITC503
from stoner_measurement.instruments.transport import NullTransport
from stoner_measurement.temperature_control import config as config_module
from stoner_measurement.temperature_control import engine as engine_module
from stoner_measurement.ui import itc503_input_settings as editor_module
from stoner_measurement.ui.temperature_panel import _InputSettingsTableWidget

SCALE = {
    "scale_name": "sensor calibration",
    "direction": "nominal_to_corrected",
    "pre_scaled_values": [1.0, 10.0, 20.0],
    "scaled_values": [2.0, 11.0, 21.0],
}


@pytest.fixture
def rig(qapp, monkeypatch, tmp_path):
    path = tmp_path / "temperature_controller.yaml"
    monkeypatch.setattr(config_module, "machine_config_path", lambda: path)
    monkeypatch.setattr(
        engine_module,
        "load_temperature_controller_config",
        lambda: yaml.safe_load(path.read_text()) if path.exists() else {},
    )
    engine = engine_module.TemperatureControllerEngine()
    engine.set_polling_rate(0)
    monkeypatch.setattr(engine_module.TemperatureControllerEngine, "_singleton", engine)
    for session in engine.controllers.values():
        transport = NullTransport()
        transport.open()
        session._driver = OxfordITC503(transport)
    yield engine, path
    engine.shutdown()


@pytest.fixture
def editor(rig, managed_qt_widget, monkeypatch):
    engine, path = rig
    monkeypatch.setattr(
        editor_module, "list_daqmx_scales", lambda: ("sensor calibration", "bad scale")
    )
    monkeypatch.setattr(editor_module, "load_daqmx_temperature_scale", lambda name: deepcopy(SCALE))
    widget = managed_qt_widget(editor_module.ITC503InputSettingsTable(engine))
    widget.set_channels(("A", "B", "C"))
    return widget, engine, path


def select(combo, value):
    """Select a persisted item value, including the explicit None choice."""
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_select_scale_direction_and_none_persist_per_channel(editor):
    widget, engine, path = editor
    assert not widget._write_button.isEnabled()
    with pytest.raises(RuntimeError, match="Read input"):
        widget.write_all()
    assert widget.read_all()
    select(widget._editors["A"]["scale"], "sensor calibration")
    select(widget._editors["A"]["direction"], "corrected_to_nominal")
    select(widget._editors["B"]["scale"], None)
    widget.write_all()
    expected = {"A": dict(SCALE, direction="corrected_to_nominal"), "B": None}
    assert engine.get_itc503_temperature_scales() == expected
    saved = yaml.safe_load(path.read_text())
    assert saved["controllers"]["primary"]["itc503_calibration"] == expected
    assert saved["controllers"]["secondary"]["itc503_calibration"] == {}
    assert not engine.connected_driver.transport.write_log


def test_offline_saved_scale_survives_direction_changes_and_restart(editor, monkeypatch):
    widget, engine, path = editor
    engine.set_itc503_temperature_scales({"A": SCALE})

    def unavailable():
        raise RuntimeError("NI driver missing")

    monkeypatch.setattr(editor_module, "list_daqmx_scales", unavailable)
    monkeypatch.setattr(
        editor_module, "load_daqmx_temperature_scale", lambda name: pytest.fail("NI import")
    )
    assert widget.read_all()
    assert widget._editors["A"]["scale"].currentData() == SCALE["scale_name"]
    select(widget._editors["A"]["direction"], "corrected_to_nominal")
    widget.write_all()
    expected = engine.get_itc503_temperature_scales()
    restarted = engine_module.TemperatureControllerEngine()
    restarted.set_polling_rate(0)
    try:
        driver = OxfordITC503(NullTransport())
        monkeypatch.setattr(driver, "confirm_identity", lambda: "ITC503")
        restarted.connect_instrument(driver)
        assert restarted.get_itc503_temperature_scales() == expected
        assert path.exists()
    finally:
        restarted.shutdown()


def test_secondary_calibration_does_not_replace_primary(rig):
    engine, path = rig
    engine.set_itc503_temperature_scales({"A": None})
    engine.controller("secondary").set_itc503_temperature_scales({"B": SCALE})
    saved = yaml.safe_load(path.read_text())
    assert saved["controllers"]["primary"]["itc503_calibration"] == {"A": None}
    assert saved["controllers"]["secondary"]["itc503_calibration"] == {"B": SCALE}
    assert engine.get_itc503_temperature_scales() == {"A": None}


def test_failed_import_does_not_apply_any_channel(editor, monkeypatch):
    widget, engine, path = editor
    assert widget.read_all()
    select(widget._editors["A"]["scale"], "sensor calibration")
    select(widget._editors["B"]["scale"], "bad scale")

    def load(name):
        if name == "bad scale":
            raise ValueError("not a table")
        return deepcopy(SCALE)

    monkeypatch.setattr(editor_module, "load_daqmx_temperature_scale", load)
    with pytest.raises(ValueError, match="not a table"):
        widget.write_all()
    assert engine.get_itc503_temperature_scales() == {}
    assert not path.exists()


def test_explicit_reload_updates_saved_table(editor, monkeypatch):
    widget, engine, _path = editor
    engine.set_itc503_temperature_scales({"A": SCALE})
    assert widget.read_all()
    updated = dict(SCALE, scaled_values=[3.0, 12.0, 22.0])
    monkeypatch.setattr(
        editor_module, "load_daqmx_temperature_scale", lambda name: deepcopy(updated)
    )
    widget._reload_tables.setChecked(True)
    widget.write_all()
    assert engine.get_itc503_temperature_scales()["A"] == updated
    assert not widget._reload_tables.isChecked()


def test_failed_yaml_save_restores_active_scales(rig, monkeypatch):
    engine, path = rig
    engine.set_itc503_temperature_scales({"A": SCALE})
    before = path.read_text()

    def fail():
        raise OSError("disk unavailable")

    monkeypatch.setattr(engine, "save_configuration", fail)
    with pytest.raises(OSError, match="disk unavailable"):
        engine.set_itc503_temperature_scales({"A": None})
    assert engine.get_itc503_temperature_scales() == {"A": SCALE}
    assert path.read_text() == before


@pytest.mark.parametrize("slot", ["primary", "secondary"])
def test_panel_routes_software_editor_and_switches_back(
    rig, slot, managed_temperature_panel, monkeypatch
):
    engine, _path = rig
    panel = managed_temperature_panel()
    session = engine.controller(slot)
    monkeypatch.setattr(editor_module, "list_daqmx_scales", lambda: ())
    attribute = "_input_settings_widget" if slot == "primary" else "_secondary_input_settings"
    panel._select_input_settings_editor(
        attribute, session, session.connected_driver.get_capabilities()
    )
    widget = getattr(panel, attribute)
    widget.set_channels(("A", "B", "C"))
    assert isinstance(widget, editor_module.ITC503InputSettingsTable)
    assert widget._engine is session
    assert widget.read_all()
    panel._select_input_settings_editor(
        attribute, session, Lakeshore335(NullTransport()).get_capabilities()
    )
    # pylint: disable-next=unidiomatic-typecheck
    assert type(getattr(panel, attribute)) is _InputSettingsTableWidget


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
