"""Ethernet (TCP/IP socket) transport implementation.

Provides a :class:`BaseTransport` implementation that communicates with
instruments over a standard TCP socket connection.  No third-party packages
are required; only the standard-library :mod:`socket` module is used.
"""

from __future__ import annotations

import socket

from stoner_measurement.instruments.transport.base import BaseTransport


class EthernetTransport(BaseTransport):
    """TCP/IP socket transport for network-connected instruments.

    Attributes:
        host (str):
            Hostname or IP address of the instrument.
        port (int):
            TCP port number (most instruments use 5025 for SCPI).
        timeout (float):
            Socket read timeout in seconds.  Defaults to ``2.0``.

    Examples:
        >>> from stoner_measurement.instruments.transport import EthernetTransport
        >>> t = EthernetTransport(host="192.168.1.100", port=5025)
        >>> t.host
        '192.168.1.100'
        >>> t.port
        5025
    """

    def __init__(self, host: str, port: int, timeout: float = 2.0) -> None:
        """Initialise the Ethernet transport.

        Args:
            host (str):
                Hostname or IP address of the instrument.
            port (int):
                TCP port number.

        Keyword Parameters:
            timeout (float):
                Socket read timeout in seconds.  Defaults to ``2.0``.
        """
        super().__init__(timeout=timeout)
        self.host = host
        self.port = port
        self._socket: socket.socket | None = None

    def open(self) -> None:
        """Connect to the instrument over TCP.

        Raises:
            ConnectionError:
                If the TCP connection cannot be established.
        """
        try:
            self._socket = socket.create_connection((self.host, self.port), timeout=self._timeout)
            self._socket.settimeout(self._timeout)
            self._is_open = True
        except OSError as exc:
            raise ConnectionError(
                f"Cannot connect to {self.host}:{self.port}: {exc}"
            ) from exc

    def close(self) -> None:
        """Close the TCP socket."""
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()
            self._socket = None
        self._is_open = False

    def write(self, data: bytes) -> None:
        """Send *data* to the instrument.

        Args:
            data (bytes):
                Raw bytes to transmit.

        Raises:
            ConnectionError:
                If the socket is not open.
        """
        if self._socket is None:
            raise ConnectionError("Ethernet transport is not open.")
        self._socket.sendall(data)

    def read(self, num_bytes: int = 4096) -> bytes:
        """Receive up to *num_bytes* from the instrument.

        Args:
            num_bytes (int):
                Maximum number of bytes to read.  Defaults to ``4096``.

        Returns:
            (bytes):
                Bytes received from the instrument.

        Raises:
            ConnectionError:
                If the socket is not open.
            TimeoutError:
                If no data arrives within :attr:`timeout` seconds.
        """
        if self._socket is None:
            raise ConnectionError("Ethernet transport is not open.")
        try:
            data = self._socket.recv(num_bytes)
        except TimeoutError as exc:
            raise TimeoutError(
                f"No data received from {self.host}:{self.port} within {self._timeout}s."
            ) from exc
        if not data:
            raise TimeoutError(
                f"Connection closed by {self.host}:{self.port}."
            )
        return data

    def flush(self) -> None:
        """Drain any unread data from the socket receive buffer.

        Temporarily sets the socket to non-blocking mode and discards any
        data already in the receive buffer.
        """
        if self._socket is None:
            return
        self._socket.setblocking(False)
        try:
            while True:
                chunk = self._socket.recv(4096)
                if not chunk:
                    break
        except BlockingIOError:
            pass
        finally:
            self._socket.settimeout(self._timeout)

    def _apply_timeout(self, value: float) -> None:
        """Update the socket timeout on a live connection."""
        if self._socket is not None:
            self._socket.settimeout(value)
