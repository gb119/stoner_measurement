"""Abstract base class for instrument communication protocols.

A protocol is responsible for formatting commands into the byte sequence that
should be sent over the transport, and for parsing raw bytes received from the
instrument back into a meaningful string response.  It does **not** handle the
physical transmission; that is the responsibility of the transport layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseProtocol(ABC):
    """Abstract base for all instrument communication protocols.

    A protocol defines the command syntax and response parsing rules for a
    particular family of instruments.  Concrete subclasses implement the
    :meth:`format_command`, :meth:`format_query`, and
    :meth:`parse_response` methods according to the protocol conventions.

    Examples:
        >>> from stoner_measurement.instruments.protocol import ScpiProtocol
        >>> p = ScpiProtocol()
        >>> p.format_command("VOLT 1.0")
        b'VOLT 1.0\\n'
        >>> p.format_query("VOLT?")
        b'VOLT?\\n'
        >>> p.parse_response(b' +1.234E+00\\n')
        '+1.234E+00'
    """

    @abstractmethod
    def format_command(self, command: str) -> bytes:
        """Format a command string for transmission.

        Args:
            command (str):
                The human-readable command string, without any protocol-
                specific terminators.

        Returns:
            (bytes):
                Bytes ready to be passed to :meth:`BaseTransport.write`.
        """

    @abstractmethod
    def format_query(self, query: str) -> bytes:
        """Format a query string for transmission.

        Args:
            query (str):
                The human-readable query string.  Many protocols distinguish
                between commands (which do not elicit a response) and queries
                (which do); subclasses may add or modify a suffix accordingly.

        Returns:
            (bytes):
                Bytes ready to be passed to :meth:`BaseTransport.write`.
        """

    @abstractmethod
    def parse_response(self, raw: bytes) -> str:
        """Parse a raw response from the instrument.

        Args:
            raw (bytes):
                Raw bytes as returned by the transport layer.

        Returns:
            (str):
                The cleaned-up response string, stripped of any protocol-
                specific framing, terminators, or whitespace.
        """

    def check_error(self, response: str) -> None:
        """Raise an exception if *response* indicates an instrument error.

        The default implementation is a no-op.  Override in subclasses that
        support error checking (e.g. by querying the instrument's error queue).

        Args:
            response (str):
                The parsed response string to examine.

        Raises:
            RuntimeError:
                If an instrument-level error is detected in the response.
        """
