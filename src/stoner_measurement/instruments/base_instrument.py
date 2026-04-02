"""Base instrument class providing the composition of transport and protocol.

:class:`BaseInstrument` is the foundation of the instrument hierarchy.  Every
concrete instrument class is a (possibly indirect) subclass of
:class:`BaseInstrument` and gains the ability to communicate with a physical
instrument by holding references to a :class:`BaseTransport` and a
:class:`BaseProtocol` instance.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class BaseInstrument(ABC):
    """Base class for all instrument drivers.

    Uses a composition pattern: each instrument instance holds a *transport*
    responsible for the physical byte-level communication, and a *protocol*
    responsible for formatting commands and parsing responses.  This design
    allows any transport/protocol combination to be substituted without
    changing the instrument driver code.

    Attributes:
        transport (BaseTransport):
            Transport layer instance (serial, Ethernet, GPIB, …).
        protocol (BaseProtocol):
            Protocol instance (SCPI, Oxford, Lakeshore, …).

    Examples:
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import ScpiProtocol
        >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
        >>> t = NullTransport(responses=[b"ACME,Model1,SN001,v1.0\\n"])
        >>> instr = BaseInstrument(transport=t, protocol=ScpiProtocol())
        >>> instr.connect()
        >>> instr.is_connected
        True
        >>> instr.query("*IDN?")
        'ACME,Model1,SN001,v1.0'
        >>> instr.disconnect()
        >>> instr.is_connected
        False
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        """Initialise the instrument with a transport and protocol.

        Args:
            transport (BaseTransport):
                Transport layer responsible for byte-level I/O.
            protocol (BaseProtocol):
                Protocol responsible for formatting commands and parsing
                responses.
        """
        self.transport = transport
        self.protocol = protocol

    @property
    def is_connected(self) -> bool:
        """``True`` if the underlying transport is currently open.

        Returns:
            (bool):
                Connection state of the transport.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> instr = BaseInstrument(NullTransport(), ScpiProtocol())
            >>> instr.is_connected
            False
        """
        return self.transport.is_open

    def connect(self) -> None:
        """Open the transport connection to the instrument.

        Raises:
            ConnectionError:
                If the underlying transport cannot be opened.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> instr = BaseInstrument(NullTransport(), ScpiProtocol())
            >>> instr.connect()
            >>> instr.is_connected
            True
            >>> instr.disconnect()
        """
        self.transport.open()

    def disconnect(self) -> None:
        """Close the transport connection to the instrument.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> instr = BaseInstrument(NullTransport(), ScpiProtocol())
            >>> instr.connect()
            >>> instr.disconnect()
            >>> instr.is_connected
            False
        """
        self.transport.close()

    def write(self, command: str) -> None:
        """Send a command to the instrument without expecting a response.

        The command is formatted by :attr:`protocol` before being passed to
        :attr:`transport`.

        Args:
            command (str):
                Command string in the instrument's command language.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> t = NullTransport()
            >>> instr = BaseInstrument(t, ScpiProtocol())
            >>> instr.connect()
            >>> instr.write("OUTP ON")
            >>> t.write_log
            [b'OUTP ON\\n']
            >>> instr.disconnect()
        """
        self.transport.write(self.protocol.format_command(command))

    def read(self) -> str:
        """Read a response from the instrument.

        Reads until the protocol's terminator character is received and
        parses the raw bytes using :attr:`protocol`.

        Returns:
            (str):
                Parsed response string.

        Raises:
            ConnectionError:
                If the transport is not open.
            TimeoutError:
                If no data is received within the transport timeout.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> t = NullTransport(responses=[b"+1.234\\n"])
            >>> instr = BaseInstrument(t, ScpiProtocol())
            >>> instr.connect()
            >>> instr.read()
            '+1.234'
            >>> instr.disconnect()
        """
        terminator = getattr(self.protocol, "terminator", b"\n")
        raw = self.transport.read_until(terminator)
        return self.protocol.parse_response(raw)

    def query(self, command: str) -> str:
        """Send a query and return the instrument's response.

        Combines :meth:`write` and :meth:`read` into a single call.
        The query is formatted by :attr:`protocol` before transmission.

        Args:
            command (str):
                Query string in the instrument's command language.

        Returns:
            (str):
                Parsed response string.

        Raises:
            ConnectionError:
                If the transport is not open.
            TimeoutError:
                If no response is received within the transport timeout.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> t = NullTransport(responses=[b"ACME,1,SN,v1\\n"])
            >>> instr = BaseInstrument(t, ScpiProtocol())
            >>> instr.connect()
            >>> instr.query("*IDN?")
            'ACME,1,SN,v1'
            >>> instr.disconnect()
        """
        self.transport.write(self.protocol.format_query(command))
        return self.read()

    def identify(self) -> str:
        """Return the instrument identification string (``*IDN?``).

        Sends the standard IEEE 488.2 ``*IDN?`` query and returns the
        response.  Instruments that do not support ``*IDN?`` should override
        this method.

        Returns:
            (str):
                Identification string returned by the instrument.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> t = NullTransport(responses=[b"ACME,Model1,SN001,v1.0\\n"])
            >>> instr = BaseInstrument(t, ScpiProtocol())
            >>> instr.connect()
            >>> instr.identify()
            'ACME,Model1,SN001,v1.0'
            >>> instr.disconnect()
        """
        return self.query("*IDN?")

    def reset(self) -> None:
        """Send the standard IEEE 488.2 reset command (``*RST``).

        Instruments that do not support ``*RST`` should override this method.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> t = NullTransport()
            >>> instr = BaseInstrument(t, ScpiProtocol())
            >>> instr.connect()
            >>> instr.reset()
            >>> t.write_log
            [b'*RST\\n']
            >>> instr.disconnect()
        """
        self.write("*RST")

    def __enter__(self) -> BaseInstrument:
        """Open the connection and return ``self`` for use as a context manager.

        Returns:
            (BaseInstrument):
                This instrument instance.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> with BaseInstrument(NullTransport(), ScpiProtocol()) as instr:
            ...     instr.is_connected
            True
        """
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        """Close the connection when leaving a ``with`` block."""
        self.disconnect()
