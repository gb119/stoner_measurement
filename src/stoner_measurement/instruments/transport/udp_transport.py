"""UDP (User Datagram Protocol) transport implementation.

Provides a :class:`BaseTransport` implementation that communicates with
instruments over a UDP socket.  The standard-library :mod:`socket` module
is used; no third-party packages are required.

UDP is a connectionless, unreliable datagram protocol.  Calling
:meth:`UdpTransport.open` creates a UDP socket and uses
:func:`socket.connect` to record the default remote address, which allows
:func:`socket.send` and :func:`socket.recv` to be used instead of the
address-bearing :func:`socket.sendto` / :func:`socket.recvfrom` variants.
"""

from __future__ import annotations

import socket

from stoner_measurement.instruments.transport.base import BaseTransport


class UdpTransport(BaseTransport):
    """UDP socket transport for network-connected instruments.

    Attributes:
        host (str):
            Hostname or IP address of the instrument.
        port (int):
            UDP port number.
        timeout (float):
            Socket read timeout in seconds.  Defaults to ``2.0``.

    Examples:
        >>> from stoner_measurement.instruments.transport import UdpTransport
        >>> t = UdpTransport(host="192.168.1.100", port=5025)
        >>> t.host
        '192.168.1.100'
        >>> t.port
        5025
    """

    def __init__(self, host: str, port: int, timeout: float = 2.0) -> None:
        """Initialise the UDP transport.

        Args:
            host (str):
                Hostname or IP address of the instrument.
            port (int):
                UDP port number.

        Keyword Parameters:
            timeout (float):
                Socket read timeout in seconds.  Defaults to ``2.0``.
        """
        super().__init__(timeout=timeout)
        self.host = host
        self.port = port
        self._socket: socket.socket | None = None

    def open(self) -> None:
        """Create a UDP socket and record the default remote address.

        :func:`socket.connect` is called on the UDP socket so that subsequent
        :func:`socket.send` and :func:`socket.recv` calls are directed to and
        filtered from the given *host* and *port* without requiring explicit
        address arguments.

        Raises:
            ConnectionError:
                If the socket cannot be created or bound.
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.settimeout(self._timeout)
            self._socket.connect((self.host, self.port))
            self._is_open = True
        except OSError as exc:
            if self._socket is not None:
                self._socket.close()
                self._socket = None
            raise ConnectionError(f"Cannot open UDP socket to {self.host}:{self.port}: {exc}") from exc

    def close(self) -> None:
        """Close the UDP socket."""
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self._is_open = False

    def write(self, data: bytes) -> None:
        """Send *data* to the instrument as a single UDP datagram.

        Args:
            data (bytes):
                Raw bytes to transmit.

        Raises:
            ConnectionError:
                If the socket is not open.
            OSError:
                If a low-level I/O error occurs.
        """
        if self._socket is None:
            raise ConnectionError("UDP transport is not open.")
        self._socket.send(data)

    def read(self, num_bytes: int = 4096) -> bytes:
        """Receive up to *num_bytes* from the instrument.

        Args:
            num_bytes (int):
                Maximum number of bytes to read per datagram.  Defaults to ``4096``.

        Returns:
            (bytes):
                Bytes received from the instrument.

        Raises:
            ConnectionError:
                If the socket is not open.
            TimeoutError:
                If no datagram arrives within :attr:`timeout` seconds.
        """
        if self._socket is None:
            raise ConnectionError("UDP transport is not open.")
        try:
            return self._socket.recv(num_bytes)
        except TimeoutError as exc:
            raise TimeoutError(f"No data received from {self.host}:{self.port} within {self._timeout}s.") from exc

    @property
    def transport_address(self) -> str:
        """Return the remote endpoint as ``"<host>:<port>"``.

        Returns:
            (str):
                UDP address string, e.g. ``"192.168.1.100:5025"``.

        Examples:
            >>> from stoner_measurement.instruments.transport import UdpTransport
            >>> UdpTransport(host="192.168.1.100", port=5025).transport_address
            '192.168.1.100:5025'
        """
        return f"{self.host}:{self.port}"

    def _apply_timeout(self, value: float) -> None:
        """Update the socket timeout on a live connection."""
        if self._socket is not None:
            self._socket.settimeout(value)
