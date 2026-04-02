"""Oxford Instruments carriage-return-terminated protocol.

Oxford Instruments cryogenic equipment (ITC, IPS, ILM, …) uses a simple
ASCII protocol where:

* Every command is a single uppercase letter optionally followed by a
  numeric argument, terminated by a carriage return (``\\r``).
* Responses begin with the echo of the command letter, followed by data
  and terminated with a carriage return.
* Status is encoded in a single-character status byte embedded in
  certain responses.

References:
    Oxford Instruments ITC 503 Remote-Control Handbook (1995).
    Oxford Instruments IPS 120-10 User Manual.
"""

from __future__ import annotations

from stoner_measurement.instruments.protocol.base import BaseProtocol

#: Terminator appended to every outgoing Oxford message.
OXFORD_TERMINATOR = b"\r"


class OxfordProtocol(BaseProtocol):
    """Oxford Instruments carriage-return-terminated ASCII protocol.

    Attributes:
        terminator (bytes):
            Byte sequence appended to outgoing messages.
            Defaults to ``b"\\r"``.

    Examples:
        >>> from stoner_measurement.instruments.protocol import OxfordProtocol
        >>> p = OxfordProtocol()
        >>> p.format_command("S5")
        b'S5\\r'
        >>> p.format_query("R1")
        b'R1\\r'
        >>> p.parse_response(b'R1.234\\r')
        '1.234'
    """

    def __init__(self, terminator: bytes = OXFORD_TERMINATOR) -> None:
        """Initialise the Oxford Instruments protocol.

        Keyword Parameters:
            terminator (bytes):
                Byte sequence appended to every outgoing message.
                Defaults to ``b"\\r"``.
        """
        self.terminator = terminator

    def format_command(self, command: str) -> bytes:
        """Format an Oxford Instruments command for transmission.

        Args:
            command (str):
                Command string without terminator.

        Returns:
            (bytes):
                ASCII-encoded command with carriage-return appended.

        Examples:
            >>> from stoner_measurement.instruments.protocol import OxfordProtocol
            >>> OxfordProtocol().format_command("H1")
            b'H1\\r'
        """
        return command.encode("ascii") + self.terminator

    def format_query(self, query: str) -> bytes:
        """Format an Oxford Instruments query for transmission.

        Oxford Instruments does not formally distinguish commands from
        queries; both are formatted identically.

        Args:
            query (str):
                Query string without terminator.

        Returns:
            (bytes):
                ASCII-encoded query with carriage-return appended.

        Examples:
            >>> from stoner_measurement.instruments.protocol import OxfordProtocol
            >>> OxfordProtocol().format_query("R1")
            b'R1\\r'
        """
        return query.encode("ascii") + self.terminator

    def parse_response(self, raw: bytes) -> str:
        """Parse a raw Oxford Instruments response.

        Oxford responses echo the command letter as their first character.
        This method strips the leading echo character, the trailing
        carriage return, and any surrounding whitespace.

        Args:
            raw (bytes):
                Raw bytes received from the instrument.

        Returns:
            (str):
                Response payload with the echo character and terminator removed.

        Examples:
            >>> from stoner_measurement.instruments.protocol import OxfordProtocol
            >>> OxfordProtocol().parse_response(b'R1.234\\r')
            '1.234'
            >>> OxfordProtocol().parse_response(b'S$A0C0H1L0R0B0\\r')
            '$A0C0H1L0R0B0'
        """
        decoded = raw.decode("ascii", errors="replace").strip()
        # Strip the leading command-echo character (first character)
        if len(decoded) > 1:
            return decoded[1:]
        return decoded

    def check_error(self, response: str) -> None:
        """Raise :exc:`RuntimeError` if *response* indicates an Oxford error.

        Oxford instruments encode the system status in a status byte
        (``?SXXX`` format for the ``X`` command).  The ``?`` prefix
        indicates the instrument did not understand the command.

        Args:
            response (str):
                Parsed response string.

        Raises:
            RuntimeError:
                If the response starts with ``"?"``.

        Examples:
            >>> from stoner_measurement.instruments.protocol import OxfordProtocol
            >>> OxfordProtocol().check_error("1.234")  # no exception
            >>> try:
            ...     OxfordProtocol().check_error("?")
            ... except RuntimeError as exc:
            ...     print(exc)
            Oxford Instruments instrument error: ?
        """
        if response.startswith("?"):
            raise RuntimeError(f"Oxford Instruments instrument error: {response}")
