"""Focused tests for protocol-level error handling contracts."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.protocol import LakeshoreProtocol, OxfordProtocol, ScpiProtocol


class TestScpiErrorHandling:
    def test_error_query_property(self):
        assert ScpiProtocol().error_query == "SYST:ERR?"

    def test_errors_in_response_is_false(self):
        assert ScpiProtocol().errors_in_response is False

    def test_check_error_no_error_variants(self):
        protocol = ScpiProtocol()
        protocol.check_error('+0,"No error"')
        protocol.check_error("+0,No error")
        protocol.check_error("+00,No error")

    def test_check_error_sets_error_code(self):
        with pytest.raises(InstrumentError) as exc_info:
            ScpiProtocol().check_error('-113,"Undefined header"', command="*IDN")
        exc = exc_info.value
        assert exc.error_code == -113
        assert exc.command == "*IDN"
        assert "Undefined header" in exc.message

    def test_check_error_unstructured_response(self):
        with pytest.raises(InstrumentError) as exc_info:
            ScpiProtocol().check_error("ERROR")
        assert exc_info.value.error_code is None

    def test_check_error_positive_nonzero_code(self):
        with pytest.raises(InstrumentError) as exc_info:
            ScpiProtocol().check_error('+100,"Device-specific error"')
        assert exc_info.value.error_code == 100


class TestOxfordErrorHandling:
    def test_errors_in_response_is_true(self):
        assert OxfordProtocol().errors_in_response is True

    def test_error_query_is_none(self):
        assert OxfordProtocol().error_query is None

    def test_check_error_ok(self):
        OxfordProtocol().check_error("1.234")

    def test_check_error_raises(self):
        with pytest.raises(InstrumentError) as exc_info:
            OxfordProtocol().check_error("?", command="R99")
        exc = exc_info.value
        assert exc.command == "R99"
        assert exc.error_code is None

    def test_check_error_question_mark_prefix(self):
        with pytest.raises(InstrumentError):
            OxfordProtocol().check_error("?status")


class TestLakeshoreErrorHandling:
    def test_errors_in_response_is_true(self):
        assert LakeshoreProtocol().errors_in_response is True

    def test_error_query_is_none(self):
        assert LakeshoreProtocol().error_query is None

    def test_check_error_ok(self):
        LakeshoreProtocol().check_error("+77.350")

    def test_check_error_raises(self):
        with pytest.raises(InstrumentError) as exc_info:
            LakeshoreProtocol().check_error("?", command="KRDG? Z")
        exc = exc_info.value
        assert exc.command == "KRDG? Z"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
