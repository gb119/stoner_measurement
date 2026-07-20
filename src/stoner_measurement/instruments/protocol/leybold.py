"""Leybold pressure-controller ASCII protocol helpers."""

from __future__ import annotations

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.protocol.base import BaseProtocol

ACK = b"\x06"
NAK = b"\x15"
ENQ = b"\x05"
ETX = b"\x03"


class LeyboldCenterProtocol(BaseProtocol):
    """CR-terminated Leybold CENTER THREE RS232 protocol framing."""

    @property
    def errors_in_response(self) -> bool:
        """Leybold CENTER reports NAK/error status in the normal transaction."""
        return True

    def format_command(self, command: str) -> bytes:
        """Return ``command`` with the Leybold CR terminator."""
        return command.strip().encode("ascii") + b"\r"

    def format_query(self, query: str) -> bytes:
        """Leybold query and set commands use the same command frame."""
        return self.format_command(query)

    def parse_response(self, raw: bytes, *, command: str | None = None) -> str:
        """Decode and strip CR/LF framing from a response payload."""
        _ = command
        return raw.decode("ascii", errors="replace").strip()

    def check_error(self, response: str, *, command: str | None = None) -> None:
        """Raise when an ERR response reports one or more Leybold error bits."""
        if response and set(response) <= {"0", "1"} and len(response) == 4 and response != "0000":
            raise InstrumentError(f"Leybold error status {response}", command=command)
