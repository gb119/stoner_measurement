"""SourceMeter model selection across set, point-scan and sweep plugins."""

import importlib
import json
from unittest.mock import MagicMock

import pytest
from qtpy.QtWidgets import QComboBox

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command.keithley_set import Keithley2400SetCommand
from stoner_measurement.plugins.state_scan.keithley_2400 import Keithley2400PointScanPlugin
from stoner_measurement.plugins.trace.keithley_2400 import Keithley2400SweepPlugin

PLUGIN_CLASSES = [Keithley2400SetCommand, Keithley2400PointScanPlugin, Keithley2400SweepPlugin]


def _instrument(plugin):
    """Return the object holding the SourceMeter settings and connection."""
    return plugin._point_plugin if isinstance(plugin, Keithley2400SetCommand) else plugin


@pytest.mark.parametrize("plugin_class", PLUGIN_CLASSES)
@pytest.mark.parametrize("model", ["2400", "2410", "2450"])
def test_model_selection_roundtrip(plugin_class, model, managed_plugin_config_tabs):
    plugin = plugin_class()
    pages = managed_plugin_config_tabs(plugin)
    combo = next(
        combo for _, page in pages
        for combo in page.findChildren(QComboBox, "sourceMeterModel")
    )
    assert [combo.itemData(index) for index in range(combo.count())] == ["2400", "2410", "2450"]
    combo.setCurrentIndex(combo.findData(model))
    restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
    assert _instrument(restored)._model == model
    restored_pages = managed_plugin_config_tabs(restored)
    restored_combo = next(
        combo for _, page in restored_pages
        for combo in page.findChildren(QComboBox, "sourceMeterModel")
    )
    assert restored_combo.currentData() == model


@pytest.mark.parametrize("plugin_class", PLUGIN_CLASSES)
def test_old_sequences_default_to_2400(plugin_class, qapp):
    plugin = plugin_class()
    data = plugin.to_json()
    settings = data["instrument"] if isinstance(plugin, Keithley2400SetCommand) else data
    settings.pop("model")
    restored = BasePlugin.from_json(data)
    assert _instrument(restored)._model == "2400"


@pytest.mark.parametrize("plugin_class", PLUGIN_CLASSES)
@pytest.mark.parametrize("model", ["2400", "2410", "2450"])
def test_selected_driver_connects_and_cleans_up(plugin_class, model, monkeypatch, qapp):
    plugin = plugin_class()
    instrument = _instrument(plugin)
    instrument._model = model
    instrument._resource = "GPIB0::24::INSTR"
    module = importlib.import_module(type(instrument).__module__)
    transport = MagicMock()
    monkeypatch.setattr(module.GpibTransport, "from_resource_string", lambda *a, **kw: transport)
    drivers = {name: MagicMock() for name in ("2400", "2410", "2450")}
    for name, driver in drivers.items():
        monkeypatch.setattr(module, f"Keithley{name}", driver)

    plugin.connect()
    selected = drivers[model]
    selected.assert_called_once_with(transport)
    selected.return_value.connect.assert_called_once()
    selected.return_value.confirm_identity.assert_called_once()
    for name, driver in drivers.items():
        if name != model:
            driver.assert_not_called()
    plugin.disconnect()
    if isinstance(plugin, Keithley2400SweepPlugin):
        selected.return_value.safe_output_off.assert_called_once()
    else:
        selected.return_value.enable_output.assert_called_with(False)
    selected.return_value.disconnect.assert_called_once()
    assert instrument._smu is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
