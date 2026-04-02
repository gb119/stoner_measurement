"""SCPI (Standard Commands for Programmable Instruments) protocol.

Implements the IEEE 488.2 / SCPI-1999 message format:

* Commands and queries are terminated with a newline (``\\n``).
* Responses are stripped of leading/trailing whitespace.
* The error queue is accessible via the standard ``SYST:ERR?`` query.

Most modern bench instruments (Keithley, Agilent/Keysight, Tektronix, …)
speak SCPI, making this the most commonly used protocol in this package.
"""

from __future__ import annotations

from stoner_measurement.instruments.protocol.base import BaseProtocol

#: Terminator appended to every outgoing SCPI message.
SCPI_TERMINATOR = b"\n"

#: SCPI query to retrieve the first entry in the error queue.
SCPI_ERROR_QUERY = b"SYST:ERR?\n"

#: Response prefix from ``SYST:ERR?`` when no error is queued.
SCPI_NO_ERROR_PREFIX = "+0"


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
    """

    def __init__(self, terminator: bytes = SCPI_TERMINATOR) -> None:
        """Initialise the SCPI protocol.

        Keyword Parameters:
            terminator (bytes):
                Byte sequence appended to every outgoing message.
                Defaults to ``b"\\n"``.
        """
        self.terminator = terminator

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

    def check_error(self, response: str) -> None:
        """Raise :exc:`RuntimeError` if *response* signals a SCPI error.

        SCPI instruments report errors as ``"<code>,<message>"``.  A code of
        ``+0`` means *No Error*.

        Args:
            response (str):
                A response string previously obtained from ``SYST:ERR?``.

        Raises:
            RuntimeError:
                If *response* does not start with ``"+0"``.

        Examples:
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> ScpiProtocol().check_error('+0,"No error"')  # no exception
            >>> try:
            ...     ScpiProtocol().check_error('-113,"Undefined header"')
            ... except RuntimeError as exc:
            ...     print(exc)
            Instrument error: -113,"Undefined header"
        """
        if not response.startswith(SCPI_NO_ERROR_PREFIX):
            raise RuntimeError(f"Instrument error: {response}")
