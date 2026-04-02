"""SCPI (Standard Commands for Programmable Instruments) protocol.

Implements the IEEE 488.2 / SCPI-1999 message format:

* Commands and queries are terminated with a newline (``\\n``).
* Responses are stripped of leading/trailing whitespace.
* The error queue is accessible via the standard ``SYST:ERR?`` query.

Most modern bench instruments (Keithley, Agilent/Keysight, Tektronix, …)
speak SCPI, making this the most commonly used protocol in this package.
"""

from __future__ import annotations

import re

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.protocol.base import BaseProtocol

#: Terminator appended to every outgoing SCPI message.
SCPI_TERMINATOR = b"\n"

#: SCPI query to retrieve the first entry in the error queue.
SCPI_ERROR_QUERY = "SYST:ERR?"

#: Response prefix from ``SYST:ERR?`` when no error is queued.
SCPI_NO_ERROR_PREFIX = "+0"

#: Pattern matching a SCPI error response: ``<code>,"<message>"``.
_SCPI_ERROR_RE = re.compile(r"^\s*([+-]?\d+)\s*,\s*\"?(.*)\"?\s*$")


class ScpiProtocol(BaseProtocol):
    """SCPI protocol — newline-terminated ASCII messages.

    Attributes:
        terminator (bytes):
            Byte sequence appended to every outgoing message.
            Defaults to ``b"\\n"``.

    Examples:
        >>> from stoner_measurement.instruments.protocol import ScpiProtocol
        >>> p = ScpiProtocol()
        >>> p.format_command("OUTP ON")
        b'OUTP ON\\n'
        >>> p.format_query("MEAS:CURR?")
        b'MEAS:CURR?\\n'
        >>> p.parse_response(b'  +1.234E-03\\n')
        '+1.234E-03'
        >>> p.errors_in_response
        False
        >>> p.error_query
        'SYST:ERR?'
    """

    def __init__(self, terminator: bytes = SCPI_TERMINATOR) -> None:
        """Initialise the SCPI protocol.

        Keyword Parameters:
            terminator (bytes):
                Byte sequence appended to every outgoing message.
                Defaults to ``b"\\n"``.
        """
        self.terminator = terminator

    @property
    def error_query(self) -> str:
        """SCPI error-queue query string.

        Returns:
            (str):
                ``"SYST:ERR?"`` — the standard SCPI command for reading the
                first entry from the instrument's error queue.

        Examples:
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> ScpiProtocol().error_query
            'SYST:ERR?'
        """
        return SCPI_ERROR_QUERY

    def format_command(self, command: str) -> bytes:
        """Format a SCPI command for transmission.

        Args:
            command (str):
                SCPI command string (without terminator).

        Returns:
            (bytes):
                UTF-8 encoded command with terminator appended.

        Examples:
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> ScpiProtocol().format_command("VOLT 5.0")
            b'VOLT 5.0\\n'
        """
        return command.encode("utf-8") + self.terminator

    def format_query(self, query: str) -> bytes:
        """Format a SCPI query for transmission.

        Args:
            query (str):
                SCPI query string (without terminator).

        Returns:
            (bytes):
                UTF-8 encoded query with terminator appended.

        Examples:
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> ScpiProtocol().format_query("*IDN?")
            b'*IDN?\\n'
        """
        return query.encode("utf-8") + self.terminator

    def parse_response(self, raw: bytes) -> str:
        """Parse a raw SCPI response.

        Decodes *raw* as UTF-8 and strips surrounding whitespace.

        Args:
            raw (bytes):
                Raw bytes received from the instrument.

        Returns:
            (str):
                Decoded and stripped response string.

        Examples:
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> ScpiProtocol().parse_response(b'  KEITHLEY,2400,12345,C32\\r\\n')
            'KEITHLEY,2400,12345,C32'
        """
        return raw.decode("utf-8", errors="replace").strip()

    def check_error(self, response: str, *, command: str | None = None) -> None:
        """Raise :exc:`~stoner_measurement.instruments.errors.InstrumentError` if *response* signals a SCPI error.

        *response* should be the parsed reply to a ``SYST:ERR?`` query.  SCPI
        instruments encode their error queue entries as
        ``"<code>,\\"<message>\\""``; a code of ``+0`` means *No Error*.

        Args:
            response (str):
                A response string previously obtained from :attr:`error_query`.

        Keyword Parameters:
            command (str | None):
                The original command that triggered the error check.

        Raises:
            InstrumentError:
                If *response* does not start with ``"+0"``.

        Examples:
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> ScpiProtocol().check_error('+0,"No error"')  # no exception
            >>> try:
            ...     ScpiProtocol().check_error('-113,"Undefined header"', command="*IDN")
            ... except Exception as exc:
            ...     print(type(exc).__name__, exc)
            InstrumentError Undefined header (command: *IDN, code: -113)
        """
        if response.startswith(SCPI_NO_ERROR_PREFIX):
            return
        match = _SCPI_ERROR_RE.match(response)
        if match:
            error_code = int(match.group(1))
            message = match.group(2).strip().strip('"')
        else:
            error_code = None
            message = response
        raise InstrumentError(message, command=command, error_code=error_code)
