"""Base instrument class providing the composition of transport and protocol.

:class:`BaseInstrument` is the foundation of the instrument hierarchy.  Every
concrete instrument class is a (possibly indirect) subclass of
:class:`BaseInstrument` and gains the ability to communicate with a physical
instrument by holding references to a :class:`BaseTransport` and a
:class:`BaseProtocol` instance.
"""

from __future__ import annotations

import logging
from abc import ABC
from typing import TYPE_CHECKING

from stoner_measurement.instruments.errors import InstrumentError

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport

_COMMS_LOGGER_NAMESPACE = "stoner_measurement.sequence.comms"


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
            to ``True``.

    Examples:
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import ScpiProtocol
        >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
        >>> # Second response is consumed by automatic SYST:ERR? polling.
        >>> t = NullTransport(
        ...     responses=[b"ACME,Model1,SN001,v1.0\\n", b'+0,"No error"\\n']
        ... )
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
        auto_check_errors: bool = True,
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
                ``True``.
        """
        self.transport = transport
        self.protocol = protocol
        self.auto_check_errors = auto_check_errors
        self._comms_logger = logging.getLogger(
            f"{_COMMS_LOGGER_NAMESPACE}.{self.__class__.__name__}"
        )

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
        payload = self.protocol.format_command(command)
        self.transport.write(payload)
        self._log_comms_traffic("TX", payload)
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
        self._log_comms_traffic("RX", raw)
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
        payload = self.protocol.format_query(command)
        self.transport.write(payload)
        self._log_comms_traffic("TX", payload)
        response = self.read()
        if self.auto_check_errors:
            if self.protocol.errors_in_response:
                try:
                    self.protocol.check_error(response, command=command)
                except InstrumentError:
                    self._comms_logger.error(
                        "Instrument reported error during query %r: %s",
                        command,
                        response,
                    )
                    raise
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

        response = self._query_error_queue_once()
        try:
            self.protocol.check_error(response, command=command)
        except InstrumentError:
            self._comms_logger.error(
                "Instrument reported command error after %r: %s",
                command,
                response,
            )
            self._clear_error_queue()
            raise

    def _query_error_queue_once(self) -> str:
        """Return one parsed response from the protocol error query.

        Returns:
            (str):
                Parsed response payload from one error-queue poll, or an
                empty string when the active protocol has no error query.
        """
        error_query = self.protocol.error_query
        if error_query is None:
            return ""
        payload = self.protocol.format_query(error_query)
        self.transport.write(payload)
        self._log_comms_traffic("TX", payload)
        terminator = getattr(self.protocol, "terminator", b"\n")
        raw = self.transport.read_until(terminator)
        self._log_comms_traffic("RX", raw)
        return self.protocol.parse_response(raw)

    def _clear_error_queue(self, *, max_entries: int = 16) -> None:
        """Drain protocol error queue entries, logging each cleared error.

        Keyword Parameters:
            max_entries (int):
                Maximum number of queued entries to consume before stopping.
                Defaults to ``16`` to prevent unbounded loops if an
                instrument repeatedly reports fresh errors.
        """
        if self.protocol.errors_in_response or self.protocol.error_query is None:
            return
        for _ in range(max_entries):
            response = self._query_error_queue_once()
            if response.strip() == "":
                break
            try:
                self.protocol.check_error(response, command=None)
            except InstrumentError as exc:
                self._comms_logger.error("Cleared queued instrument error: %s", exc)
                continue
            break

    def confirm_identity(self) -> str:
        """Query and validate the identity string against expected tokens.

        Returns:
            (str):
                The validated identity string, or an empty string when no
                expected tokens are configured for this driver.

        Raises:
            InstrumentError:
                If configured expected identity tokens are missing from the
                instrument identity response.
        """
        tokens = tuple(getattr(self, "_EXPECTED_IDENTITY_TOKENS", ()))
        if not tokens and hasattr(self, "_MODEL"):
            model = getattr(self, "_MODEL")
            if model:
                tokens = (str(model),)
        if not tokens:
            return ""

        identity = self.identify()
        identity_upper = identity.upper()
        if not all(str(token).upper() in identity_upper for token in tokens):
            expected = ", ".join(str(token) for token in tokens)
            message = (
                f"Unexpected instrument identity {identity!r}; "
                f"expected token(s): {expected}."
            )
            self._comms_logger.error(message)
            raise InstrumentError(message)
        return identity

    def _log_comms_traffic(self, direction: str, payload: bytes) -> None:
        """Emit a transcript log entry for one instrument I/O event.

        Args:
            direction (str):
                Traffic direction token: ``"TX"`` for transmitted bytes or
                ``"RX"`` for received bytes.
            payload (bytes):
                Raw payload bytes sent to or received from the instrument.

        Notes:
            ``errors='backslashreplace'`` is used when decoding *payload* so
            that instruments which send non-UTF-8 binary frames (e.g. raw
            IEEE 488.2 binary block data) are still represented as printable
            text in the log rather than causing a ``UnicodeDecodeError``.
        """
        decoded_payload = payload.decode(
            "utf-8",
            errors="backslashreplace",
        ).rstrip("\r\n")
        self._comms_logger.debug(
            "%s %s",
            direction,
            decoded_payload,
            extra={
                "sm_traffic_channel": "instrument_comms",
                "sm_traffic_direction": direction,
                "sm_transport_address": self.transport.transport_address,
            },
        )

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
