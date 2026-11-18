"""Model-specific buffered acquisition for Keithley electrometers."""

import struct
from unittest.mock import MagicMock

import pytest

from stoner_measurement.instruments.electrometer import ElectrometerDataFormat, ElectrometerFunction
from stoner_measurement.instruments.keithley import Keithley6485, Keithley6514, Keithley6517
from stoner_measurement.instruments.transport import NullTransport


def _driver(cls=Keithley6485, responses=()):
    transport = NullTransport(responses=list(responses))
    transport.open()
    driver = cls(transport)
    driver.auto_check_errors = False
    return driver, transport


@pytest.mark.parametrize("cls", [Keithley6485, Keithley6514, Keithley6517])
def test_buffer_setup_and_repeated_arming(cls):
    driver, transport = _driver(cls)
    driver.prepare_buffer(2)
    assert transport.write_log[:6] == [
        b":INIT:CONT OFF\n", b":ABOR\n", b":TRAC:FEED:CONT NEV\n",
        b":TRAC:CLE\n", b":TRAC:POIN 2\n", b":FORM:ELEM READ\n",
    ]
    assert transport.write_log[-1] == b":TRAC:FEED SENS\n"
    if cls is not Keithley6514:
        assert b":FORM:BORD NORM\n" in transport.write_log
    driver.start_buffer()
    assert transport.write_log[-5:] == [
        b":ABOR\n", b":TRAC:FEED:CONT NEV\n", b":TRAC:CLE\n",
        b":TRAC:FEED:CONT NEXT\n", b":INIT\n",
    ]


def test_current_only_picoammeter_does_not_send_function_selection():
    driver, transport = _driver()
    driver.configure_input(ElectrometerFunction.CURR, autorange=False, input_range=2e-9,
                           nplc=1.0, filter_enabled=True, filter_count=4)
    assert transport.write_log == [
        b":SENS:CURR:RANG:AUTO 0\n", b":SENS:CURR:RANG 2e-09\n",
        b":SENS:CURR:NPLC 1.0\n", b":SENS:CURR:AVER:STAT 1\n",
        b":SENS:CURR:AVER:COUN 4\n", b":SYST:ZCH 0\n",
    ]


def test_voltage_settings_address_voltage_not_current():
    driver, transport = _driver(Keithley6514)
    driver.configure_input(ElectrometerFunction.VOLT, autorange=True, input_range=2,
                           nplc=1, filter_enabled=False, filter_count=10)
    assert transport.write_log == [
        b":SENS:FUNC 'VOLT'\n", b":SENS:VOLT:RANG:AUTO 1\n",
        b":SENS:VOLT:NPLC 1\n", b":SENS:VOLT:AVER:STAT 0\n",
        b":SENS:VOLT:AVER:COUN 10\n", b":SYST:ZCH 0\n",
    ]


@pytest.mark.parametrize("cls,data_format,code", [
    (Keithley6485, ElectrometerDataFormat.SREAL, "f"),
    (Keithley6514, ElectrometerDataFormat.SREAL, "f"),
    (Keithley6517, ElectrometerDataFormat.DREAL, "d"),
])
def test_binary_buffer_read(cls, data_format, code):
    # Normal byte order and indefinite block framing from the FORMat manuals.
    payload = b"#0" + struct.pack(f">2{code}", 1.25, -2.5) + b"\n"
    driver, transport = _driver(cls, [payload])
    driver.set_data_format(data_format)
    assert driver.read_buffer() == pytest.approx((1.25, -2.5))
    assert transport.write_log[-1] == b":TRAC:DATA?\n"


def test_ascii_count_is_limited_in_software():
    driver, transport = _driver(responses=[b"1e-9,2e-9,3e-9\n"])
    assert driver.read_buffer(count=2) == (1e-9, 2e-9)
    assert transport.write_log == [b":TRAC:DATA?\n"]


def test_unsupported_precision_rejected_before_write():
    driver, transport = _driver(Keithley6514)
    with pytest.raises(ValueError, match="does not support"):
        driver.set_data_format(ElectrometerDataFormat.DREAL)
    assert not transport.write_log


def test_initiate_defers_error_query_until_acquisition_completes():
    driver, transport = _driver()
    driver.auto_check_errors = True
    driver.check_for_errors = MagicMock(side_effect=AssertionError("would block on external trigger"))
    driver.initiate()
    assert driver.auto_check_errors
    assert transport.write_log == [b":INIT\n"]


def test_trigger_link_routes_completion_and_disables_first_event_bypass():
    driver, transport = _driver(Keithley6514, [b"2\n"])
    driver.configure_trigger_link(input_line=1, output_line=3)
    assert transport.write_log == [
        b":TRIG:CLE\n", b":ARM:TCON:OUTP NONE\n", b":TRIG:TCON:DIR ACC\n",
        b":TRIG:TCON:OLIN?\n", b":TRIG:TCON:ILIN 1\n",
        b":TRIG:TCON:OLIN 3\n", b":TRIG:TCON:ILIN 1\n", b":TRIG:TCON:OUTP SENS\n",
    ]


def test_final_completion_wait_restores_transport_timeout():
    driver, transport = _driver(responses=[b"1\n"])
    previous = transport.timeout
    driver.wait_for_buffer_complete(50)
    assert transport.timeout == previous
    assert transport.write_log == [b"*OPC?\n"]


def test_6517_uses_its_automatic_measurement_complete_output():
    driver, transport = _driver(Keithley6517, [b"1\n"])
    driver.configure_trigger_link(input_line=2, output_line=3)
    assert b":TRIG:TCON:PROT ASYN\n" in transport.write_log
    assert b":ARM:TCON:DIR ACC\n" in transport.write_log
    assert b":TRIG:TCON:DIR ACC\n" in transport.write_log
    assert not any(b":OUTP " in command or command == b":TRIG:CLE\n" for command in transport.write_log)


def test_binary_buffer_rejects_partial_values():
    driver, _ = _driver(responses=[b"#0\x00\x00\n"])
    driver.set_data_format(ElectrometerDataFormat.SREAL)
    with pytest.raises(ValueError):
        driver.read_buffer()


@pytest.mark.parametrize("cls", [Keithley6485, Keithley6514, Keithley6517])
def test_single_read_setup_disables_buffer_and_external_triggering(cls):
    driver, transport = _driver(cls)
    driver.prepare_single_reading(trigger_delay=0.05)
    assert transport.write_log == [
        b":INIT:CONT OFF\n", b":ABOR\n", b":TRAC:FEED:CONT NEV\n",
        b":FORM:ELEM READ\n", b":FORM:DATA ASC\n", b":TRIG:SOUR IMM\n",
        b":TRIG:COUN 1\n", b":TRIG:DEL 0.05\n", b":ARM:SOUR IMM\n", b":ARM:COUN 1\n",
    ]


def test_single_read_queries_a_fresh_value_every_time():
    driver, transport = _driver(responses=[b"+1.25e-9\n", b"+2.5e-9\n"])
    assert driver.read_measurement() == 1.25e-9
    assert driver.read_measurement() == 2.5e-9
    assert transport.write_log == [b":READ?\n", b":READ?\n"]


@pytest.mark.parametrize("response", [b"\n", b"1,2\n", b"not a reading\n"])
def test_single_read_rejects_empty_multiple_or_malformed_results(response):
    driver, _ = _driver(responses=[response])
    with pytest.raises(ValueError):
        driver.read_measurement()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
