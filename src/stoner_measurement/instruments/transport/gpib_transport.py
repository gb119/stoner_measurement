"""GPIB transport implementation via PyVISA.

Provides a :class:`BaseTransport` implementation that communicates with
instruments over a GPIB (IEEE-488) bus using the :mod:`pyvisa` library.
PyVISA is an optional run-time dependency; an :exc:`ImportError` is raised
at construction time if it is not installed.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from stoner_measurement.instruments.transport.base import BaseTransport

if TYPE_CHECKING:
    import pyvisa
    import pyvisa.resources

#: Regular expression that parses a GPIB VISA resource string of the form
#: ``"GPIB<board>::<address>::INSTR"``.
_GPIB_RESOURCE_RE = re.compile(r"^GPIB(\d+)::(\d+)::INSTR$", re.IGNORECASE)
_DEFAULT_GPIB_READ_TERMINATOR = "\n"
logger = logging.getLogger(__name__)


class GpibTransport(BaseTransport):
    """GPIB transport using PyVISA.

    Wraps a PyVISA ``GPIBInstrument`` resource to provide the standard
    :class:`BaseTransport` interface.  The VISA resource string is
    constructed from *address* and *board* as ``"GPIB<board>::<address>::INSTR"``.

    Attributes:
        address (int):
            GPIB primary address of the instrument (0–30).
        board (int):
            GPIB board (interface) index.  Defaults to ``0``.
        timeout (float):
            Read timeout in seconds.  Defaults to ``2.0``.

    Examples:
        >>> from stoner_measurement.instruments.transport import GpibTransport
        >>> t = GpibTransport(address=22)
        >>> t.address
        22
        >>> t.board
        0
        >>> t.resource_string
        'GPIB0::22::INSTR'
    """

    def __init__(self, address: int, board: int = 0, timeout: float = 2.0) -> None:
        """Initialise the GPIB transport.

        Args:
            address (int):
                GPIB primary address (0–30).

        Keyword Parameters:
            board (int):
                GPIB board index.  Defaults to ``0``.
            timeout (float):
                Read timeout in seconds.  Defaults to ``2.0``.

        Raises:
            ImportError:
                If :mod:`pyvisa` is not installed.
        """
        try:
            import pyvisa as _pyvisa  # noqa: F401
        except ImportError as exc:
            raise ImportError("pyvisa is required for GpibTransport. " "Install it with: pip install pyvisa") from exc

        super().__init__(timeout=timeout)
        self.address = address
        self.board = board
        self._resource: pyvisa.resources.GPIBInstrument | None = None
        self._rm: pyvisa.ResourceManager | None = None
        self._read_termination: str = _DEFAULT_GPIB_READ_TERMINATOR

    @classmethod
    def from_resource_string(cls, resource_string: str, timeout: float = 2.0) -> GpibTransport:
        """Construct a :class:`GpibTransport` from a VISA resource string.

        Parses the *board* and *address* components from a resource string of
        the form ``"GPIB<board>::<address>::INSTR"`` and delegates to the
        standard constructor.

        Args:
            resource_string (str):
                VISA resource string, e.g. ``"GPIB0::22::INSTR"``.

        Keyword Parameters:
            timeout (float):
                Read timeout in seconds.  Defaults to ``2.0``.

        Returns:
            (GpibTransport):
                A new :class:`GpibTransport` instance.

        Raises:
            ValueError:
                If *resource_string* does not match the expected GPIB format.
            ImportError:
                If :mod:`pyvisa` is not installed.

        Examples:
            >>> from stoner_measurement.instruments.transport import GpibTransport
            >>> t = GpibTransport.from_resource_string("GPIB0::14::INSTR")
            >>> t.address
            14
            >>> t.board
            0
            >>> t.resource_string
            'GPIB0::14::INSTR'
        """
        m = _GPIB_RESOURCE_RE.match(resource_string.strip())
        if not m:
            raise ValueError(
                f"Cannot parse GPIB resource string {resource_string!r}. "
                "Expected format: 'GPIB<board>::<address>::INSTR'."
            )
        board = int(m.group(1))
        address = int(m.group(2))
        return cls(address=address, board=board, timeout=timeout)

    @property
    def resource_string(self) -> str:
        """VISA resource string for this GPIB address.

        Returns:
            (str):
                Resource string in the form ``"GPIB<board>::<address>::INSTR"``.

        Examples:
            >>> from stoner_measurement.instruments.transport import GpibTransport
            >>> GpibTransport(address=14, board=1).resource_string
            'GPIB1::14::INSTR'
        """
        return f"GPIB{self.board}::{self.address}::INSTR"

    def open(self) -> None:
        """Open the GPIB resource via PyVISA.

        Raises:
            ConnectionError:
                If the resource cannot be opened.
        """
        import pyvisa

        try:
            self._rm = pyvisa.ResourceManager()
            self._resource = self._rm.open_resource(self.resource_string)
            self._resource.timeout = int(self._timeout * 1000)  # pyvisa uses milliseconds
            self._resource.send_end = True
            self._resource.read_termination = self._read_termination
            self._is_open = True
        except pyvisa.VisaIOError as exc:
            raise ConnectionError(f"Cannot open GPIB resource {self.resource_string!r}: {exc}") from exc

    def close(self) -> None:
        """Close the GPIB resource."""
        if self._resource is not None:
            self._resource.close()
            self._resource = None
        if self._rm is not None:
            self._rm.close()
            self._rm = None
        self._is_open = False

    def write(self, data: bytes) -> None:
        """Write *data* to the GPIB instrument.

        Args:
            data (bytes):
                Raw bytes to transmit.  The bytes are decoded as ASCII before
                being passed to PyVISA's ``write_raw``.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        if self._resource is None:
            raise ConnectionError("GPIB transport is not open.")
        self._resource.write_raw(data)

    def read(self, num_bytes: int | None = None) -> bytes:
        """Read one response frame from the GPIB instrument.

        Args:
            num_bytes (int | None):
                Optional maximum number of bytes to read.  When ``None``,
                the protocol-defined frame-size limit is used.

        Returns:
            (bytes):
                Bytes received.

        Raises:
            ConnectionError:
                If the transport is not open.
            TimeoutError:
                If no data arrives within :attr:`timeout` seconds.
        """
        import pyvisa

        if self._resource is None:
            raise ConnectionError("GPIB transport is not open.")
        frame_limit = self._resolve_max_frame_size(num_bytes)
        try:
            return self._resource.read_raw(frame_limit)
        except pyvisa.errors.VisaIOError as exc:
            raise TimeoutError(f"Timeout reading from GPIB address {self.address}: {exc}") from exc

    @property
    def transport_address(self) -> str:
        """Return the VISA resource string for this GPIB instrument.

        Returns:
            (str):
                VISA resource string, e.g. ``"GPIB0::22::INSTR"``.

        Examples:
            >>> from stoner_measurement.instruments.transport import GpibTransport
            >>> GpibTransport(address=22).transport_address
            'GPIB0::22::INSTR'
        """
        return self.resource_string

    def _apply_timeout(self, value: float) -> None:
        """Update the PyVISA timeout on a live connection.

        PyVISA expresses timeout in milliseconds.
        """
        if self._resource is not None:
            self._resource.timeout = int(value * 1000)

    def _apply_protocol(self, protocol: object) -> None:
        """Apply protocol-specific read termination settings.

        Args:
            protocol (object):
                Protocol instance supplied by the owning instrument.
        """
        terminator = getattr(protocol, "terminator", _DEFAULT_GPIB_READ_TERMINATOR)
        if isinstance(terminator, bytes):
            read_termination = terminator.decode("latin-1")
        else:
            read_termination = str(terminator)
        self._read_termination = read_termination
        if self._resource is not None:
            self._resource.read_termination = self._read_termination

    def read_status_byte(self) -> int | None:
        """Return the IEEE 488.2 status byte via a GPIB serial poll.

        Performs an out-of-band serial poll (PyVISA ``read_stb()``) without
        transmitting any command to the instrument.  This is the preferred
        mechanism for checking the GPIB status byte because it does not
        consume a response from the instrument's output buffer.

        Returns:
            (int | None):
                The 8-bit status byte, or ``None`` if the transport is not
                currently open.

        Examples:
            >>> from stoner_measurement.instruments.transport import GpibTransport
            >>> t = GpibTransport(address=22)
            >>> t.read_status_byte() is None  # not open
            True
        """
        if self._resource is None:
            return None
        return int(self._resource.read_stb())

    def flush(self) -> None:
        """Send IEEE 488.2 Device Clear to the instrument and reset the interface.

        Calls the PyVISA ``clear()`` method, which sends the Selected Device
        Clear (SDC) message over the GPIB bus.  This resets the instrument's
        parser and discards any bytes queued in its output buffer, preventing
        stale responses from old commands being misread after a reconnect.

        If the resource is not open or Device Clear fails, the exception is
        ignored and logged at debug level.
        """
        if self._resource is None:
            return
        import pyvisa

        try:
            self._resource.clear()
        except pyvisa.VisaIOError as exc:
            logger.debug("Ignoring GPIB Device Clear failure for %s: %s", self.resource_string, exc)
