"""Native Mercury iTC device discovery, acknowledgements and control contracts."""

import pytest

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.oxford import OxfordMercuryTemperatureController
from stoner_measurement.instruments.protocol.mercury import MercuryProtocol
from stoner_measurement.instruments.temperature_controller import ControlMode, PIDParameters
from stoner_measurement.instruments.transport import NullTransport

TEMP = "DEV:MB1.T1:TEMP"
LOOP = "DEV:MB1.T1:TEMP:LOOP"
HEATER = "DEV:MB0.H1:HTR"


class MercuryTransport(NullTransport):
    """Stateful native-only Mercury replies, including unsolicited SET acknowledgements."""

    def __init__(self):
        super().__init__()
        self.identity = "IDN:OXFORD INSTRUMENTS:MERCURY iTC:SN123:2.6.0"
        self.catalogue = "STAT:SYS:CAT:DEV:MB1.T1:TEMP:DEV:MB0.H1:HTR:DEV:DB4.G1:AUX"
        self.values = {
            LOOP + ":HTR": "MB0.H1", LOOP + ":AUX": "DB4.G1", LOOP + ":TSET": "20K",
            LOOP + ":ENAB": "ON", LOOP + ":PIDT": "OFF", LOOP + ":P": "30",
            LOOP + ":I": "4", LOOP + ":D": "0.5", LOOP + ":RSET": "2K/m",
            LOOP + ":RENA": "OFF", LOOP + ":FAUT": "ON", LOOP + ":HSET": "25%",
            TEMP + ":SIG:TEMP": "4.2K", HEATER + ":SIG:POWR": "20W", HEATER + ":PMAX": "80W",
            "DEV:DB4.G1:AUX:SIG:OPEN": "12%",
        }
        self.reject = None

    def write(self, data, slow=None):
        super().write(data, slow=slow)
        command = data.decode().strip()
        if self.reject and command.startswith(self.reject):
            reply = command + ":DENIED"
        elif command == "*IDN?":
            reply = self.identity
        elif command == "READ:SYS:CAT":
            reply = self.catalogue
        elif command.startswith("READ:"):
            path = command[5:]
            reply = f"STAT:{path}:{self.values.get(path, 'INVALID')}"
        elif command.startswith("SET:"):
            path, value = command[4:].rsplit(":", 1)
            self.values[path] = value
            reply = f"STAT:SET:{path}:VALID"
        else:
            raise AssertionError(f"Unsupported non-native command {command!r}.")
        self.queue_response((reply + "\n").encode())
        return len(data)


@pytest.fixture
def mercury():
    transport = MercuryTransport()
    driver = OxfordMercuryTemperatureController(transport)
    driver.connect()
    transport.write_log.clear()
    yield driver, transport
    driver.disconnect()


def test_discovery_reads_existing_associations_without_changing_hardware(mercury):
    driver, transport = mercury
    caps = driver.get_capabilities()
    assert caps.input_channels == ("A",)
    assert caps.loop_numbers == (1,)
    assert caps.has_ramp and caps.has_cryogen_control and caps.has_manual_heater_output
    assert not caps.has_heater_range
    assert driver.get_loop_input_channels(1) == ("A",)
    driver.set_input_channel(1, "A")
    assert transport.write_log == []
    with pytest.raises(ValueError):
        driver.set_input_channel(1, "B")


def test_core_reads_use_native_paths_and_units(mercury):
    driver, transport = mercury
    assert driver.get_temperature("A") == 4.2
    assert driver.get_setpoint(1) == 20
    assert driver.get_pid(1) == PIDParameters(30, 4, 0.5)
    assert driver.get_heater_output(1) == 25
    assert driver.get_ramp_rate(1) == 2
    assert driver.get_gas_flow() == 12
    assert transport.write_log[:5] == [
        b"READ:DEV:MB1.T1:TEMP:SIG:TEMP\n", b"READ:DEV:MB1.T1:TEMP:LOOP:TSET\n",
        b"READ:DEV:MB1.T1:TEMP:LOOP:P\n", b"READ:DEV:MB1.T1:TEMP:LOOP:I\n",
        b"READ:DEV:MB1.T1:TEMP:LOOP:D\n",
    ]
    assert all(b"SYST:ERR" not in command for command in transport.write_log)


@pytest.mark.parametrize("value,expected", [("4.2K", 4.2), ("4200mK", 4.2), ("4.2:K:VALID", 4.2)])
def test_readback_units_and_valid_suffix(mercury, value, expected):
    driver, transport = mercury
    transport.values[TEMP + ":SIG:TEMP"] = value
    assert driver.get_temperature("A") == pytest.approx(expected)


@pytest.mark.parametrize("value", ["nanK", "INVALID", "4.2W", "", "4.2:INVALID"])
def test_invalid_temperature_is_not_a_numeric_reading(mercury, value):
    driver, transport = mercury
    transport.values[TEMP + ":SIG:TEMP"] = value
    with pytest.raises((ValueError, InstrumentError)):
        driver.get_temperature("A")


def test_set_commands_consume_acknowledgements_before_reads(mercury):
    driver, transport = mercury
    driver.set_setpoint(1, 30)
    assert driver.get_setpoint(1) == 30
    driver.set_ramp_rate(1, 5)
    driver.set_ramp_enabled(1, True)
    assert driver.get_ramp_enabled(1)
    assert transport.write_log == [
        b"SET:DEV:MB1.T1:TEMP:LOOP:TSET:30\n", b"READ:DEV:MB1.T1:TEMP:LOOP:TSET\n",
        b"SET:DEV:MB1.T1:TEMP:LOOP:RSET:5\n", b"SET:DEV:MB1.T1:TEMP:LOOP:RENA:ON\n",
        b"READ:DEV:MB1.T1:TEMP:LOOP:RENA\n",
    ]


@pytest.mark.parametrize("mode,enabled,table", [
    (ControlMode.CLOSED_LOOP, "ON", "OFF"), (ControlMode.ZONE, "ON", "ON"),
    (ControlMode.OPEN_LOOP, "OFF", "OFF"), (ControlMode.OFF, "OFF", "OFF"),
])
def test_heater_modes_do_not_change_gas(mercury, mode, enabled, table):
    driver, transport = mercury
    driver.set_loop_mode(1, mode)
    assert transport.values[LOOP + ":ENAB"] == enabled
    assert transport.values[LOOP + ":PIDT"] == table
    assert transport.values[LOOP + ":FAUT"] == "ON"
    assert not any(b"FAUT" in data for data in transport.write_log)
    if mode is ControlMode.OFF:
        assert transport.write_log[-1] == b"SET:DEV:MB1.T1:TEMP:LOOP:HSET:0.0\n"
    expected = ControlMode.OPEN_LOOP if enabled == "OFF" else mode
    assert driver.get_loop_mode(1) is expected


def test_gas_controls_do_not_change_heater(mercury):
    driver, transport = mercury
    assert driver.get_gas_auto()
    driver.set_gas_auto(False)
    driver.set_gas_flow(35)
    assert transport.values[LOOP + ":ENAB"] == "ON"
    assert transport.write_log == [
        b"READ:DEV:MB1.T1:TEMP:LOOP:FAUT\n", b"SET:DEV:MB1.T1:TEMP:LOOP:FAUT:OFF\n",
        b"SET:DEV:MB1.T1:TEMP:LOOP:FSET:35\n",
    ]


def test_rejected_set_stops_pid_transaction_without_retries(mercury):
    driver, transport = mercury
    transport.reject = "SET:" + LOOP + ":P:"
    with pytest.raises(InstrumentError):
        driver.set_pid(1, 10, 20, 30)
    assert transport.write_log == [
        b"SET:DEV:MB1.T1:TEMP:LOOP:PIDT:OFF\n", b"SET:DEV:MB1.T1:TEMP:LOOP:P:10\n",
    ]


@pytest.mark.parametrize("reply", [
    b"STAT:SET:DEV:WRONG:TEMP:LOOP:TSET:VALID\n", b"\n", b"SET:INVALID\n",
])
def test_set_rejects_mismatched_or_missing_acknowledgement(mercury, reply):
    driver, transport = mercury
    transport.queue_response(reply)
    with pytest.raises(InstrumentError):
        driver.set_setpoint(1, 20)
    assert len(transport.write_log) == 1


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_invalid_requests_write_nothing(mercury, value):
    driver, transport = mercury
    for method in (driver.set_setpoint, driver.set_manual_heater_output, driver.set_ramp_rate):
        with pytest.raises(ValueError):
            method(1, value)
    assert transport.write_log == []


def test_old_firmware_does_not_advertise_ramp_and_uses_legacy_gas_tokens():
    transport = MercuryTransport()
    transport.identity = "IDN:OXFORD INSTRUMENTS:MERCURY iTC:SN123:1.0.11"
    driver = OxfordMercuryTemperatureController(transport)
    driver.connect()
    assert not driver.get_capabilities().has_ramp
    with pytest.raises(NotImplementedError):
        driver.set_ramp_rate(1, 5)
    driver.set_gas_auto(True)
    assert transport.write_log[-1] == b"SET:DEV:MB1.T1:TEMP:LOOP:FAUT:Auto\n"
    driver.disconnect()


def test_failed_discovery_closes_owned_transport_and_reconnect_discards_catalogue():
    transport = MercuryTransport()
    driver = OxfordMercuryTemperatureController(transport)
    driver.connect()
    driver.disconnect()
    assert driver.get_capabilities().input_channels == ()
    transport.catalogue = "STAT:SYS:CAT:broken"
    with pytest.raises(ValueError):
        driver.connect()
    assert not transport.is_open
    assert driver.get_capabilities().loop_numbers == ()


def test_catalogue_without_heater_or_auxiliary_does_not_invent_controls():
    transport = MercuryTransport()
    transport.catalogue = "STAT:DEV:MB1.T1:TEMP"
    transport.values[LOOP + ":HTR"] = "0"
    transport.values[LOOP + ":AUX"] = "0"
    driver = OxfordMercuryTemperatureController(transport)
    driver.connect()
    assert driver.get_capabilities().loop_numbers == ()
    assert not driver.get_capabilities().has_cryogen_control
    with pytest.raises(NotImplementedError):
        driver.set_gas_flow(10)
    driver.disconnect()


def test_engine_selects_native_protocol(qapp):
    from stoner_measurement.temperature_control.engine import TemperatureControllerEngine

    service = TemperatureControllerEngine()
    try:
        assert isinstance(service._build_protocol("OxfordMercuryTemperatureController"), MercuryProtocol)
    finally:
        service.shutdown()


def test_primary_apply_configures_native_ramp_before_target(
    mercury, monkeypatch, managed_qt_widget, wait_temperature_tasks
):
    from qtpy.QtWidgets import QPushButton

    from stoner_measurement.temperature_control import engine as engine_module
    from stoner_measurement.ui.temperature_panel import _LoopControlGroup

    monkeypatch.setattr(engine_module, "load_temperature_controller_config", lambda: {})
    driver, transport = mercury
    service = engine_module.TemperatureControllerEngine()
    service.set_polling_rate(0)
    service._driver = driver
    try:
        group = managed_qt_widget(_LoopControlGroup(1, service, driver.get_capabilities()))
        from stoner_measurement.temperature_control.types import LoopSettings

        monkeypatch.setattr(service, "get_loop_settings", lambda loop: LoopSettings(
            4.2, ControlMode.CLOSED_LOOP, "MB1.T1", False, 0, 1, 1, 1,
        ))
        assert group.read_from_hardware()
        group._mode_combo.setCurrentIndex(group._mode_combo.findData(ControlMode.CLOSED_LOOP))
        group._sp_spin.setValue(30)
        group._ramp_rate_spin.setValue(5)
        group._ramp_enable.setChecked(True)
        group._pid_p_spin.setValue(20)
        group._pid_i_spin.setValue(3)
        group._pid_d_spin.setValue(1)
        assert group._heater_range_spin.isHidden()
        assert group._channel_combo.count() == 1
        next(button for button in group.findChildren(QPushButton) if button.text() == "Apply").click()
        wait_temperature_tasks(service)
        assert transport.write_log == [
            b"SET:DEV:MB1.T1:TEMP:LOOP:RSET:5.0\n", b"SET:DEV:MB1.T1:TEMP:LOOP:RENA:ON\n",
            b"SET:DEV:MB1.T1:TEMP:LOOP:PIDT:OFF\n", b"SET:DEV:MB1.T1:TEMP:LOOP:P:20.0\n",
            b"SET:DEV:MB1.T1:TEMP:LOOP:I:3.0\n", b"SET:DEV:MB1.T1:TEMP:LOOP:D:1.0\n",
            b"SET:DEV:MB1.T1:TEMP:LOOP:TSET:30.0\n", b"SET:DEV:MB1.T1:TEMP:LOOP:PIDT:OFF\n",
            b"SET:DEV:MB1.T1:TEMP:LOOP:ENAB:ON\n",
        ]
    finally:
        service.shutdown()


def test_two_heaters_follow_existing_associations_and_multiple_gas_loops_are_not_guessed():
    transport = MercuryTransport()
    transport.catalogue += ":DEV:DB2.T1:TEMP:DEV:DB3.H1:HTR:DEV:DB5.G1:AUX"
    second = "DEV:DB2.T1:TEMP:LOOP"
    transport.values[second + ":HTR"] = "DB3.H1"
    transport.values[second + ":AUX"] = "DB5.G1"
    driver = OxfordMercuryTemperatureController(transport)
    driver.connect()
    # Sorted UID aliases are stable and independent of catalogue listing order.
    assert driver.get_input_channel(1) == "A"
    assert driver.get_input_channel(2) == "B"
    assert driver._heaters == {1: "DB3.H1", 2: "MB0.H1"}
    assert not driver.get_capabilities().has_cryogen_control
    assert not any(data.startswith(b"SET:") for data in transport.write_log)
    driver.disconnect()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
