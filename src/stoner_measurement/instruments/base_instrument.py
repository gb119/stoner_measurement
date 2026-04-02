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

    Error checking is performed on demand via :meth:`check_for_errors` and
    can be enabled automatically for every :meth:`write` and :meth:`query`
    call by setting :attr:`auto_check_errors` to ``True``.

    Two strategies are supported transparently, chosen based on the protocol:

    * **Response-embedded** (Oxford, Lakeshore) — :meth:`check_for_errors`
      inspects the last query response for an inline error token.
    * **Error-queue** (SCPI) — :meth:`check_for_errors` polls the
      instrument's error queue.  If the transport supports an out-of-band
      status byte (:meth:`~stoner_measurement.instruments.transport.base.BaseTransport.read_status_byte`,
      e.g. GPIB serial poll), only the ESB bit is checked first to avoid an unnecessary
      round-trip when no error is pending.

    Attributes:
        transport (BaseTransport):
            Transport layer instance (serial, Ethernet, GPIB, …).
        protocol (BaseProtocol):
            Protocol instance (SCPI, Oxford, Lakeshore, …).
        auto_check_errors (bool):
            When ``True``, :meth:`write` and :meth:`query` automatically
            call :meth:`check_for_errors` after each operation.  Defaults
            to ``False``.

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
        *,
        auto_check_errors: bool = False,
    ) -> None:
        """Initialise the instrument with a transport and protocol.

        Args:
            transport (BaseTransport):
                Transport layer responsible for byte-level I/O.
            protocol (BaseProtocol):
                Protocol responsible for formatting commands and parsing
                responses.

        Keyword Parameters:
            auto_check_errors (bool):
                When ``True``, automatically call :meth:`check_for_errors`
                after every :meth:`write` and :meth:`query`.  Defaults to
                ``False``.
        """
        self.transport = transport
        self.protocol = protocol
        self.auto_check_errors = auto_check_errors

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
        :attr:`transport`.  If :attr:`auto_check_errors` is ``True`` and the
        protocol uses an error queue (not response-embedded errors),
        :meth:`check_for_errors` is called after the command is sent.

        Args:
            command (str):
                Command string in the instrument's command language.

        Raises:
            ConnectionError:
                If the transport is not open.
            InstrumentError:
                If :attr:`auto_check_errors` is ``True`` and the instrument
                reports an error after processing the command.

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
        if self.auto_check_errors and not self.protocol.errors_in_response:
            self.check_for_errors(command=command)

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

        If :attr:`auto_check_errors` is ``True``:

        * For protocols with response-embedded errors (Oxford, Lakeshore),
          :meth:`~BaseProtocol.check_error` is called on the parsed response
          directly.
        * For error-queue protocols (SCPI), :meth:`check_for_errors` is called
          after the response is returned.

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
            InstrumentError:
                If :attr:`auto_check_errors` is ``True`` and the instrument
                signals an error.

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
        response = self.read()
        if self.auto_check_errors:
            if self.protocol.errors_in_response:
                self.protocol.check_error(response, command=command)
            else:
                self.check_for_errors(command=command)
        return response

    def check_for_errors(self, *, command: str | None = None) -> None:
        """Poll the instrument for errors and raise if one is found.

        The strategy depends on the protocol and transport combination:

        1. If the protocol uses response-embedded errors
           (:attr:`~BaseProtocol.errors_in_response` is ``True``), this
           method is a no-op — errors are detected inline by :meth:`query`.

        2. If the transport supports an out-of-band status byte
           (:meth:`~stoner_measurement.instruments.transport.base.BaseTransport.read_status_byte`
           returns a non-``None`` value), the IEEE 488.2 Event Status Bit (ESB, bit 2) is checked.
           If it is clear, no error query is sent.

        3. Otherwise (or if the ESB bit is set) the protocol's
           :attr:`~BaseProtocol.error_query` command is sent and
           :meth:`~BaseProtocol.check_error` is called on the response.

        Keyword Parameters:
            command (str | None):
                The command that preceded this check, used to populate the
                :attr:`~InstrumentError.command` field of any raised
                exception.  Defaults to ``None``.

        Raises:
            InstrumentError:
                If the instrument reports an error.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> t = NullTransport(responses=[b'+0,"No error"\\n'])
            >>> instr = BaseInstrument(t, ScpiProtocol())
            >>> instr.connect()
            >>> instr.check_for_errors()   # no exception — queue is clear
            >>> instr.disconnect()
        """
        if self.protocol.errors_in_response or self.protocol.error_query is None:
            return

        # If the transport can provide an out-of-band status byte (e.g. GPIB
        # serial poll), check the ESB bit first to avoid an unnecessary query.
        stb = self.transport.read_status_byte()
        if stb is not None and not (stb & _IEEE488_ESB_BIT):
            return

        # Query the instrument's error queue.
        error_query = self.protocol.error_query
        self.transport.write(self.protocol.format_query(error_query))
        terminator = getattr(self.protocol, "terminator", b"\n")
        raw = self.transport.read_until(terminator)
        response = self.protocol.parse_response(raw)
        self.protocol.check_error(response, command=command)

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


#: IEEE 488.2 Event Status Bit (ESB) — bit 2 of the status byte.
#: When this bit is set the Event Status Register contains at least one
#: enabled event (e.g. command error, execution error).
_IEEE488_ESB_BIT: int = 0x04
