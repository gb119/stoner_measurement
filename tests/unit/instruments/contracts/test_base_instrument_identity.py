"""Focused tests for BaseInstrument identity validation and queue clearing."""

from __future__ import annotations

import logging

import pytest

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.lakeshore import Lakeshore335
from stoner_measurement.instruments.oxford import OxfordIPS120
from stoner_measurement.instruments.protocol import ScpiProtocol
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


class TestIdentityAndQueueClearing:
    def test_confirm_identity_passes_for_expected_tokens(self):
        class _IdentityInstr(BaseInstrument):
            _EXPECTED_IDENTITY_TOKENS = ("MODEL1",)

        transport = _null(responses=[b"VENDOR,MODEL1,SN,FW\n"])
        instrument = _IdentityInstr(transport, ScpiProtocol(), auto_check_errors=False)
        assert instrument.confirm_identity() == "VENDOR,MODEL1,SN,FW"

    def test_confirm_identity_raises_for_mismatched_tokens(self):
        class _IdentityInstr(BaseInstrument):
            _EXPECTED_IDENTITY_TOKENS = ("MODEL1",)

        transport = _null(responses=[b"VENDOR,OTHER,SN,FW\n"])
        instrument = _IdentityInstr(transport, ScpiProtocol(), auto_check_errors=False)
        with pytest.raises(InstrumentError, match="Unexpected instrument identity"):
            instrument.confirm_identity()

    def test_confirm_identity_uses_model_fallback(self):
        class _ModelInstr(BaseInstrument):
            _MODEL = "MODEL2"

        transport = _null(responses=[b"VENDOR,MODEL2,SN,FW\n"])
        instrument = _ModelInstr(transport, ScpiProtocol(), auto_check_errors=False)
        assert instrument.confirm_identity() == "VENDOR,MODEL2,SN,FW"

    def test_check_for_errors_clears_remaining_queue_entries(self, caplog):
        transport = _NullTransportWithEsb(
            responses=[
                b'-113,"First error"\n',
                b'-114,"Second error"\n',
                b'+0,"No error"\n',
            ]
        )
        transport.open()
        instrument = BaseInstrument(transport, ScpiProtocol())
        with caplog.at_level(logging.ERROR, logger="stoner_measurement.sequence.comms"):
            with pytest.raises(InstrumentError, match="First error"):
                instrument.check_for_errors(command="BAD CMD")
        assert transport.write_log == [b"SYST:ERR?\n", b"SYST:ERR?\n", b"SYST:ERR?\n"]
        assert any("Cleared queued instrument error" in record.getMessage() for record in caplog.records)

    def test_temperature_controller_connect_closes_on_identity_failure(self):
        transport = NullTransport(responses=[b"VENDOR,WRONGMODEL,SN,1.0\r\n"])
        controller = Lakeshore335(transport)
        with pytest.raises(InstrumentError, match="Unexpected instrument identity"):
            controller.connect()
        assert not controller.is_connected

    def test_magnet_controller_connect_closes_on_identity_failure(self):
        transport = NullTransport(responses=[b"VWRONGMODEL 3.07\r"])
        controller = OxfordIPS120(transport)
        with pytest.raises(InstrumentError, match="Unexpected instrument identity"):
            controller.connect()
        assert not controller.is_connected


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
