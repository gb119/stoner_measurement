"""Null (loopback) transport for simulation and unit testing.

:class:`NullTransport` does not open any real hardware connection.  Instead,
it records all :meth:`write` calls in an internal log and returns responses
from a user-supplied queue.  This makes it possible to test instrument code
without physical hardware.
"""

from __future__ import annotations

from collections import deque

from stoner_measurement.instruments.transport.base import BaseTransport


class NullTransport(BaseTransport):
    """Loopback transport for simulation and unit testing.

    :meth:`write` appends bytes to :attr:`write_log`.  :meth:`read` returns
    the next entry from the *responses* queue provided at construction time.
    When the queue is exhausted :meth:`read` returns ``b""``.

    Attributes:
        write_log (list[bytes]):
            All data written via :meth:`write` since the transport was created.
        timeout (float):
            Nominal timeout (not actually enforced).  Defaults to ``2.0``.

    Examples:
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> t = NullTransport(responses=[b"+0.123\\n"])
        >>> t.open()
        >>> t.write(b"MEAS:VOLT?\\n")
        >>> t.read_until(b"\\n")
        b'+0.123\\n'
        >>> t.write_log
        [b'MEAS:VOLT?\\n']
        >>> t.close()
    """

    def __init__(
        self,
        responses: list[bytes] | None = None,
        timeout: float = 2.0,
    ) -> None:
        """Initialise the null transport.

        Keyword Parameters:
            responses (list[bytes] | None):
                Ordered list of byte strings returned by successive
                :meth:`read` or :meth:`read_until` calls.  Defaults to
                an empty list (all reads return ``b""``).
            timeout (float):
                Nominal timeout value stored for interface compatibility.
                Defaults to ``2.0``.
        """
        super().__init__(timeout=timeout)
        self._responses: deque[bytes] = deque(responses or [])
        self.write_log: list[bytes] = []

    def open(self) -> None:
        """Mark the transport as open."""
        self._is_open = True

    def close(self) -> None:
        """Mark the transport as closed."""
        self._is_open = False

    def write(self, data: bytes) -> None:
        """Record *data* in :attr:`write_log`.

        Args:
            data (bytes):
                Bytes to record.

        Raises:
            ConnectionError:
                If the transport has not been opened.
        """
        if not self._is_open:
            raise ConnectionError("NullTransport is not open.")
        self.write_log.append(data)

    def read(self, num_bytes: int = 4096) -> bytes:
        """Return the next pre-loaded response, or ``b""`` when exhausted.

        Args:
            num_bytes (int):
                Ignored; present for interface compatibility.

        Returns:
            (bytes):
                Next response from the queue, or ``b""`` if the queue is empty.

        Raises:
            ConnectionError:
                If the transport has not been opened.
        """
        if not self._is_open:
            raise ConnectionError("NullTransport is not open.")
        if self._responses:
            return self._responses.popleft()
        return b""

    def read_until(self, terminator: bytes = b"\n") -> bytes:
        """Return the next pre-loaded response regardless of terminator.

        Args:
            terminator (bytes):
                Ignored; present for interface compatibility.

        Returns:
            (bytes):
                Next response from the queue, or ``b""`` if exhausted.

        Raises:
            ConnectionError:
                If the transport has not been opened.
        """
        return self.read()

    def queue_response(self, response: bytes) -> None:
        """Append *response* to the end of the response queue.

        Useful when building up a sequence of expected replies during a test.

        Args:
            response (bytes):
                Bytes to add to the response queue.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> t = NullTransport()
            >>> t.open()
            >>> t.queue_response(b"OK\\n")
            >>> t.read_until()
            b'OK\\n'
            >>> t.close()
        """
        self._responses.append(response)

    def clear_log(self) -> None:
        """Clear the write log and any pending responses.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> t = NullTransport(responses=[b"data\\n"])
            >>> t.open()
            >>> t.write(b"CMD\\n")
            >>> t.clear_log()
            >>> t.write_log
            []
            >>> t.close()
        """
        self.write_log.clear()
        self._responses.clear()
