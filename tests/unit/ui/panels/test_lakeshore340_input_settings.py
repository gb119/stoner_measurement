"""Native Model 340 input editor, routing and hardware-write regressions."""

from dataclasses import replace

import pytest
from qtpy.QtWidgets import QMessageBox, QPushButton

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.lakeshore import (
    Lakeshore335,
    Lakeshore340,
    Lakeshore340InputSettings,
)
from stoner_measurement.instruments.transport import NullTransport
from stoner_measurement.temperature_control import engine as engine_module
from stoner_measurement.ui.lakeshore340_input_settings import Lakeshore340InputSettingsTable
from stoner_measurement.ui.temperature_panel import _InputSettingsTableWidget


class InputTransport(NullTransport):
    """Model the native input commands and the defaults loaded by a sensor preset."""

    def __init__(self):
        super().__init__()
        self.settings = {
            "A": Lakeshore340InputSettings(
                sensor_type=8,
                sensor_units=2,
                coefficient=1,
                excitation=7,
                range_=8,
                input_enabled=True,
                compensation_mode=2,
                filter_enabled=True,
                filter_points=10,
                filter_window=2,
                curve_number=22,
            ),
            "B": Lakeshore340InputSettings(
                sensor_type=1,
                sensor_units=1,
                coefficient=1,
                excitation=6,
                range_=11,
                input_enabled=True,
                compensation_mode=0,
                filter_enabled=False,
                filter_points=10,
                filter_window=1,
                curve_number=1,
            ),
        }
        self.read_failure = False
        self.write_failure = False

    def write(self, data, slow=None):
        super().write(data, slow=slow)
        command = data.decode().strip()
        name, _, arguments = command.partition(" ")
        if name == "*ESR?":
            self.queue_response(b"16\r\n" if self.write_failure else b"0\r\n")
            return 0
        if name == "CRVHDR?":
            self.queue_response(f'"Curve {arguments}","SN",2,300,1\r\n'.encode())
            return 0
        channel, *values = arguments.split(",")
        settings = self.settings[channel]
        if name.endswith("?"):
            if self.read_failure:
                raise TimeoutError("Input readback unavailable")
            queries = {
                "INTYPE?": ("sensor_type", "sensor_units", "coefficient", "excitation", "range_"),
                "INSET?": ("input_enabled", "compensation_mode"),
                "FILTER?": ("filter_enabled", "filter_points", "filter_window"),
                "INCRV?": ("curve_number",),
            }
            reply = ",".join(
                str(int(value) if isinstance(value, bool) else value)
                for value in (getattr(settings, key) for key in queries[name])
            )
            self.queue_response((reply + "\r\n").encode())
            return 0
        keys = {
            "INTYPE": ("sensor_type", "sensor_units", "coefficient", "excitation", "range_"),
            "INSET": ("input_enabled", "compensation_mode"),
            "FILTER": ("filter_enabled", "filter_points", "filter_window"),
            "INCRV": ("curve_number",),
        }[name]
        changed = {}
        for key, value in zip(keys, values, strict=True):
            if value:
                changed[key] = float(value) if key == "filter_window" else int(value)
        if name == "INTYPE":
            if any(value for value in values[1:]):
                changed["sensor_type"] = 0
            elif changed.get("sensor_type") == 1:
                changed.update(sensor_units=1, coefficient=1, excitation=6, range_=11)
        self.settings[channel] = replace(settings, **changed)
        return 0


@pytest.fixture
def rig(monkeypatch, qapp):
    monkeypatch.setattr(engine_module, "load_temperature_controller_config", lambda: {})
    engine = engine_module.TemperatureControllerEngine()
    engine.set_polling_rate(0)
    monkeypatch.setattr(engine_module.TemperatureControllerEngine, "_singleton", engine)
    yield engine
    engine.shutdown()


@pytest.fixture
def editor(rig, managed_qt_widget, monkeypatch):
    transport = InputTransport()
    transport.open()
    rig._driver = Lakeshore340(transport)
    widget = managed_qt_widget(Lakeshore340InputSettingsTable(rig))
    widget.set_channels(("A", "B"))
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *_args: pytest.fail("Unexpected hardware warning")
    )
    return widget, transport


def _select(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def _click(widget, text):
    next(button for button in widget.findChildren(QPushButton) if button.text() == text).click()


def test_read_enables_native_controls_and_preserves_paused_compensation(editor):
    widget, transport = editor
    assert not widget._write_button.isEnabled()
    with pytest.raises(RuntimeError, match="Read input"):
        widget.write_all()
    assert not transport.write_log
    _click(widget, "Read All")
    controls = widget._editors["A"]
    assert widget._write_button.isEnabled()
    assert controls["sensor_type"].currentText() == "Cernox"
    assert controls["sensor_units"].currentText() == "Ohms"
    assert controls["excitation"].currentText() == "30 µA"
    assert controls["range_"].currentText() == "250 mV"
    assert controls["compensation_mode"].currentText() == "Paused"
    assert not controls["excitation"].isEnabled()
    assert "autorange" not in controls and "units" not in controls
    transport.write_log.clear()
    _click(widget, "Write All")
    assert transport.write_log == []


def test_sensor_preset_write_leaves_native_defaults_implicit_and_reads_them_back(editor):
    widget, transport = editor
    widget.read_all()
    _select(widget._editors["A"]["sensor_type"], 1)
    transport.write_log.clear()
    _click(widget, "Write All")
    assert transport.write_log == [
        b"INTYPE A,1,,,,\r\n",
        b"*ESR?\r\n",
        b"INTYPE? A\r\n",
        b"INSET? A\r\n",
        b"FILTER? A\r\n",
        b"INCRV? A\r\n",
    ]
    assert transport.settings["A"].sensor_type == 1
    assert widget._editors["A"]["sensor_units"].currentData() == 1
    assert widget._editors["A"]["excitation"].currentData() == 6
    assert widget._editors["A"]["range_"].currentData() == 11
    assert widget._write_button.isEnabled()


def test_special_sensor_writes_native_fields_through_engine_and_driver(editor):
    widget, transport = editor
    widget.read_all()
    controls = widget._editors["A"]
    for key, value in (
        ("sensor_type", 0),
        ("sensor_units", 1),
        ("coefficient", 2),
        ("excitation", 11),
        ("range_", 12),
        ("compensation_mode", 1),
        ("curve_number", 23),
    ):
        _select(controls[key], value)
    assert controls["excitation"].isEnabled()
    controls["input_enabled"].setChecked(False)
    controls["filter_enabled"].setChecked(False)
    controls["filter_points"].setValue(20)
    controls["filter_window"].setValue(5)
    transport.write_log.clear()
    _click(widget, "Write All")
    assert transport.write_log[:8] == [
        b"INTYPE A,0,1,2,11,12\r\n",
        b"*ESR?\r\n",
        b"INSET A,0,1\r\n",
        b"*ESR?\r\n",
        b"FILTER A,0,20,5.0\r\n",
        b"*ESR?\r\n",
        b"INCRV A,23\r\n",
        b"*ESR?\r\n",
    ]
    assert all(b" B" not in command for command in transport.write_log)
    assert transport.settings["A"].sensor_type == 0
    assert widget._snapshots["A"].compensation_mode == 1


def test_changing_only_curve_does_not_rewrite_sensor_type_or_other_channels(editor):
    widget, transport = editor
    widget.read_all()
    _select(widget._editors["B"]["curve_number"], 25)
    transport.write_log.clear()
    widget.write_all()
    assert transport.write_log[:2] == [b"INCRV B,25\r\n", b"*ESR?\r\n"]
    assert not any(
        command.startswith(b"INTYPE ") or b" A" in command for command in transport.write_log
    )


def test_rejected_write_requires_read_instead_of_automatically_replaying(editor):
    widget, transport = editor
    widget.read_all()
    _select(widget._editors["A"]["curve_number"], 25)
    transport.write_failure = True
    with pytest.raises(InstrumentError):
        widget.write_all()
    assert not widget._write_button.isEnabled()
    previous_writes = list(transport.write_log)
    with pytest.raises(RuntimeError, match="Read input"):
        widget.write_all()
    assert transport.write_log == previous_writes
    transport.write_failure = False
    assert widget.read_all()
    assert widget._write_button.isEnabled()


def test_failed_read_invalidates_previous_snapshot(editor):
    widget, transport = editor
    widget.read_all()
    transport.read_failure = True
    assert not widget.read_all(show_warning=False)
    assert not widget._write_button.isEnabled()
    assert widget._snapshots == {}


def test_failed_post_write_readback_reports_applied_settings_and_requires_read(editor, monkeypatch):
    widget, transport = editor
    widget.read_all()
    _select(widget._editors["A"]["curve_number"], 25)
    monkeypatch.setattr(widget._engine, "get_input_channel_settings", lambda _channel: None)
    with pytest.raises(RuntimeError, match="was written but could not be read back"):
        widget.write_all()
    assert transport.settings["A"].curve_number == 25
    assert not widget._write_button.isEnabled()


def test_every_native_row_is_visible_without_inner_vertical_scrolling(editor, qtbot):
    widget, _transport = editor
    widget.read_all()
    widget.resize(900, widget.sizeHint().height())
    widget.show()
    qtbot.waitExposed(widget)
    table = widget._table
    assert table.verticalScrollBar().maximum() == 0
    last_row = table.rowCount() - 1
    assert table.rowViewportPosition(last_row) + table.rowHeight(last_row) <= table.viewport().height()


@pytest.mark.parametrize("slot", ["primary", "secondary"])
def test_panel_selects_native_editor_for_its_owning_session_and_switches_back(
    rig, slot, managed_temperature_panel, monkeypatch
):
    panel = managed_temperature_panel()
    transport = InputTransport()
    transport.open()
    session = rig.controller(slot)
    session._driver = Lakeshore340(transport)
    attribute = "_input_settings_widget" if slot == "primary" else "_secondary_input_settings"
    if slot == "primary":
        panel._configure_input_settings_tab(session.connected_driver.get_capabilities())
    else:
        monkeypatch.setattr(panel, "_rebuild_loop_groups", lambda: None)
        monkeypatch.setattr(rig, "loop_catalogue", lambda: ())
        monkeypatch.setattr(panel, "_refresh_stability_channel_selectors", lambda: None)
        panel._sync_secondary_ui()
    widget = getattr(panel, attribute)
    assert isinstance(widget, Lakeshore340InputSettingsTable)
    assert widget._engine is session
    assert panel._tabs.isTabEnabled(panel._input_settings_tab_index)
    assert widget._channels == ("A", "B")
    assert widget._editors["A"]["curve_number"].itemText(22) == "Curve 22 (22)"
    scroll = panel._tabs.widget(panel._input_settings_tab_index)
    assert scroll.widget().layout().indexOf(widget) >= 0
    panel._select_input_settings_editor(
        attribute, session, Lakeshore335(NullTransport()).get_capabilities()
    )
    assert type(getattr(panel, attribute)) is _InputSettingsTableWidget


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
