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

    Two complementary error-detection strategies are supported:

    **Response-embedded errors** (Oxford Instruments, Lakeshore):
        The instrument encodes an error indicator directly inside its normal
        response string (e.g. a leading ``"?"``).  :attr:`errors_in_response`
        returns ``True`` for these protocols and :meth:`check_error` should be
        called on every parsed response.

    **Error-queue errors** (SCPI):
        The instrument maintains an internal error queue that must be polled
        separately, typically via a ``SYST:ERR?`` query.  :attr:`error_query`
        returns the query string and :meth:`check_error` is called on the
        result of that query rather than on normal responses.

    Examples:
        >>> from stoner_measurement.instruments.protocol import ScpiProtocol
        >>> p = ScpiProtocol()
        >>> p.format_command("VOLT 1.0")
        b'VOLT 1.0\\n'
        >>> p.format_query("VOLT?")
        b'VOLT?\\n'
        >>> p.parse_response(b' +1.234E+00\\n')
        '+1.234E+00'
        >>> p.errors_in_response
        False
        >>> p.error_query
        'SYST:ERR?'
    """

    @property
    def errors_in_response(self) -> bool:
        """``True`` if errors are embedded in normal query responses.

        When this property returns ``True`` (Oxford, Lakeshore), the instrument
        signals command errors directly inside its reply to a query.
        :meth:`check_error` should be called on every parsed response.

        When ``False`` (SCPI), errors are held in a separate error queue and
        must be retrieved via :attr:`error_query`.

        Returns:
            (bool):
                ``True`` for response-embedded error protocols; ``False``
                (default) for error-queue protocols.

        Examples:
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> ScpiProtocol().errors_in_response
            False
            >>> from stoner_measurement.instruments.protocol import OxfordProtocol
            >>> OxfordProtocol().errors_in_response
            True
        """
        return False

    @property
    def error_query(self) -> str | None:
        """Query string used to retrieve the first error from the error queue.

        Returns ``None`` (default) for protocols that embed errors in responses.
        Override in subclasses that maintain a separate error queue (e.g. SCPI
        returns ``"SYST:ERR?"``).

        Returns:
            (str | None):
                Query command string, or ``None`` if not applicable.

        Examples:
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> ScpiProtocol().error_query
            'SYST:ERR?'
            >>> from stoner_measurement.instruments.protocol import OxfordProtocol
            >>> OxfordProtocol().error_query is None
            True
        """
        return None

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

    def check_error(self, response: str, *, command: str | None = None) -> None:
        """Raise :exc:`~stoner_measurement.instruments.errors.InstrumentError` if *response* indicates an error.

        The default implementation is a no-op.  Override in subclasses that
        support error checking.

        For protocols where :attr:`errors_in_response` is ``True`` (Oxford,
        Lakeshore), *response* is the parsed reply to any query and the method
        must inspect it for error indicators.

        For error-queue protocols (SCPI), *response* is the parsed reply to
        the :attr:`error_query` command.

        Args:
            response (str):
                The parsed response string to examine.

        Keyword Parameters:
            command (str | None):
                The original command that was sent (used to populate the
                :attr:`~stoner_measurement.instruments.errors.InstrumentError.command`
                field).  Defaults to ``None``.

        Raises:
            InstrumentError:
                If an instrument-level error is detected in the response.
        """
