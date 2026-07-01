"""Focused tests for BaseInstrument error polling and auto-check behavior."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.protocol import LakeshoreProtocol, OxfordProtocol, ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class _NullTransportWithEsb(NullTransport):
    """Null transport variant that reports ESB set for SCPI error polling tests."""

    def read_status_byte(self) -> int:
        return 0x04


class TestCheckForErrors:
    def test_check_for_errors_no_error(self):
        transport = _NullTransportWithEsb(responses=[b'+0,"No error"\n'])
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol())
        instrument.check_for_errors()
        assert transport.write_log == [b"SYST:ERR?\n"]

    def test_check_for_errors_raises_on_error(self):
        transport = _NullTransportWithEsb(responses=[b'-113,"Undefined header"\n'])
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol())
        with pytest.raises(InstrumentError) as exc_info:
            instrument.check_for_errors(command="*IDN")
        assert exc_info.value.error_code == -113
        assert exc_info.value.command == "*IDN"

    def test_check_for_errors_noop_for_response_embedded_protocol(self):
        transport = _null()
        instrument = BaseInstrument(transport, OxfordProtocol())
        instrument.check_for_errors()
        assert transport.write_log == []

    def test_check_for_errors_noop_when_no_error_query(self):
        transport = _null()
        instrument = BaseInstrument(transport, LakeshoreProtocol())
        instrument.check_for_errors()
        assert transport.write_log == []

    def test_check_for_errors_skips_query_when_stb_esb_clear(self):
        class StubTransport(NullTransport):
            def read_status_byte(self) -> int:
                return 0x00

        transport = StubTransport()
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol())
        instrument.check_for_errors()
        assert transport.write_log == []

    def test_check_for_errors_queries_when_stb_esb_set(self):
        class StubTransport(NullTransport):
            def read_status_byte(self) -> int:
                return 0x04

        transport = StubTransport(responses=[b'+0,"No error"\n'])
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol())
        instrument.check_for_errors()
        assert transport.write_log == [b"SYST:ERR?\n"]

    def test_check_for_errors_raises_when_stb_esb_set_and_error_queued(self):
        class StubTransport(NullTransport):
            def read_status_byte(self) -> int:
                return 0x04

        transport = StubTransport(responses=[b'-113,"Undefined header"\n'])
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol())
        with pytest.raises(InstrumentError) as exc_info:
            instrument.check_for_errors(command="BAD CMD")
        assert exc_info.value.error_code == -113
        assert exc_info.value.command == "BAD CMD"


class TestAutoCheckErrors:
    def test_auto_check_errors_default_true(self):
        assert BaseInstrument(NullTransport(), ScpiProtocol()).auto_check_errors is True

    def test_auto_check_errors_query_raises_on_scpi_error(self):
        transport = _NullTransportWithEsb(responses=[b"ACME\n", b'-113,"Undefined header"\n'])
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol(), auto_check_errors=True)
        with pytest.raises(InstrumentError, match="Undefined header"):
            instrument.query("*IDN?")

    def test_auto_check_errors_query_no_raise_when_queue_clear(self):
        transport = _NullTransportWithEsb(responses=[b"ACME\n", b'+0,"No error"\n'])
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol(), auto_check_errors=True)
        result = instrument.query("*IDN?")
        assert result == "ACME"

    def test_auto_check_errors_write_raises_on_scpi_error(self):
        transport = _NullTransportWithEsb(responses=[b'-113,"Undefined header"\n'])
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol(), auto_check_errors=True)
        with pytest.raises(InstrumentError):
            instrument.write("BAD CMD")

    def test_auto_check_errors_oxford_query_raises_on_error_response(self):
        transport = _null(responses=[b"?\r"])
        instrument = BaseInstrument(transport, OxfordProtocol(), auto_check_errors=True)
        with pytest.raises(InstrumentError, match="Oxford Instruments"):
            instrument.query("X9")

    def test_auto_check_errors_oxford_query_ok(self):
        transport = _null(responses=[b"R1.234\r"])
        instrument = BaseInstrument(transport, OxfordProtocol(), auto_check_errors=True)
        assert instrument.query("R1") == "1.234"

    def test_auto_check_errors_write_does_not_query_for_response_embedded(self):
        transport = _null()
        instrument = BaseInstrument(transport, OxfordProtocol(), auto_check_errors=True)
        instrument.write("H1")
        assert transport.write_log == [b"H1\r"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
