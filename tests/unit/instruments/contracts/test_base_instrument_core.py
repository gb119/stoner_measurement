"""Focused tests for core BaseInstrument communication behaviour."""

from __future__ import annotations

import logging

import pytest

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.keithley import Keithley2400
from stoner_measurement.instruments.protocol import LakeshoreProtocol, ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


def _null(responses=None):
    """Return an open NullTransport pre-loaded with *responses*."""
    transport = NullTransport(responses=responses or [])
    transport.open()
    return transport


class TestBaseInstrument:
    def test_connect_disconnect(self):
        t = NullTransport()
        k = Keithley2400(transport=t)
        assert not k.is_connected
        k.connect()
        assert k.is_connected
        k.disconnect()
        assert not k.is_connected

    def test_context_manager(self):
        t = NullTransport()
        with Keithley2400(transport=t) as k:
            assert k.is_connected
        assert not k.is_connected

    def test_write_formats_via_protocol(self):
        t = _null()
        k = Keithley2400(transport=t)
        k.write("OUTP ON")
        assert t.write_log == [b"OUTP ON\n"]

    def test_query_writes_then_reads(self):
        t = _null(responses=[b"answer\n"])
        k = Keithley2400(transport=t)
        result = k.query("*IDN?")
        assert t.write_log == [b"*IDN?\n"]
        assert result == "answer"

    def test_read_strips_whitespace(self):
        t = _null(responses=[b"  +1.0\r\n"])
        k = Keithley2400(transport=t)
        assert k.read() == "+1.0"

    def test_read_uses_transport_read_not_read_until(self):
        class _ReadOnlyTransport(NullTransport):
            def read(self, num_bytes: int = 4096) -> bytes:
                return b"ACME,MODEL,SN,FW\r\n"

            def read_until(self, terminator: bytes = b"\n") -> bytes:
                raise AssertionError("read_until should not be called")

        t = _ReadOnlyTransport()
        t.open()
        instr = BaseInstrument(t, ScpiProtocol(terminator=b"\r\n"))
        assert instr.read() == "ACME,MODEL,SN,FW"

    def test_constructor_binds_protocol_to_transport(self):
        class _ProtocolAwareTransport(NullTransport):
            def __init__(self):
                super().__init__()
                self.bound_protocol = None

            def set_protocol(self, protocol: object) -> None:
                super().set_protocol(protocol)
                self.bound_protocol = protocol

        transport = _ProtocolAwareTransport()
        protocol = LakeshoreProtocol()
        BaseInstrument(transport, protocol)
        assert transport.bound_protocol is protocol

    def test_identify(self):
        t = _null(responses=[b"KEITHLEY,2400,SN,v1\n"])
        k = Keithley2400(transport=t)
        assert k.identify() == "KEITHLEY,2400,SN,v1"

    def test_reset_sends_rst(self):
        t = _null()
        k = Keithley2400(transport=t)
        k.reset()
        assert t.write_log == [b"*RST\n"]

    def test_write_raises_when_not_open(self):
        t = NullTransport()
        k = Keithley2400(transport=t)
        with pytest.raises(ConnectionError):
            k.write("OUTP ON")

    def test_query_logs_tx_and_rx_transcript_records(self, caplog):
        t = _null(responses=[b"answer\n"])
        k = Keithley2400(transport=t)
        with caplog.at_level(logging.DEBUG, logger="stoner_measurement.sequence.comms"):
            assert k.query("*IDN?") == "answer"
        transcript_records = [
            record for record in caplog.records if getattr(record, "sm_traffic_channel", "") == "instrument_comms"
        ]
        assert len(transcript_records) == 2
        assert transcript_records[0].sm_traffic_direction == "TX"
        assert transcript_records[0].getMessage() == "TX *IDN?"
        assert transcript_records[0].sm_transport_address == ""
        assert transcript_records[1].sm_traffic_direction == "RX"
        assert transcript_records[1].getMessage() == "RX answer"
        assert transcript_records[1].sm_transport_address == ""

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
