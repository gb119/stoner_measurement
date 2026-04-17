"""Serial (RS-232 / RS-485) transport implementation.

Wraps :mod:`serial` (pyserial) to provide a :class:`BaseTransport`-compatible
serial-port connection.  Pyserial is an optional run-time dependency; an
:exc:`ImportError` is raised at construction time if it is not installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stoner_measurement.instruments.transport.base import BaseTransport

if TYPE_CHECKING:
    import serial as _serial_module


class SerialTransport(BaseTransport):
    """Serial-port transport using pyserial.

    The default parameters match the most common factory settings found on
    scientific instruments (Keithley, Agilent/Keysight, Oxford Instruments,
    Lakeshore, Stanford Research Systems, etc.): **9600 baud, 8 data bits,
    1 stop bit, no parity, no flow control**.  Adjust when an instrument's
    manual specifies different values.

    Attributes:
        port (str):
            System device name (e.g. ``"/dev/ttyUSB0"`` or ``"COM3"``).
        baud_rate (int):
            Baud rate in bits per second.  Common values: 9600, 19200,
            57600, 115200.  Defaults to ``9600``.
        data_bits (int):
            Number of data bits per character (5–8).  Defaults to ``8``.
        stop_bits (float):
            Number of stop bits (1, 1.5, or 2).  Defaults to ``1``.
        parity (str):
            Parity mode: ``"N"`` (none), ``"E"`` (even), ``"O"`` (odd),
            ``"M"`` (mark), or ``"S"`` (space).  Defaults to ``"N"``.
        xonxoff (bool):
            Enable software (XON/XOFF) flow control.  Defaults to ``False``.
        rtscts (bool):
            Enable hardware (RTS/CTS) flow control.  Defaults to ``False``.
        timeout (float):
            Read timeout in seconds.  Defaults to ``2.0``.

    Examples:
        >>> from stoner_measurement.instruments.transport import SerialTransport
        >>> t = SerialTransport(port="/dev/ttyUSB0", baud_rate=9600)
        >>> t.port
        '/dev/ttyUSB0'
        >>> t.baud_rate
        9600
        >>> t.xonxoff
        False
        >>> t.rtscts
        False
    """

    def __init__(
        self,
        port: str,
        baud_rate: int = 9600,
        data_bits: int = 8,
        stop_bits: float = 1,
        parity: str = "N",
        xonxoff: bool = False,
        rtscts: bool = False,
        timeout: float = 2.0,
    ) -> None:
        """Initialise the serial transport.

        The default values match the most common factory settings used by
        scientific instruments: 9600 baud, 8 data bits, 1 stop bit, no parity,
        and no flow control.  Override only when the instrument manual specifies
        different values.

        Args:
            port (str):
                System device name for the serial port.

        Keyword Parameters:
            baud_rate (int):
                Baud rate in bits per second.  Defaults to ``9600``.
            data_bits (int):
                Number of data bits (5–8).  Defaults to ``8``.
            stop_bits (float):
                Number of stop bits (1, 1.5, or 2).  Defaults to ``1``.
            parity (str):
                Parity mode (``"N"``, ``"E"``, ``"O"``, ``"M"``, ``"S"``).
                Defaults to ``"N"``.
            xonxoff (bool):
                Enable software (XON/XOFF) flow control.  Defaults to
                ``False``.
            rtscts (bool):
                Enable hardware (RTS/CTS) flow control.  Defaults to
                ``False``.
            timeout (float):
                Read timeout in seconds.  Defaults to ``2.0``.

        Raises:
            ImportError:
                If :mod:`serial` (pyserial) is not installed.
        """
        try:
            import serial as _serial  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "pyserial is required for SerialTransport. " "Install it with: pip install pyserial"
            ) from exc

        super().__init__(timeout=timeout)
        self.port = port
        self.baud_rate = baud_rate
        self.data_bits = data_bits
        self.stop_bits = stop_bits
        self.parity = parity
        self.xonxoff = xonxoff
        self.rtscts = rtscts
        self._serial: _serial_module.Serial | None = None

    def open(self) -> None:
        """Open the serial port.

        Raises:
            ConnectionError:
                If the port cannot be opened.
        """
        import serial

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                bytesize=self.data_bits,
                stopbits=self.stop_bits,
                parity=self.parity,
                xonxoff=self.xonxoff,
                rtscts=self.rtscts,
                timeout=self._timeout,
            )
            self._is_open = True
        except serial.SerialException as exc:
            raise ConnectionError(f"Cannot open serial port {self.port!r}: {exc}") from exc

    def close(self) -> None:
        """Close the serial port."""
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
        self._is_open = False

    def write(self, data: bytes) -> None:
        """Send *data* over the serial port.

        Args:
            data (bytes):
                Raw bytes to transmit.

        Raises:
            ConnectionError:
                If the port is not open.
        """
        if self._serial is None or not self._serial.is_open:
            raise ConnectionError("Serial port is not open.")
        self._serial.write(data)

    def read(self, num_bytes: int = 4096) -> bytes:
        """Read up to *num_bytes* from the serial port.

        Args:
            num_bytes (int):
                Maximum number of bytes to read.  Defaults to ``4096``.

        Returns:
            (bytes):
                Bytes received.

        Raises:
            ConnectionError:
                If the port is not open.
            TimeoutError:
                If no data arrives within :attr:`timeout` seconds.
        """
        if self._serial is None or not self._serial.is_open:
            raise ConnectionError("Serial port is not open.")
        data = self._serial.read(num_bytes)
        if not data:
            raise TimeoutError(f"No data received from {self.port!r} within {self._timeout}s.")
        return data

    def read_until(self, terminator: bytes = b"\n") -> bytes:
        """Read from the serial port until *terminator* is received.

        Uses pyserial's native ``read_until`` for efficiency.

        Args:
            terminator (bytes):
                Terminator byte sequence.  Defaults to ``b"\\n"``.

        Returns:
            (bytes):
                All bytes up to and including the terminator.

        Raises:
            ConnectionError:
                If the port is not open.
            TimeoutError:
                If no data arrives within :attr:`timeout` seconds.
        """
        if self._serial is None or not self._serial.is_open:
            raise ConnectionError("Serial port is not open.")
        data = self._serial.read_until(terminator)
        if not data:
            raise TimeoutError(f"No data received from {self.port!r} within {self._timeout}s.")
        return data

    def flush(self) -> None:
        """Flush both input and output buffers of the serial port."""
        if self._serial is not None and self._serial.is_open:
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()

    def _apply_timeout(self, value: float) -> None:
        """Update the pyserial timeout on a live connection."""
        if self._serial is not None and self._serial.is_open:
            self._serial.timeout = value
