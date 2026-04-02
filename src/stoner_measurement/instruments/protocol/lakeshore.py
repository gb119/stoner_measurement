"""Lakeshore simple ASCII protocol.

Lakeshore temperature controllers and gaussmeters use a straightforward
ASCII protocol where:

* Commands and queries are separated by spaces from their arguments.
* Messages are terminated with a carriage-return / line-feed pair (``\\r\\n``).
* Query responses are plain ASCII strings, also CRLF-terminated.
* There is no formal distinction between a command and a query other than
  whether a response is expected; queries conventionally end with ``?``.

References:
    Lake Shore Model 336 Temperature Controller User Manual.
    Lake Shore Model 425 Gaussmeter User Manual.
"""

from __future__ import annotations

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.protocol.base import BaseProtocol

#: Terminator appended to every outgoing Lakeshore message.
LAKESHORE_TERMINATOR = b"\r\n"

#: Error response prefix used by some Lakeshore models.
LAKESHORE_ERROR_PREFIX = "?"


class LakeshoreProtocol(BaseProtocol):
    """Lakeshore simple ASCII CRLF-terminated protocol.

    Lakeshore instruments signal an unrecognised command by returning ``"?"``
    or a ``"?"``-prefixed string in place of the expected value.  Because
    the error indicator is embedded in the normal query response, this
    protocol sets :attr:`errors_in_response` to ``True``.

    Attributes:
        terminator (bytes):
            Byte sequence appended to outgoing messages.
            Defaults to ``b"\\r\\n"``.

    Examples:
        >>> from stoner_measurement.instruments.protocol import LakeshoreProtocol
        >>> p = LakeshoreProtocol()
        >>> p.format_command("SETP 1,10.0")
        b'SETP 1,10.0\\r\\n'
        >>> p.format_query("KRDG? A")
        b'KRDG? A\\r\\n'
        >>> p.parse_response(b'+273.150\\r\\n')
        '+273.150'
        >>> p.errors_in_response
        True
        >>> p.error_query is None
        True
    """

    @property
    def errors_in_response(self) -> bool:
        """``True`` — Lakeshore errors are embedded in the response payload.

        Returns:
            (bool):
                Always ``True`` for :class:`LakeshoreProtocol`.

        Examples:
            >>> from stoner_measurement.instruments.protocol import LakeshoreProtocol
            >>> LakeshoreProtocol().errors_in_response
            True
        """
        return True

    def __init__(self, terminator: bytes = LAKESHORE_TERMINATOR) -> None:
        """Initialise the Lakeshore protocol.

        Keyword Parameters:
            terminator (bytes):
                Byte sequence appended to every outgoing message.
                Defaults to ``b"\\r\\n"``.
        """
        self.terminator = terminator

    def format_command(self, command: str) -> bytes:
        """Format a Lakeshore command for transmission.

        Args:
            command (str):
                Command string without terminator.

        Returns:
            (bytes):
                ASCII-encoded command with CRLF appended.

        Examples:
            >>> from stoner_measurement.instruments.protocol import LakeshoreProtocol
            >>> LakeshoreProtocol().format_command("RAMP 1,1,0.5")
            b'RAMP 1,1,0.5\\r\\n'
        """
        return command.encode("ascii") + self.terminator

    def format_query(self, query: str) -> bytes:
        """Format a Lakeshore query for transmission.

        Args:
            query (str):
                Query string without terminator.

        Returns:
            (bytes):
                ASCII-encoded query with CRLF appended.

        Examples:
            >>> from stoner_measurement.instruments.protocol import LakeshoreProtocol
            >>> LakeshoreProtocol().format_query("SRDG? B")
            b'SRDG? B\\r\\n'
        """
        return query.encode("ascii") + self.terminator

    def parse_response(self, raw: bytes) -> str:
        """Parse a raw Lakeshore response.

        Decodes the bytes as ASCII and strips surrounding whitespace,
        including the CRLF terminator.

        Args:
            raw (bytes):
                Raw bytes received from the instrument.

        Returns:
            (str):
                Decoded response string with whitespace stripped.

        Examples:
            >>> from stoner_measurement.instruments.protocol import LakeshoreProtocol
            >>> LakeshoreProtocol().parse_response(b'+77.350\\r\\n')
            '+77.350'
            >>> LakeshoreProtocol().parse_response(b'1,CONTROL,1\\r\\n')
            '1,CONTROL,1'
        """
        return raw.decode("ascii", errors="replace").strip()

    def check_error(self, response: str, *, command: str | None = None) -> None:
        """Raise :exc:`~stoner_measurement.instruments.errors.InstrumentError` if *response* indicates a Lakeshore error.

        Some Lakeshore models return ``"?"`` or a ``"?"``-prefixed string for
        unrecognised commands.

        Args:
            response (str):
                Parsed response string.

        Keyword Parameters:
            command (str | None):
                The original command that was sent.

        Raises:
            InstrumentError:
                If the response is ``"?"`` or starts with ``"?"``.

        Examples:
            >>> from stoner_measurement.instruments.protocol import LakeshoreProtocol
            >>> LakeshoreProtocol().check_error("+77.350")  # no exception
            >>> try:
            ...     LakeshoreProtocol().check_error("?", command="KRDG? Z")
            ... except Exception as exc:
            ...     print(type(exc).__name__, exc)
            InstrumentError Lakeshore: unrecognised command (command: KRDG? Z)
        """
        if response.startswith(LAKESHORE_ERROR_PREFIX):
            raise InstrumentError(
                "Lakeshore: unrecognised command",
                command=command,
            )
