"""Abstract base class for instrument transport layers.

All transport implementations must inherit from :class:`BaseTransport` and
implement the abstract methods to provide a uniform communication interface
regardless of the underlying physical connection.
"""

from __future__ import annotations

import re
import urllib.parse
from abc import ABC, abstractmethod

# Matches the start of a VISA resource string and captures the prefix for
# later classification.  ASRL resources may have a non-numeric path component
# (e.g. "ASRL/dev/ttyUSB0::INSTR"), so any non-colon characters are allowed
# after the prefix rather than digits only.
_VISA_RE = re.compile(r"^(GPIB|TCPIP|ASRL)[^:]*::", re.IGNORECASE)


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

    def read_status_byte(self) -> int | None:
        """Return the instrument status byte via an out-of-band mechanism.

        Some transports (notably GPIB) can perform a *serial poll* to read
        the IEEE 488.2 status byte (STB) without sending a command, allowing
        the caller to check whether an error condition exists before issuing
        an expensive error-queue query.

        The default implementation returns ``None``, indicating that no
        out-of-band mechanism is available.  Subclasses that support
        hardware-level status polling (e.g. :class:`GpibTransport`) should
        override this method.

        If :meth:`read_status_byte` returns ``None``,
        :meth:`~stoner_measurement.instruments.base_instrument.BaseInstrument.check_for_errors`
        will fall back to issuing the protocol's
        :attr:`~stoner_measurement.instruments.protocol.base.BaseProtocol.error_query`
        command directly.

        Returns:
            (int | None):
                The 8-bit status byte, or ``None`` if not supported.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> NullTransport().read_status_byte() is None
            True
        """
        return None

    @classmethod
    def from_uri(cls, uri: str) -> BaseTransport:
        """Construct the appropriate transport instance from a URI or VISA resource string.

        Two input formats are recognised:

        **URI strings** use a ``scheme://...`` format:

        * ``serial:///dev/ttyUSB0?baud_rate=9600`` — :class:`SerialTransport`.
          On Windows use ``serial://COM3?baud_rate=9600``.  Query parameters
          mirror the :class:`SerialTransport` constructor keyword arguments:
          ``baud_rate`` (alias ``baud``), ``data_bits``, ``stop_bits``,
          ``parity``, ``timeout``.
        * ``tcp://host:port?timeout=2.0`` — :class:`EthernetTransport`.
        * ``udp://host:port?timeout=2.0`` — :class:`UdpTransport`.
        * ``gpib://board:address/?timeout=2.0`` or ``gpib://address/?timeout=2.0``
          — :class:`GpibTransport`.  When only one component is present it is
          treated as the *address*; the *board* defaults to ``0``.

        **VISA resource strings** follow the IVI/VISA convention and do not
        contain ``://``:

        * ``GPIB[N]::address::INSTR`` — :class:`GpibTransport`.
        * ``TCPIP[N]::host::port::SOCKET`` — :class:`EthernetTransport`.
        * ``TCPIP[N]::host::INSTR`` — :class:`EthernetTransport` on the
          default SCPI port ``5025``.
        * ``ASRL<port>::INSTR`` — :class:`SerialTransport`.  The port name is
          everything after ``ASRL`` and before ``::INSTR``, e.g.
          ``ASRL/dev/ttyUSB0::INSTR`` or ``ASRLCOM3::INSTR``.

        Args:
            uri (str):
                URI string or VISA resource string describing the transport.

        Returns:
            (BaseTransport):
                A concrete transport instance corresponding to *uri*.

        Raises:
            ValueError:
                If the URI scheme or VISA resource type is not supported, or if
                required components (host, port, address) are missing.

        Examples:
            >>> from stoner_measurement.instruments.transport import BaseTransport, SerialTransport
            >>> t = BaseTransport.from_uri("serial:///dev/ttyUSB0?baud_rate=9600")
            >>> isinstance(t, SerialTransport)
            True
            >>> t.port
            '/dev/ttyUSB0'
            >>> t.baud_rate
            9600
            >>> from stoner_measurement.instruments.transport import EthernetTransport
            >>> t = BaseTransport.from_uri("tcp://192.168.1.100:5025")
            >>> isinstance(t, EthernetTransport)
            True
            >>> t.host
            '192.168.1.100'
            >>> t.port
            5025
            >>> from stoner_measurement.instruments.transport import GpibTransport
            >>> t = BaseTransport.from_uri("GPIB0::22::INSTR")
            >>> isinstance(t, GpibTransport)
            True
            >>> t.address
            22
            >>> t.board
            0
        """
        if "://" not in uri:
            return cls._from_visa_resource_string(uri)
        return cls._from_uri_string(uri)

    @classmethod
    def _from_uri_string(cls, uri: str) -> BaseTransport:
        """Parse a ``scheme://...`` URI and return the matching transport."""
        parsed = urllib.parse.urlparse(uri)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)

        def get_query_param(name: str, default: str | None = None) -> str | None:
            """Return the first value of query parameter *name*, or *default*."""
            values = query.get(name)
            return values[0] if values else default

        scheme = parsed.scheme.lower()
        timeout_str = get_query_param("timeout")
        timeout = float(timeout_str) if timeout_str is not None else 2.0

        if scheme == "serial":
            from stoner_measurement.instruments.transport.serial_transport import SerialTransport

            port = parsed.netloc if parsed.netloc else parsed.path
            if not port:
                raise ValueError(f"No serial port specified in URI: {uri!r}")
            baud_str = get_query_param("baud_rate") or get_query_param("baud")
            return SerialTransport(
                port=port,
                baud_rate=int(baud_str) if baud_str is not None else 9600,
                data_bits=int(get_query_param("data_bits") or 8),
                stop_bits=float(get_query_param("stop_bits") or 1),
                parity=(get_query_param("parity") or "N").upper(),
                xonxoff=(get_query_param("xonxoff") or "").lower() in ("1", "true", "yes"),
                rtscts=(get_query_param("rtscts") or "").lower() in ("1", "true", "yes"),
                timeout=timeout,
            )

        if scheme in ("tcp", "tcpip"):
            from stoner_measurement.instruments.transport.ethernet_transport import (
                EthernetTransport,
            )

            host = parsed.hostname
            port_num = parsed.port
            if not host or port_num is None:
                raise ValueError(f"TCP URI must include host and port: {uri!r}")
            return EthernetTransport(host=host, port=port_num, timeout=timeout)

        if scheme == "udp":
            from stoner_measurement.instruments.transport.udp_transport import UdpTransport

            host = parsed.hostname
            port_num = parsed.port
            if not host or port_num is None:
                raise ValueError(f"UDP URI must include host and port: {uri!r}")
            return UdpTransport(host=host, port=port_num, timeout=timeout)

        if scheme == "gpib":
            from stoner_measurement.instruments.transport.gpib_transport import GpibTransport

            if parsed.port is not None:
                board = int(parsed.hostname or 0)
                address = parsed.port
            else:
                board = 0
                address = int(parsed.hostname or parsed.path.strip("/"))
            return GpibTransport(address=address, board=board, timeout=timeout)

        raise ValueError(f"Unsupported URI scheme: {scheme!r}")

    @classmethod
    def _from_visa_resource_string(cls, resource: str) -> BaseTransport:
        """Parse a VISA resource string and return the matching transport.

        Recognised prefixes: ``GPIB``, ``TCPIP``, ``ASRL``.
        """
        if not _VISA_RE.match(resource):
            raise ValueError(f"Unrecognised VISA resource string: {resource!r}")

        parts = resource.split("::")
        prefix_upper = parts[0].upper()

        if prefix_upper.startswith("GPIB"):
            from stoner_measurement.instruments.transport.gpib_transport import GpibTransport

            board_str = parts[0][4:]
            board = int(board_str) if board_str else 0
            address = int(parts[1])
            return GpibTransport(address=address, board=board)

        if prefix_upper.startswith("TCPIP"):
            from stoner_measurement.instruments.transport.ethernet_transport import (
                EthernetTransport,
            )

            host = parts[1]
            suffix = parts[-1].upper()
            if suffix == "SOCKET":
                port = int(parts[2])
            else:
                port = 5025
            return EthernetTransport(host=host, port=port)

        if prefix_upper.startswith("ASRL"):
            from stoner_measurement.instruments.transport.serial_transport import SerialTransport

            port = parts[0][4:]
            if not port:
                raise ValueError(f"No serial port in VISA resource string: {resource!r}")
            return SerialTransport(port=port)

        raise ValueError(f"Unsupported VISA resource string: {resource!r}")

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
