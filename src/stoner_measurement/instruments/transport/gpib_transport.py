"""GPIB transport implementation via PyVISA.

Provides a :class:`BaseTransport` implementation that communicates with
instruments over a GPIB (IEEE-488) bus using the :mod:`pyvisa` library.
PyVISA is an optional run-time dependency; an :exc:`ImportError` is raised
at construction time if it is not installed.
"""

from __future__ import annotations

import logging
import re
from time import perf_counter, sleep
from typing import TYPE_CHECKING

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.transport.base import BaseTransport

if TYPE_CHECKING:
    import pyvisa
    import pyvisa.resources

#: Regular expression that parses a GPIB VISA resource string of the form
#: ``"GPIB<board>::<address>::INSTR"``.
_GPIB_RESOURCE_RE = re.compile(r"^GPIB(\d+)::(\d+)::INSTR$", re.IGNORECASE)
_DEFAULT_GPIB_READ_TERMINATOR = None
_DEFAULT_GPIB_WRITE_TERMINATOR = "\n"
_DEFAULT_K6221_SERIAL_POLL = 0.05
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
            raise ImportError("pyvisa is required for GpibTransport. Install it with: pip install pyvisa") from exc

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
            self._log_comms_traffic("IEEE", "Connection opened.")
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
        self._log_comms_traffic("IEEE", "Connection closed.")


    def write(self, data: bytes, slow:int|None = None) -> None:
        """Write *data* to the GPIB instrument.

        Args:
            data (bytes):
                Raw bytes to transmit.  The bytes are decoded as ASCII before
                being passed to PyVISA's ``write_raw``.

        Keyword Arguments:
            slow (int|none, None):
                Whether to except the response to be slow and thus to pause for
                *slow* milliseconds.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        if self._resource is None:
            raise ConnectionError("GPIB transport is not open.")
        self._log_comms_traffic("TX", data)
        self._resource.write_raw(data)
        if slow is not None:
            sleep(slow/1000)
        rc = self._resource.read_stb()
        if rc&4:
            raise InstrumentError(f"Bad return status byte from {data.decode()}: STB={rc}")
        return rc

    def read(self, num_bytes: int | None = None) -> bytes:
        """Read one response frame from the GPIB instrument.

        Keyword Arguments:
            num_bytes (int | None, None):
                Optional maximum frame size for this call.  When ``None``,
                the transport uses the protocol-defined frame-size limit.

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
            response=b""
            while self.read_status_byte() & 16: # Loop until we don;'t have a message available.
                response += self._resource.read_raw(frame_limit)
            self._log_comms_traffic("RX", response)
            return response
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
        terminator = getattr(protocol, "gpib_terminator", getattr(protocol, "terminator", _DEFAULT_GPIB_READ_TERMINATOR))
        if isinstance(terminator, bytes):
            self._read_termination = terminator.decode("latin-1")
        else:
            self._read_termination = str(terminator)
        if self._resource is not None:
            self._resource.read_termination = self._read_termination
        logger.info(f"Termination sort for {self._resource} {self._read_termination=} {terminator=}")

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
        stb = self._resource.read_stb()
        self._log_comms_traffic("IEEE", f"{stb=}")
        return stb

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
            self._log_comms_traffic("IEEE", "Connection flushed.")
        except pyvisa.VisaIOError as exc:
            logger.debug("Ignoring GPIB Device Clear failure for %s: %s", self.resource_string, exc)


class PassThroughGpibTransport(GpibTransport):
    """Passthrough Keithley 6221 GPIB transport.

    Subclasses a GPIBTransport so that commands are wrapped in the SYST:COMM:SER:[SEND|ENT?]
    SCPI commands of a Keithley 6221 current source. This is primarily intentended for
    communicating with an attached Keithley 2182A nanovoltmeter, but could in principle be used
    for other instruments supports IEEE488.2 common comands.

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

    def __init__(self, address: int, board: int = 0, timeout: float = 2.0, max_read_chunks: int = 64) -> None:
        """Initialise the GPIB transport.

        Args:
            address (int):
                GPIB primary address (0–30) of the 6221.

        Keyword Parameters:
            board (int):
                GPIB board index.  Defaults to ``0``.
            timeout (float):
                Read timeout in seconds.  Defaults to ``2.0``.
            max_read_chunks (int):
                Maximum number of ``SYST:COMM:SER:ENT?`` chunks to poll while
                collecting one relayed response.

        Raises:
            ImportError:
                If :mod:`pyvisa` is not installed.
        """
        try:
            import pyvisa as _pyvisa  # noqa: F401
        except ImportError as exc:
            raise ImportError("pyvisa is required for GpibTransport. Install it with: pip install pyvisa") from exc

        super().__init__(address=address, board=board, timeout=timeout)
        self._max_read_chunks = max_read_chunks
        self._last_cmd = 0
        self.last_Stb=0

    @staticmethod
    def _serial_send_payload(cmd: str, terminator: str = "\n") -> str:
        """Return a relay-safe serial payload string.

        Args:
            cmd (str):
                Command string to relay.
            terminator (str):
                Serial command terminator to append (for example ``"\\r\\n"``).

        Returns:
            (str):
                Command with exactly one trailing *terminator* and doubled
                double-quotes for safe insertion in a SCPI quoted string.
        """
        command = cmd.rstrip("\r\n")
        payload = f"{command}{terminator}"
        return payload.replace('"', '""')

    def write(self, data: bytes, slow:int|None = None, host=False) -> None:
        """Write *data* to the 6221 wrapping the data in a SYST:COMM:SER:ESEND command.

        Args:
            data (bytes):
                Raw bytes to transmit.  The bytes are decoded as ASCII before
                being passed to PyVISA's ``write_raw``.

        Keyword Arguments:
            slow (int|none, None):
                Whether to except the response to be slow and thus to pause for
                *slow* milliseconds.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        if self._resource is None:
            raise ConnectionError("GPIB transport is not open.")
        if isinstance(data, str):
            data = data.encode("ascii")
        inner = data.rstrip(b"\r\n")
        if host:
            return super().write(data,slow=slow)
        if slow is None:
            wrapped = b'SYST:COMM:SER:SEND "' + inner.replace(b'"', b'""') + b';*STB?";ENT?'
        else:
            wrapped = b'SYST:COMM:SER:SEND "' + inner.replace(b'"', b'""')+b'"'
        if perf_counter()-self._last_cmd < _DEFAULT_K6221_SERIAL_POLL*10000:
            sleep(_DEFAULT_K6221_SERIAL_POLL)
        self._log_comms_traffic("TX", wrapped)
        self._resource.write_raw(wrapped)
        self._last_cmd=perf_counter()
        if slow is not None:
            sleep(slow/1000)
            wrapped = b'SYST:COMM:SER:SEND "*STB?";ENT?'
            self._log_comms_traffic("TX", wrapped)
            self._resource.write_raw(wrapped)            
        self.last_stb,response=self._read_serial_entry_chunk()
        self._log_comms_traffic("RX", response)
        self._log_comms_traffic("IEEE", f"stb={self.last_stb}")
        if self.last_stb&4:
            raise InstrumentError(f"Bad return status byte from {data.decode()}: STB={self.last_stb}")
        return self.last_stb
            
        
    def query(self,data: bytes, num_bytes: int | None = None, slow:bool = False) -> bytes:
        """Perform a write and then read operation in series.

        Args:
            data (bytes):
                Raw bytes to transmit.

        Keyword Arguments:
            num_bytes (int | None, None):
                Optional maximum frame size for this call.  When ``None``,
                the transport uses the protocol-defined frame-size limit.
            slow (int|none, None):
                Whether to except the response to be slow and thus to pause for
                *slow* milliseconds.

        Returns:
            (bytes):
                The bytes received from the instrument.

        Raises:
            ConnectionError:
                If the transport is not open.
            TimeoutError:
                If no data is received within :attr:`timeout` seconds.
            OSError:
                If a low-level I/O error occurs.
        """
        if self._resource is None:
            raise ConnectionError("GPIB transport is not open.")
        if isinstance(data, str):
            data = data.encode("ascii")
        inner = data.rstrip(b"\r\n")
        if slow is  None:
            wrapped = b'SYST:COMM:SER:SEND "' + inner.replace(b'"', b'""') + b';*STB?";ENT?'
        else:
            wrapped = b'SYST:COMM:SER:SEND "' + inner.replace(b'"', b'""')+b'"'
        if perf_counter()-self._last_cmd < _DEFAULT_K6221_SERIAL_POLL*10000:
            sleep(_DEFAULT_K6221_SERIAL_POLL)
        self._log_comms_traffic("TX", wrapped)
        self._resource.write_raw(wrapped)
        self._last_cmd=perf_counter()
        if slow is not None:
            sleep(slow/1000)
            wrapped = b'SYST:COMM:SER:SEND "*STB?";ENT?'
            self._log_comms_traffic("TX", wrapped)
            self._resource.write_raw(wrapped)                    
        self.last_stb,response=self._read_serial_entry_chunk()
        self._log_comms_traffic("RX", response)
        self._log_comms_traffic("IEEE", f"stb={self.last_stb}")
        if self.last_stb&4:
            raise InstrumentError(f"Bad return status byte from {data.decode()}: STB={self.last_stb}")
        return response
                 
    def _read_serial_entry_chunk(self, num_bytes: int | None = None) -> str:
        """Read a response from 2182A via 6221.
        
        If the response is blank (i.e. just newline) then reissue the ``SYST:COMM:SER:ENT?`` and try again. Repeat
        this for 64 times, pausing briefly in between. If we still have a blank response, try sending a ``*STB?`` to
        get an error code.

        Returns:
            (tuple[int,bytes]):
                We expect every response to contain a status bytes and a string message (which may be blank).

        Raises:
            ``InstrumentError`` if we can't get a response from the instrument.'                
        """
        command=b"SYST:COMM:SER:ENT?"
        for ix in range(1,65):
            raw = self._resource.read_raw()
            if raw.strip():
                parts=raw.split(b";")
                try:
                    rc=int(parts[-1])
                except ValueError:
                    raise InstrumentError(f"Response {raw} did not contain a status byte!")
                if len(parts)>1:
                    response=b";".join(parts[:-1])
                else:
                    response =b""
                return rc,response
            if ix<64:
                sleep(_DEFAULT_K6221_SERIAL_POLL)
                self._resource.write_raw(command)
        self._resource.write_raw(b'SYST:COMM:SER:SEND "*STB?";ENT?')
        raw = self._resource.read_raw().strip()
        try:
            rc=int(raw)
        except ValueError:
            raise InstrumentError(f"Response {raw} did not contain a status byte!")
        return rc,""

    def read(self, num_bytes: int | None = None) -> bytes:
        """Read one response frame from the instrument via the 6221's SYST:COMM:SER:ENT?.

        Keyword Arguments:
            num_bytes (int | None, None):
                Optional maximum frame size for this call.  When ``None``,
                the transport uses the protocol-defined frame-size limit.

        Returns:
            (bytes):
                Bytes received.

        Raises:
            ConnectionError:
                If the transport is not open.
            TimeoutError:
                If no data arrives within :attr:`timeout` seconds.
        """
        if self._resource is None:
            raise ConnectionError("GPIB transport is not open.")
        wrapped = b'SYST:COMM:SER:SEND "*STB?";ENT?'
        self._log_comms_traffic("TX", wrapped)
        self._resource.write_raw(wrapped)                    
        self.last_stb,response=self._read_serial_entry_chunk()
        self._log_comms_traffic("RX", response)
        self._log_comms_traffic("IEEE", f"stb={self.last_stb}")
        if self.last_stb&4:
            raise InstrumentError(f"Bad return status byte during read: STB={self.last_stb}")
        return response



    def read_status_byte(self) -> int | None:
        """Return the IEEE 488.2 status byte via a wrapped *STB? query.

        Because this is a serial over GPIB transport, this is not an out-of-band operation.

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
        return self.last_stb

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
            self.write("*CLS")
        except pyvisa.errors.VisaIOError as exc:
            logger.debug("Ignoring GPIB Device Clear failure for %s: %s", self.resource_string, exc)
