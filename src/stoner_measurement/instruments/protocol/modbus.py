"""Minimal Modbus RTU protocol descriptor.

This protocol class mainly exists so transports can be configured for Modbus
RTU style binary frames. The Eurotherm driver performs binary frame
construction and parsing itself because the generic :class:`BaseInstrument`
string-oriented helpers are not a natural fit for Modbus register traffic.
"""

from __future__ import annotations

from stoner_measurement.instruments.protocol.base import BaseProtocol


class ModbusRtuProtocol(BaseProtocol):
    """Minimal protocol descriptor for Modbus RTU binary frames."""

    terminator = None

    @property
    def max_frame_size(self) -> int:
        """Return a conservative Modbus RTU frame-size limit."""
        return 256

    def format_command(self, command: str) -> bytes:
        """Encode *command* as ASCII bytes.

        The Modbus drivers in this project do not use
        :meth:`BaseInstrument.write`; they talk to the transport with pre-built
        binary frames. This implementation exists only to satisfy the
        :class:`BaseProtocol` interface.
        """
        return command.encode("ascii")

    def format_query(self, query: str) -> bytes:
        """Encode *query* as ASCII bytes.

        See :meth:`format_command` for why this is intentionally minimal.
        """
        return query.encode("ascii")

    def parse_response(self, raw: bytes, *, command: str | None = None) -> str:
        """Decode *raw* for diagnostic purposes."""
        del command
        return raw.hex()
