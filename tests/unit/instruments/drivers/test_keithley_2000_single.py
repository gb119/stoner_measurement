"""Single-reading setup and setting readbacks without scanner commands."""

import pytest

from stoner_measurement.instruments.dmm import DmmFunction
from stoner_measurement.instruments.keithley import Keithley2000, Keithley2700
from stoner_measurement.instruments.transport import NullTransport


def _meter(cls=Keithley2000, responses=()):
    transport = NullTransport(responses=list(responses))
    transport.open()
    meter = cls(transport)
    meter.auto_check_errors = False
    return meter, transport


@pytest.mark.parametrize("model", [Keithley2000, Keithley2700])
@pytest.mark.parametrize("function", list(DmmFunction))
def test_setup_one_reading_without_reset_route_or_channel_commands(model, function):
    meter, transport = _meter(model)
    meter.configure_single_reading(function)
    log = transport.write_log
    assert b":SAMP:COUN 1\n" in log and b":TRIG:COUN 1\n" in log
    assert b":TRIG:SOUR IMM\n" in log and b":FORM:ELEM READ\n" in log
    assert not any(b"ROUT" in command or b"(@" in command or b"*RST" in command for command in log)
    if function in model.GATED_FUNCTIONS:
        assert not any(b":NPLC " in command or b":AVER:" in command or b":RANG" in command for command in log)
        assert f":SENS:{function.value}:APER 0.1\n".encode() in log
    if function is DmmFunction.TEMP:
        assert b":UNIT:TEMP K\n" in log
        assert not any(b":RANG" in command for command in log)


def test_ac_uses_ac_prefix_and_bandwidth_before_nplc():
    meter, transport = _meter()
    meter.configure_single_reading(DmmFunction.VOLT_AC, autorange=False, input_range=10.0, nplc=2.0)
    assert b":SENS:VOLT:AC:RANG 10.0\n" in transport.write_log
    bandwidth = transport.write_log.index(b":SENS:VOLT:AC:DET:BAND 300.0\n")
    integration = transport.write_log.index(b":SENS:VOLT:AC:NPLC 2.0\n")
    assert bandwidth < integration
    transport.write_log.clear()
    meter.configure_single_reading(DmmFunction.VOLT_AC, ac_bandwidth=30.0)
    assert not any(b":NPLC " in command for command in transport.write_log)


def test_single_snapshot_queries_actual_range_and_settings():
    meter, transport = _meter(responses=[
        b'"VOLT:DC"\n', b"0.001\n", b"0.05\n", b"0.1\n", b"1\n",
        b"2\n", b"1\n", b"4\n", b"REP\n",
    ])
    value, settings = meter.read_single_snapshot(DmmFunction.VOLT_DC)
    assert value == 0.001
    assert settings["range"] == 0.1 and settings["autorange"] == 1
    assert settings["nplc"] == 2 and settings["filter_count"] == 4
    assert settings["filter_type"] == 0 and settings["trigger_delay"] == 0.05
    assert transport.write_log == [
        b":SENS:FUNC?\n", b":READ?\n", b":TRIG:DEL?\n", b":SENS:VOLT:DC:RANG?\n",
        b":SENS:VOLT:DC:RANG:AUTO?\n", b":SENS:VOLT:DC:NPLC?\n",
        b":SENS:VOLT:DC:AVER:STAT?\n", b":SENS:VOLT:DC:AVER:COUN?\n", b":SENS:VOLT:DC:AVER:TCON?\n",
    ]


def test_frequency_snapshot_has_gate_time_but_no_unsupported_range_or_filter_queries():
    meter, transport = _meter(Keithley2700, [b'"FREQ"\n', b"1000\n", b"0\n", b"0.1\n"])
    value, settings = meter.read_single_snapshot(DmmFunction.FREQ)
    assert value == 1000 and settings["gate_time"] == 0.1
    assert set(settings) == {"trigger_delay", "timeout", "gate_time"}
    assert transport.write_log[-1] == b":SENS:FREQ:APER?\n"


@pytest.mark.parametrize("payload", [b"\n", b"1,2\n", b"malformed\n"])
def test_single_read_rejects_wrong_response_shape(payload):
    meter, _ = _meter(responses=[b'"VOLT:DC"\n', payload])
    with pytest.raises(ValueError):
        meter.read_single_snapshot(DmmFunction.VOLT_DC)


def test_changed_function_is_rejected_before_read():
    meter, transport = _meter(responses=[b'"VOLT:AC"\n'])
    with pytest.raises(RuntimeError, match="function changed"):
        meter.read_single_snapshot(DmmFunction.VOLT_DC)
    assert b":READ?\n" not in transport.write_log


def test_legacy_ac_range_helper_keeps_ac_qualifier():
    meter, transport = _meter(responses=[b'"CURR:AC"\n'])
    meter.set_range(0.1)
    assert transport.write_log[-1] == b":SENS:CURR:AC:RANG 0.1\n"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
