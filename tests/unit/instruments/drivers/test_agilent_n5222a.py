"""Focused tests for the Agilent N5222A PNA driver."""

from __future__ import annotations

import numpy as np
import pytest

from stoner_measurement.instruments import (
    AgilentN5222A,
    NetworkAnalyserTriggerSource,
)
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.transport import NullTransport


def _driver(responses=()):
    transport = NullTransport(responses=list(responses))
    transport.open()
    return AgilentN5222A(transport, auto_check_errors=False)


def _capability_responses(model="N5222A"):
    return [
        f"Agilent Technologies,{model},MY123,A.10.49\n".encode(),
        b"010,080\n",
        b"2\n",
        b"32\n",
        b"24\n",
        b"1e7\n",
        b"2.65e10\n",
    ]


def test_identity_and_runtime_capabilities_are_queried_not_b_model_assumed():
    driver = _driver(_capability_responses())

    capabilities = driver.get_capabilities()

    assert capabilities.port_count == 2
    assert capabilities.max_channels == 32
    assert capabilities.max_traces_per_channel == 24
    assert capabilities.frequency_min_hz == pytest.approx(1e7)
    assert capabilities.frequency_max_hz == pytest.approx(2.65e10)
    assert capabilities.has_frequency_offset


def test_identity_rejects_n5222b():
    driver = _driver([_capability_responses("N5222B")[0]])

    with pytest.raises(InstrumentError, match="N5222B"):
        driver.confirm_identity()


@pytest.mark.parametrize(
    "catalogue",
    [
        b'"Meas1",S11,"Meas2",S21\n',
        b'"Meas1,S11,Meas2,S21"\n',
    ],
)
def test_named_measurement_selection_and_modification(catalogue):
    driver = _driver(_capability_responses() + [b'"Meas2"\n', catalogue])
    driver.get_capabilities()

    assert driver.get_measurement_parameter(channel=1, trace=2) == "S21"
    driver.set_measurement_parameter("S12", channel=1, trace=2)
    assert driver.transport.write_log[-5:] == [
        b":CALC1:PAR:MNUM 2\n",
        b":CALC1:PAR:SEL?\n",
        b":CALC1:PAR:CAT:EXT? DEF\n",
        b":CALC1:PAR:MNUM 2\n",
        b":CALC1:PAR:MOD S12\n",
    ]


def test_pna_trigger_mapping_and_single_sweep():
    driver = _driver([b"MAN\n", b"1\n"])

    driver.set_trigger_source(NetworkAnalyserTriggerSource.BUS)
    assert driver.get_trigger_source() is NetworkAnalyserTriggerSource.MANUAL
    driver.perform_single_sweep(2)
    assert driver.transport.write_log == [
        b":TRIG:SOUR MAN\n",
        b":TRIG:SOUR?\n",
        b":INIT2:CONT 0\n",
        b":INIT2:IMM;*OPC?\n",
    ]


def test_external_ttl_pulse_modulation_queries_presence_and_state():
    driver = _driver([b"1\n", b"ON\n"])

    assert driver.has_external_pulse_modulator(2)
    assert driver.get_external_pulse_modulation(2, 1)
    driver.set_external_pulse_modulation(False, 2, 1)

    assert driver.transport.write_log == [
        b":SOUR2:PULS:MOD:EXIS?\n",
        b":SOUR2:PULS1:MOD:STAT?\n",
        b":SOUR2:PULS1:MOD:STAT 0\n",
    ]


def test_external_ttl_pulse_modulation_rejects_missing_modulator():
    driver = _driver([b"0\n"])

    with pytest.raises(NotImplementedError, match="external pulse modulator"):
        driver.set_external_pulse_modulation(True, 1, 1)


def test_ascii_acquisition_uses_measurement_scoped_data_commands():
    driver = _driver(
        [
            b"1\n",
            b"ASC,0\n",
            b"1,2,3\n",
            b"ASC,0\n",
            b"2,0,4,0,6,0\n",
            b'"Meas1"\n',
            b'"Meas1",S21\n',
        ]
    )

    sweep = driver.acquire()

    trace = sweep.traces[0]
    np.testing.assert_allclose(trace.stimulus, [1, 2, 3])
    np.testing.assert_allclose(trace.values, [2, 4, 6])
    assert trace.parameter == "S21"
    assert b":CALC1:MEAS1:X:VAL?\n" in driver.transport.write_log
    assert b":CALC1:MEAS1:DATA:SDAT?\n" in driver.transport.write_log


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
