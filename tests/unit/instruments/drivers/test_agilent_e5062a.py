"""Focused tests for the Agilent E5062A ENA driver."""

from __future__ import annotations

import numpy as np
import pytest

from stoner_measurement.instruments import (
    AgilentE5062A,
    ByteOrder,
    DataEncoding,
    NetworkAnalyserTriggerSource,
    SweepConfiguration,
    SweepType,
)
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.transport import NullTransport


def _driver(responses=()):
    transport = NullTransport(responses=list(responses))
    transport.open()
    return AgilentE5062A(transport, auto_check_errors=False)


def _capability_responses(model="E5062A"):
    return [
        f"Agilent Technologies,{model},MY123,A.03.00\n".encode(),
        b"016,100\n",
        b"2\n",
        b"4\n",
        b"4\n",
    ]


def test_identity_and_runtime_capabilities():
    driver = _driver(_capability_responses())

    capabilities = driver.get_capabilities()

    assert capabilities.port_count == 2
    assert capabilities.max_channels == 4
    assert capabilities.max_traces_per_channel == 4
    assert capabilities.installed_options == ("016", "100")
    assert capabilities.firmware == "A.03.00"
    assert driver.transport.write_log == [
        b"*IDN?\n",
        b"*OPT?\n",
        b":SERV:PORT:COUN?\n",
        b":SERV:CHAN:COUN?\n",
        b":SERV:CHAN:TRAC:COUN?\n",
    ]


def test_identity_rejects_nearby_model():
    driver = _driver([_capability_responses("E5061A")[0]])

    with pytest.raises(InstrumentError, match="E5061A"):
        driver.confirm_identity()


def test_sweep_configuration_round_trip_commands():
    driver = _driver([b"LIN\n", b"1e6\n", b"2e6\n", b"101\n", b"1e3\n", b"-10\n", b"1\n", b"8\n"])

    configuration = driver.get_sweep_configuration(2)

    assert configuration == SweepConfiguration(
        sweep_type=SweepType.LINEAR,
        start_hz=1e6,
        stop_hz=2e6,
        points=101,
        if_bandwidth_hz=1e3,
        source_power_dbm=-10,
        averaging_count=8,
    )
    driver.set_sweep_configuration(configuration, 2)
    assert b":SENS2:SWE:TYPE LIN\n" in driver.transport.write_log
    assert b":SENS2:SWE:POIN 101\n" in driver.transport.write_log
    assert b":SOUR2:POW -10.0\n" in driver.transport.write_log


def test_trace_trigger_and_correction_commands():
    driver = _driver(_capability_responses() + [b"S21\n", b"BUS\n", b"1\n"])
    driver.get_capabilities()

    driver.set_measurement_parameter("s21", channel=2, trace=3)
    assert driver.get_measurement_parameter(2, 3) == "S21"
    driver.set_trigger_source(NetworkAnalyserTriggerSource.BUS)
    assert driver.get_trigger_source() is NetworkAnalyserTriggerSource.BUS
    driver.set_correction_enabled(True, 2)
    assert driver.get_correction_enabled(2)
    assert driver.transport.write_log[-6:] == [
        b":CALC2:PAR3:DEF S21\n",
        b":CALC2:PAR3:DEF?\n",
        b":TRIG:SOUR BUS\n",
        b":TRIG:SOUR?\n",
        b":SENS2:CORR 1\n",
        b":SENS2:CORR?\n",
    ]


def test_cw_frequency_and_power_sweep_range_commands():
    driver = _driver([b"1e9\n", b"-20\n", b"0\n"])

    assert driver.get_cw_frequency(2) == pytest.approx(1e9)
    assert driver.get_power_sweep_range(2) == pytest.approx((-20.0, 0.0))
    driver.set_sweep_configuration(
        SweepConfiguration(SweepType.POWER, 2e9, 2e9, 11), 2
    )
    driver.set_cw_frequency(2e9, 2)
    driver.set_power_sweep_range(-30.0, -5.0, 2)

    assert b":SENS2:FREQ:STAR 2000000000.0\n" not in driver.transport.write_log
    assert b":SENS2:FREQ:STOP 2000000000.0\n" not in driver.transport.write_log
    assert driver.transport.write_log[-2:] == [
        b":SOUR2:POW:STAR -30.0\n",
        b":SOUR2:POW:STOP -5.0\n",
    ]


def test_cw_sweep_configuration_uses_cw_frequency_not_equal_limits():
    driver = _driver()

    driver.set_sweep_configuration(
        SweepConfiguration(SweepType.CW, 2e9, 2e9, 2, if_bandwidth_hz=1e3), 2
    )

    assert b":SENS2:FREQ:CW 2000000000.0\n" in driver.transport.write_log
    assert not any(b":FREQ:STAR" in command for command in driver.transport.write_log)
    assert not any(b":FREQ:STOP" in command for command in driver.transport.write_log)


def test_ascii_acquisition_returns_matching_complex_trace():
    driver = _driver([b"1\n", b"ASC\n", b"1,2,3\n", b"ASC\n", b"1,2,3,4,5,6\n", b"S21\n"])

    sweep = driver.acquire(channel=1, traces=(1,), timeout=5.0)

    trace = sweep.traces[0]
    np.testing.assert_allclose(trace.stimulus, [1, 2, 3])
    np.testing.assert_allclose(trace.values, [1 + 2j, 3 + 4j, 5 + 6j])
    assert trace.parameter == "S21"
    assert driver.transport.timeout == 2.0


@pytest.mark.parametrize(
    ("encoding", "order", "dtype", "format_response", "border_response"),
    [
        (DataEncoding.REAL32, ByteOrder.NORMAL, ">f4", b"REAL32\n", b"NORM\n"),
        (DataEncoding.REAL64, ByteOrder.SWAPPED, "<f8", b"REAL\n", b"SWAP\n"),
    ],
)
def test_binary_complex_transfer(encoding, order, dtype, format_response, border_response):
    values = np.array([1, 2, 3, 4], dtype=dtype).tobytes()
    block = b"#2" + f"{len(values):02d}".encode() + values + b"\n"
    driver = _driver([format_response, border_response, block])

    result = driver.read_complex()

    np.testing.assert_allclose(result, [1 + 2j, 3 + 4j])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
