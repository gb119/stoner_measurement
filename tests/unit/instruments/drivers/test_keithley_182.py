"""Behaviour tests for the legacy IEEE-488 Keithley Model 182 driver."""

from __future__ import annotations

import math

import pytest

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.keithley.k182 import (
    Keithley182,
    Keithley182Protocol,
)
from stoner_measurement.instruments.nanovoltmeter import NanovoltmeterTriggerSource
from stoner_measurement.instruments.transport import GpibTransport, NullTransport

_NO_ERRORS = b"ERR000000000000000000000\r\n"
_MACHINE_STATUS = b"182B1F0G1I0J0K0M000N1O0P2R5S0T06V0Y0Z0\r\n"


def _open_driver(*responses: bytes) -> tuple[Keithley182, NullTransport]:
    transport = NullTransport(responses=list(responses))
    transport.open()
    return Keithley182(transport), transport


def _error_status(bit: int) -> bytes:
    bits = ["0"] * 21
    bits[bit] = "1"
    return f"ERR{''.join(bits)}\r\n".encode()


def test_protocol_uses_exact_eoi_terminated_command_grammar():
    protocol = Keithley182Protocol()

    assert protocol.format_command("R0B1S0X") == b"R0B1S0X"
    assert protocol.format_query("U0X") == b"U0X"
    assert protocol.parse_response(b"NDCV+1.0E-6\r\n") == "NDCV+1.0E-6"
    assert b"\n" not in protocol.format_command("F0G0T1X")


def test_protocol_applies_legacy_gpib_status_semantics():
    transport = GpibTransport(address=7)
    transport.set_protocol(Keithley182Protocol())

    assert transport._use_mav is False
    assert transport._status_error_mask is None
    assert transport._read_termination is None


def test_connect_verifies_u0_without_scpi_or_device_clear():
    transport = NullTransport(responses=[_MACHINE_STATUS, _NO_ERRORS])
    driver = Keithley182(transport)

    driver.connect()

    assert driver.confirm_identity() == "182"
    assert transport.write_log == [b"U0X", b"U1X"]
    assert all(b"*" not in command and b"\n" not in command for command in transport.write_log)


def test_single_measurement_uses_one_shot_on_talk():
    driver, transport = _open_driver(b"+1.820000E-06\r\n", _NO_ERRORS)

    assert driver.measure_voltage() == pytest.approx(1.82e-6)
    assert transport.write_log == [b"F0G0T1X", b"U1X"]


@pytest.mark.parametrize(
    ("response", "value", "prefix", "location", "timestamp"),
    [
        ("+1.2E-6", 1.2e-6, None, None, None),
        ("NDCV+1.820000E+00", 1.82, "NDCV", None, None),
        ("RDCV-2.5E-3, 0012, 000123.50", -2.5e-3, "RDCV", 12, 123.5),
        ("NMAX+4.0E-2,1,0.25", 0.04, "NMAX", 1, 0.25),
        ("NMIN-4.0E-2", -0.04, "NMIN", None, None),
    ],
)
def test_parse_reading_formats(response, value, prefix, location, timestamp):
    reading = Keithley182.parse_reading(response)

    assert reading.value == pytest.approx(value)
    assert reading.prefix == prefix
    assert reading.location == location
    assert reading.timestamp == timestamp


@pytest.mark.parametrize(
    ("value", "command"),
    [
        (0.003, b"R1X"),
        (0.03, b"R2X"),
        (0.3, b"R3X"),
        (3.0, b"R4X"),
        (30.0, b"R5X"),
    ],
)
def test_fixed_ranges_emit_exact_legacy_commands(value, command):
    driver, transport = _open_driver(_NO_ERRORS)

    driver.set_range(value)

    assert transport.write_log == [command, b"U1X"]


def test_invalid_and_nonfinite_values_fail_before_writing():
    driver, transport = _open_driver()

    for operation in (
        lambda: driver.set_range(0.1),
        lambda: driver.set_nplc(10.0),
        lambda: driver.set_digits(8),
        lambda: driver.set_trigger_delay(math.inf),
        lambda: driver.set_relative_value(math.nan),
        lambda: driver.set_buffer_size(1025),
    ):
        with pytest.raises(ValueError):
            operation()

    assert transport.write_log == []


@pytest.mark.parametrize(
    ("bit", "message"),
    [
        (0, "invalid command"),
        (4, "trigger overrun"),
        (5, "measurement overflow"),
        (16, "trigger not ready"),
    ],
)
def test_u1_error_bits_raise_distinct_instrument_errors(bit, message):
    driver, _ = _open_driver(_error_status(bit))

    with pytest.raises(InstrumentError, match=message):
        driver._check_errors(command="test")


def test_buffer_configuration_and_block_read():
    driver, transport = _open_driver(
        _NO_ERRORS,
        b"+1.0E-6,+2.0E-6,-3.0E-6\r\n",
        _NO_ERRORS,
    )

    driver.set_buffer_size(3)
    readings = driver.read_buffer(count=3)

    assert readings == pytest.approx((1e-6, 2e-6, -3e-6))
    assert transport.write_log == [b"I1,3X", b"U1X", b"F2G0X", b"U1X"]


def test_external_buffered_triggering_selects_multiple_mode():
    driver, transport = _open_driver(_NO_ERRORS, _NO_ERRORS, _NO_ERRORS)

    driver.set_trigger_source(NanovoltmeterTriggerSource.EXT)
    driver.set_trigger_count(10)
    driver.initiate()

    assert transport.write_log == [b"T7X", b"U1X", b"T6X", b"U1X", b"T6X", b"U1X"]


def test_reset_is_explicitly_refused():
    driver, transport = _open_driver()

    with pytest.raises(NotImplementedError, match="device clear"):
        driver.reset()

    assert transport.write_log == []


def test_capabilities_describe_all_plugin_configuration_variations():
    capabilities = Keithley182.CAPABILITIES

    assert Keithley182(NullTransport()).get_capabilities() is capabilities
    assert capabilities.fixed_voltage_ranges == (0.003, 0.03, 0.3, 3.0, 30.0)
    assert capabilities.nplc_values == (0.15, 1.0, 5.0)
    assert capabilities.digit_values == (3, 4, 5, 6)
    assert capabilities.filter_types == ("OFF", "FAST", "MEDIUM", "SLOW")
    assert capabilities.supports_filter_count is False
    assert capabilities.supports_line_sync is False
    assert capabilities.supports_autozero is False
    assert capabilities.supports_safe_reset is False
    assert capabilities.relative_limits == (-30.0, 30.0)
    assert capabilities.max_buffer_points == 1024


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
