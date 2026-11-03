"""Native Pulse Delta command contracts from the 6221 reference manual."""

import pytest

from stoner_measurement.instruments.keithley.k6221 import Keithley6221
from stoner_measurement.instruments.transport import NullTransport


def driver(responses=()):
    transport = NullTransport(responses=list(responses))
    transport.open()
    return Keithley6221(transport), transport


def test_custom_pulse_sweep_uses_native_commands(monkeypatch):
    monkeypatch.setattr("stoner_measurement.instruments.keithley.k6221.sleep", lambda _: None)
    source, transport = driver()
    source.configure_pulse_delta_sweep(
        (0.001, -0.002, 0.004),
        width=0.0005,
        source_delay=0.00002,
        period=0.1,
        low_measurements=2,
    )
    assert transport.write_log == [
        b":SOUR:SWE:SPAC LIST\n",
        b":SOUR:LIST:CURR 0.001,-0.002,0.004\n",
        b":SOUR:SWE:POIN 3\n",
        b":SOUR:LIST:DEL 0.1,0.1,0.1\n",
        b":SOUR:SWE:COUN 1\n",
        b":SOUR:PDEL:LOW 0\n",
        b":SOUR:PDEL:WIDT 0.0005\n",
        b":SOUR:PDEL:SDEL 2e-05\n",
        b":SOUR:PDEL:LME 2\n",
        b":SOUR:PDEL:SWE ON\n",
        b":UNIT V\n",
        b":SENS:AVER:STAT OFF\n",
    ]


@pytest.mark.parametrize(
    "override",
    [
        {"values": ()},
        {"values": (float("nan"),)},
        {"values": (0.106,)},
        {"width": 49e-6},
        {"width": 0.013},
        {"width": float("nan")},
        {"source_delay": 15e-6},
        {"source_delay": 0.0005},
        {"period": 0.0005},
        {"period": float("inf")},
        {"low_measurements": 3},
        {"low_measurements": True},
    ],
)
def test_invalid_pulse_settings_do_not_write(override):
    source, transport = driver()
    settings = dict(
        values=(0.001,), width=0.0005, source_delay=16e-6, period=0.1, low_measurements=2
    )
    settings.update(override)
    with pytest.raises(ValueError):
        source.configure_pulse_delta_sweep(**settings)
    assert not transport.write_log


def test_minimum_pulse_width_and_settling_are_valid():
    Keithley6221.validate_pulse_delta_sweep(
        (0.0,),
        width=50e-6,
        source_delay=16e-6,
        period=0.1,
        low_measurements=1,
    )


def test_buffer_reinitialises_persistent_state_and_reads_only_corrected_volts():
    source, transport = driver([b"2\n", b"0.01,-0.02\n"])
    source.prepare_pulse_delta_buffer(2)
    assert source.pulse_delta_buffer_count() == 2
    assert source.read_pulse_delta_buffer(2) == (0.01, -0.02)
    assert transport.write_log == [
        b":TRAC:FEED:CONT NEV\n",
        b":TRAC:CLE\n",
        b":TRAC:POIN 2\n",
        b":FORM:DATA ASC\n",
        b":FORM:ELEM READ\n",
        b":TRAC:FEED SENS1\n",
        b":TRAC:FEED:CONT NEXT\n",
        b":TRAC:POIN:ACT?\n",
        b":TRAC:DATA?\n",
    ]


@pytest.mark.parametrize("count", [0, 65537, 2.5, True])
def test_invalid_buffer_sizes_are_rejected_without_writes(count):
    source, transport = driver()
    with pytest.raises(ValueError, match="buffer size"):
        source.prepare_pulse_delta_buffer(count)
    assert transport.write_log == []


@pytest.mark.parametrize("response", [b"0.1\n", b"0.1,bad\n", b"\n"])
def test_incomplete_or_malformed_readings_are_rejected(response):
    source, _ = driver([response])
    with pytest.raises(ValueError):
        source.read_pulse_delta_buffer(2)


@pytest.mark.parametrize("response", [b"1\n", b"0\n"])
def test_arm_confirms_native_mode_and_restores_transport_timeout(response):
    source, transport = driver([response])
    timeout = transport.timeout
    if response == b"1\n":
        source.pulse_delta_arm()
    else:
        with pytest.raises(RuntimeError, match="did not arm"):
            source.pulse_delta_arm()
    assert transport.timeout == timeout
    assert transport.write_log == [b":SOUR:PDEL:ARM\n", b":SOUR:PDEL:ARM?\n"]


def test_range_and_presence_use_source_serial_connection():
    source, transport = driver([b"1\n"])
    assert source.pulse_delta_present()
    source.set_pulse_delta_voltage_range(0.1)
    commands = b"".join(transport.write_log)
    assert b":SOUR:PDEL:NVPR?\n" in commands
    assert b"SYST:COMM:SER:SEND" in commands
    assert b":SENS:VOLT:CHAN1:RANG 0.1" in commands


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
