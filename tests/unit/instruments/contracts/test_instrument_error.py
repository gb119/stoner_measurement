"""Focused tests for the InstrumentError contract."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.errors import InstrumentError


class TestInstrumentError:
    """Structured exception class for instrument errors."""

    def test_message_only(self):
        exc = InstrumentError("bad news")
        assert str(exc) == "bad news"
        assert exc.message == "bad news"
        assert exc.command is None
        assert exc.error_code is None

    def test_with_command(self):
        exc = InstrumentError("bad news", command="*IDN")
        assert "command: *IDN" in str(exc)
        assert exc.command == "*IDN"

    def test_with_error_code(self):
        exc = InstrumentError("Undefined header", error_code=-113)
        assert "code: -113" in str(exc)
        assert exc.error_code == -113

    def test_with_all_fields(self):
        exc = InstrumentError("Undefined header", command="*IDN", error_code=-113)
        s = str(exc)
        assert "Undefined header" in s
        assert "command: *IDN" in s
        assert "code: -113" in s

    def test_is_exception(self):
        assert issubclass(InstrumentError, Exception)

    def test_exported_from_instruments_package(self):
        from stoner_measurement.instruments import InstrumentError as exported

        assert exported is InstrumentError


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
