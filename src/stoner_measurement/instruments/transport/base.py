"""Abstract base class for instrument transport layers.

All transport implementations must inherit from :class:`BaseTransport` and
implement the abstract methods to provide a uniform communication interface
regardless of the underlying physical connection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTransport(ABC):
    """Abstract base for all instrument transport layers.

    A transport is responsible for the physical transmission and reception
    of raw bytes over a specific interface (serial port, Ethernet socket,
    GPIB bus, etc.).  Higher-level protocol formatting is handled separately
    by :class:`~stoner_measurement.instruments.protocol.base.BaseProtocol`.

    Attributes:
        timeout (float):
            Read timeout in seconds.  A value of ``0`` means non-blocking and
            ``None`` means block indefinitely.

    Examples:
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> t = NullTransport()
        >>> t.is_open
        False
        >>> t.open()
        >>> t.is_open
        True
        >>> t.close()
        >>> t.is_open
        False
    """

    def __init__(self, timeout: float = 2.0) -> None:
        """Initialise the transport with a default timeout.

        Args:
            timeout (float):
                Read timeout in seconds.  Defaults to ``2.0``.
        """
        self._timeout: float = timeout
        self._is_open: bool = False

    @property
    def timeout(self) -> float:
        """Read timeout in seconds."""
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = value
        self._apply_timeout(value)

    def _apply_timeout(self, value: float) -> None:
        """Apply a new timeout to the underlying connection.

        Called automatically when :attr:`timeout` is set after the transport
        has been opened.  The default implementation is a no-op; override in
        subclasses that support live timeout updates.
        """

    @property
    def is_open(self) -> bool:
        """``True`` if the transport connection is currently open."""
        return self._is_open

    @abstractmethod
    def open(self) -> None:
        """Open the physical connection to the instrument.

        Raises:
            ConnectionError:
                If the connection cannot be established.
        """

    @abstractmethod
    def close(self) -> None:
        """Close the physical connection to the instrument."""

    @abstractmethod
    def write(self, data: bytes) -> None:
        """Send *data* to the instrument.

        Args:
            data (bytes):
                Raw bytes to transmit.

        Raises:
            ConnectionError:
                If the transport is not open.
            OSError:
                If a low-level I/O error occurs.
        """

    @abstractmethod
    def read(self, num_bytes: int = 4096) -> bytes:
        """Read up to *num_bytes* from the instrument.

        Args:
            num_bytes (int):
                Maximum number of bytes to read.  Defaults to ``4096``.

        Returns:
            (bytes):
                The bytes received from the instrument.

        Raises:
            ConnectionError:
                If the transport is not open.
            TimeoutError:
                If no data is received within :attr:`timeout` seconds.
        """

    def read_until(self, terminator: bytes = b"\n") -> bytes:
        """Read bytes from the instrument until *terminator* is encountered.

        The default implementation calls :meth:`read` one byte at a time.
        Subclasses may override this with a more efficient implementation.

        Args:
            terminator (bytes):
                Byte sequence that marks the end of a response.
                Defaults to ``b"\\n"``.

        Returns:
            (bytes):
                All bytes received up to and including the *terminator*.

        Raises:
            ConnectionError:
                If the transport is not open.
            TimeoutError:
                If no data is received within :attr:`timeout` seconds.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> t = NullTransport(responses=[b"hello\\n"])
            >>> t.open()
            >>> t.read_until(b"\\n")
            b'hello\\n'
            >>> t.close()
        """
        buf = b""
        while True:
            byte = self.read(1)
            buf += byte
            if buf.endswith(terminator):
                break
        return buf

    def flush(self) -> None:
        """Flush any pending data in the transport buffers.

        The default implementation is a no-op; override in subclasses where
        a hardware flush operation is meaningful.
        """

    def __enter__(self) -> BaseTransport:
        """Open the transport and return ``self`` for use as a context manager.

        Returns:
            (BaseTransport):
                This transport instance.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> with NullTransport() as t:
            ...     t.is_open
            True
        """
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        """Close the transport when leaving a ``with`` block."""
        self.close()
