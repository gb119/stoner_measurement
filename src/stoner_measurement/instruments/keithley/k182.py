"""Keithley Model 182 legacy IEEE-488 nanovoltmeter driver."""

from __future__ import annotations

import enum
import math
import re
from dataclasses import dataclass

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.nanovoltmeter import (
    Nanovoltmeter,
    NanovoltmeterCapabilities,
    NanovoltmeterFunction,
    NanovoltmeterTriggerSource,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.transport.base import BaseTransport


class Keithley182Protocol(BaseProtocol):
    """Unterminated one-letter command protocol used by the Model 182."""

    terminator = b"\r\n"
    # F2 can return many CR/LF-framed readings in one response. Rely on GPIB
    # EOI for the complete block instead of letting VISA stop after the first.
    gpib_terminator = None
    max_frame_size = 65536
    # The driver reads U1 synchronously so it can preserve detailed error
    # context; do not let the transport turn the serial-poll error bit into a
    # generic exception before that response is read.
    status_error_mask = None
    gpib_use_mav = False

    def format_command(self, command: str) -> bytes:
        """Encode a command exactly; GPIB EOI terminates the message."""
        return command.encode("ascii")

    def format_query(self, query: str) -> bytes:
        """Format a talk-selecting command without SCPI punctuation."""
        return self.format_command(query)

    def parse_response(self, raw: bytes, *, command: str | None = None) -> str:
        """Decode ASCII and remove only the configured response terminator."""
        _ = command
        return raw.decode("ascii", errors="strict").rstrip("\r\n")


class Keithley182FilterResponse(enum.Enum):
    """Model 182 digital-filter response selection."""

    OFF = "OFF"
    FAST = "FAST"
    MEDIUM = "MEDIUM"
    SLOW = "SLOW"


@dataclass(frozen=True)
class Keithley182Reading:
    """Parsed Model 182 reading with optional buffer metadata."""

    value: float
    prefix: str | None = None
    location: int | None = None
    timestamp: float | None = None


_READING_RE = re.compile(
    r"^\s*(?P<prefix>(?:[NRO](?:DCV|MAX|MIN))|(?:NMAX|NMIN))?"
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)"
    r"(?:\s*,\s*(?P<location>\d+))?"
    r"(?:\s*,\s*(?P<timestamp>[+-]?(?:\d+(?:\.\d*)?|\.\d+)))?\s*$"
)

_ERROR_BITS: dict[int, str] = {
    0: "invalid command",
    1: "invalid option",
    2: "invalid format",
    3: "not in remote",
    4: "trigger overrun",
    5: "measurement overflow",
    6: "NVRAM failure",
    7: "RAM failure",
    8: "instrument is uncalibrated",
    9: "calibration running",
    10: "calibration locked",
    11: "calibration error",
    14: "front-panel communication failure",
    15: "A/D communication failure",
    16: "trigger not ready",
}

_RANGE_COMMANDS = {
    0.003: "R1",
    0.03: "R2",
    0.3: "R3",
    3.0: "R4",
    30.0: "R5",
}
_RANGE_VALUES = {int(command[1:]): value for value, command in _RANGE_COMMANDS.items()}
_DIGIT_COMMANDS = {5: "B0", 6: "B1", 3: "B2", 4: "B3"}
_INTEGRATION_COMMANDS = {1.0: "S0", 0.15: "S1", 5.0: "S2"}
_INTEGRATION_VALUES = {int(command[1:]): value for value, command in _INTEGRATION_COMMANDS.items()}
_FILTER_COMMANDS = {
    Keithley182FilterResponse.OFF: "P0",
    Keithley182FilterResponse.FAST: "P1",
    Keithley182FilterResponse.MEDIUM: "P2",
    Keithley182FilterResponse.SLOW: "P3",
}


class Keithley182(Nanovoltmeter):
    """Concrete driver for the non-SCPI Keithley Model 182 nanovoltmeter."""

    DISPLAY_NAME = "Keithley 182"
    _MODEL = "182"
    CAPABILITIES = NanovoltmeterCapabilities(
        has_filter=True,
        has_trigger=True,
        has_buffer=True,
        supported_functions=(NanovoltmeterFunction.VOLT,),
        fixed_voltage_ranges=tuple(_RANGE_COMMANDS),
        nplc_values=(0.15, 1.0, 5.0),
        digit_values=tuple(sorted(_DIGIT_COMMANDS)),
        filter_types=tuple(response.name for response in Keithley182FilterResponse),
        default_nplc=1.0,
        default_digits=6,
        default_filter_type="OFF",
        supports_analog_filter=True,
        supports_relative=True,
        supports_safe_reset=False,
        relative_limits=(-30.0, 30.0),
        max_buffer_points=1024,
    )

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise cached state without sending any device-clear commands."""
        super().__init__(transport, protocol or Keithley182Protocol())
        self.auto_check_errors = False
        self._machine_status: str | None = None
        self._trigger_source = NanovoltmeterTriggerSource.EXT
        self._trigger_count = 1
        self._buffer_size = 1
        self._relative_value = 0.0

    @staticmethod
    def _build_command(*commands: str) -> str:
        """Validate and concatenate command fragments with one final ``X``."""
        fragments: list[str] = []
        for command in commands:
            token = command.strip()
            if not token or any(char.isspace() for char in token):
                raise ValueError(f"Invalid Model 182 command fragment: {command!r}")
            if "X" in token.upper():
                raise ValueError("Command fragments must not contain the execution delimiter X.")
            token.encode("ascii")
            fragments.append(token)
        if not fragments:
            raise ValueError("At least one Model 182 command fragment is required.")
        return "".join(fragments) + "X"

    @staticmethod
    def _format_finite(value: float) -> str:
        """Return a finite value in a compact instrument-safe form."""
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Model 182 numeric values must be finite.")
        return f"{number:.12g}"

    def _query_status(self, selector: int) -> str:
        """Read one alternate-output status word (U0 through U14)."""
        if not 0 <= selector <= 14:
            raise ValueError("Status selector must be in the range 0..14.")
        return self.query(self._build_command(f"U{selector}"))

    def _check_errors(self, *, command: str | None = None) -> None:
        """Read, decode, and clear the Model 182 U1 error word."""
        response = self._query_status(1).strip()
        if not response.startswith("ERR"):
            raise InstrumentError(
                f"Malformed Keithley 182 error status {response!r}", command=command
            )
        bits = response[3:]
        if len(bits) < 17 or any(bit not in "01" for bit in bits):
            raise InstrumentError(
                f"Malformed Keithley 182 error status {response!r}", command=command
            )
        errors = [message for bit, message in _ERROR_BITS.items() if bits[bit] == "1"]
        if errors:
            raise InstrumentError(
                f"Keithley 182 reported: {', '.join(errors)}; status={response}",
                command=command,
            )

    def _send_config(self, *commands: str) -> None:
        """Send validated configuration and synchronously check U1."""
        payload = self._build_command(*commands)
        self.write(payload)
        self._check_errors(command=payload)

    def _talk(self, *commands: str) -> str:
        """Select output, execute, perform the talk transaction, then check U1."""
        payload = self._build_command(*commands)
        response = self.query(payload)
        self._check_errors(command=payload)
        return response

    def connect(self) -> None:
        """Open GPIB and verify communication without clearing or calibrating."""
        super().connect()
        try:
            self._machine_status = self._query_status(0)
            if not self._machine_status.startswith("182"):
                raise InstrumentError(
                    f"Unexpected instrument status {self._machine_status!r}; expected Model 182."
                )
            self._check_errors(command="connect")
        except Exception:
            self.disconnect()
            raise

    def identify(self) -> str:
        """Identify the instrument from its U0 machine-status word."""
        status = self._machine_status or self._query_status(0)
        return status[:3]

    def confirm_identity(self) -> str:
        """Confirm that the U0 status word identifies a Model 182."""
        identity = self.identify()
        if identity != self._MODEL:
            raise InstrumentError(f"Unexpected instrument identity {identity!r}; expected '182'.")
        return identity

    def reset(self) -> None:
        """Refuse implicit reset because Model 182 reset requires destructive DCL/SDC."""
        raise NotImplementedError(
            "Keithley 182 reset requires an explicit IEEE-488 device clear and is not "
            "performed by the measurement driver."
        )

    @staticmethod
    def parse_reading(response: str) -> Keithley182Reading:
        """Parse numeric, prefixed, and metadata-bearing Model 182 readings."""
        match = _READING_RE.fullmatch(response)
        if match is None:
            raise InstrumentError(f"Malformed Keithley 182 reading {response!r}.")
        prefix = match.group("prefix")
        if prefix is not None and prefix.startswith("O"):
            raise InstrumentError(f"Keithley 182 measurement overflow: {response!r}.")
        value = float(match.group("value"))
        if not math.isfinite(value):
            raise InstrumentError(f"Non-finite Keithley 182 reading {response!r}.")
        location = match.group("location")
        timestamp = match.group("timestamp")
        return Keithley182Reading(
            value=value,
            prefix=prefix,
            location=int(location) if location is not None else None,
            timestamp=float(timestamp) if timestamp is not None else None,
        )

    def measure_voltage(self) -> float:
        """Take one numeric voltage reading using one-shot-on-talk triggering."""
        return self.parse_reading(self._talk("F0", "G0", "T1")).value

    def _status_option(self, letter: str, width: int = 1) -> int:
        """Return one numeric field from the U0 machine status word."""
        status = self._query_status(0)
        match = re.search(rf"{re.escape(letter)}(\d{{{width}}})", status)
        if match is None:
            raise InstrumentError(f"Malformed Keithley 182 machine status {status!r}.")
        return int(match.group(1))

    def get_range(self) -> float:
        """Read the active range, returning 0.0 for autorange."""
        option = self._status_option("R")
        return 0.0 if option == 0 else _RANGE_VALUES[option]

    def set_range(self, value: float) -> None:
        """Select one of the five fixed full-scale voltage ranges."""
        number = float(value)
        command = next(
            (cmd for limit, cmd in _RANGE_COMMANDS.items() if math.isclose(number, limit)),
            None,
        )
        if command is None:
            raise ValueError(f"Unsupported Keithley 182 range {value!r}.")
        self._send_config(command)

    def get_autorange(self) -> bool:
        """Return whether U0 reports automatic ranging."""
        return self._status_option("R") == 0

    def set_autorange(self, state: bool) -> None:
        """Enable autorange or retain the current fixed range."""
        self._send_config("R0" if state else "R8")

    def get_nplc(self) -> float:
        """Return the constrained 50-Hz NPLC-equivalent integration value."""
        return _INTEGRATION_VALUES[self._status_option("S")]

    def set_nplc(self, value: float) -> None:
        """Set 3 ms (0.15 PLC), line-cycle (1 PLC), or 100 ms (5 PLC)."""
        number = float(value)
        command = next(
            (cmd for nplc, cmd in _INTEGRATION_COMMANDS.items() if math.isclose(number, nplc)),
            None,
        )
        if command is None:
            raise ValueError("Keithley 182 NPLC must be one of 0.15, 1.0, or 5.0.")
        self._send_config(command)

    def set_digits(self, digits: int) -> None:
        """Select one of the supported 3.5 through 6.5 digit resolutions."""
        try:
            command = _DIGIT_COMMANDS[digits]
        except KeyError as exc:
            raise ValueError("Keithley 182 digits must be one of 3, 4, 5, or 6.") from exc
        self._send_config(command)

    def get_measure_function(self) -> NanovoltmeterFunction:
        """Return the only supported measurement function."""
        return NanovoltmeterFunction.VOLT

    def set_measure_function(self, function: NanovoltmeterFunction) -> None:
        """Accept voltage measurement and reject unsupported functions."""
        if function is not NanovoltmeterFunction.VOLT:
            raise ValueError("Keithley 182 supports voltage measurement only.")

    def get_filter_enabled(self) -> bool:
        """Return the U0 master filter-enable state."""
        return bool(self._status_option("N"))

    def set_filter_enabled(self, state: bool) -> None:
        """Enable or disable the master analogue/digital filter gate."""
        self._send_config("N1" if state else "N0")

    def get_filter_count(self) -> int:
        """Reject filter-count access because the Model 182 uses response modes."""
        raise NotImplementedError("Keithley 182 has filter response modes, not a filter count.")

    def set_filter_count(self, count: int) -> None:
        """Reject filter counts; use :meth:`set_filter_type` instead."""
        _ = count
        raise NotImplementedError("Keithley 182 has filter response modes, not a filter count.")

    def set_filter_type(self, filter_type: str) -> None:
        """Select off, fast, medium, or slow digital-filter response."""
        try:
            response = Keithley182FilterResponse(filter_type.strip().upper())
        except ValueError as exc:
            raise ValueError(
                "Keithley 182 filter type must be OFF, FAST, MEDIUM, or SLOW."
            ) from exc
        self._send_config(_FILTER_COMMANDS[response])

    def set_analog_filter_enabled(self, state: bool) -> None:
        """Configure the analogue filter behind the master filter gate."""
        self._send_config("O1" if state else "O0")

    def set_relative_value(self, value: float) -> None:
        """Program an explicit reading-relative baseline in volts."""
        number = float(value)
        if abs(number) > 30.0:
            raise ValueError("Keithley 182 relative value must be within -30..30 V.")
        self._relative_value = number
        self._send_config(f"Z2,{self._format_finite(number)}")

    def get_relative_value(self) -> float:
        """Query the reading-relative baseline with U6."""
        response = self._query_status(6)
        if not response.startswith("MRL"):
            raise InstrumentError(f"Malformed Keithley 182 relative status {response!r}.")
        return self.parse_reading(response[3:]).value

    def set_relative_enabled(self, state: bool) -> None:
        """Enable the programmed baseline or disable reading-relative mode."""
        self._send_config("Z3" if state else "Z0")

    def set_trigger_delay(self, delay: float) -> None:
        """Set one-shot trigger delay in seconds."""
        number = float(delay)
        if number == 0.0:
            self._send_config("W0")
            return
        if not 0.001 <= number <= 999.999:
            raise ValueError("Keithley 182 trigger delay must be 0 or 0.001..999.999 s.")
        self._send_config(f"W{self._format_finite(number)}")

    def set_line_sync_enabled(self, state: bool) -> None:
        """Reject independent line sync; select line-cycle integration instead."""
        _ = state
        raise NotImplementedError(
            "Keithley 182 has no independent line-sync setting; use 1 PLC integration."
        )

    def set_autozero_enabled(self, state: bool) -> None:
        """Reject unsupported automatic-zero configuration."""
        _ = state
        raise NotImplementedError("Keithley 182 has no configurable autozero mode.")

    def get_trigger_source(self) -> NanovoltmeterTriggerSource:
        """Return the cached generic trigger-source selection."""
        return self._trigger_source

    def _trigger_command(self) -> str:
        """Map the generic trigger source and count onto a Model 182 T command."""
        multiple = self._trigger_count > 1
        options = {
            NanovoltmeterTriggerSource.IMM: ("T5", "T4"),
            NanovoltmeterTriggerSource.BUS: ("T3", "T2"),
            NanovoltmeterTriggerSource.EXT: ("T7", "T6"),
            NanovoltmeterTriggerSource.TIM: ("T1", "T0"),
            NanovoltmeterTriggerSource.MAN: ("T9", "T8"),
        }
        return options[self._trigger_source][1 if multiple else 0]

    def set_trigger_source(self, source: NanovoltmeterTriggerSource) -> None:
        """Select the generic trigger source using one-shot/multiple state."""
        self._trigger_source = source
        self._send_config(self._trigger_command())

    def get_trigger_count(self) -> int:
        """Return the configured acquisition count."""
        return self._trigger_count

    def set_trigger_count(self, count: int) -> None:
        """Select one-shot for one point or multiple mode for several points."""
        if count <= 0:
            raise ValueError("Trigger count must be positive.")
        self._trigger_count = count
        self._send_config(self._trigger_command())

    def initiate(self) -> None:
        """Arm the selected trigger mode without generating a software trigger."""
        self._send_config(self._trigger_command())

    def abort(self) -> None:
        """Disable all Model 182 triggers."""
        self._send_config("T10")

    def clear_buffer(self) -> None:
        """Disable the buffer before reconfiguration."""
        self._send_config("I0")

    def get_buffer_count(self) -> int:
        """Return the programmed buffer length reported by U3."""
        response = self._query_status(3)
        if not response.startswith("LEN"):
            raise InstrumentError(f"Malformed Keithley 182 buffer status {response!r}.")
        return int(response[3:])

    def set_buffer_size(self, size: int) -> None:
        """Configure a 1..1024 point linear buffer."""
        if not 1 <= size <= 1024:
            raise ValueError("Keithley 182 linear buffer size must be in the range 1..1024.")
        self._buffer_size = size
        self._send_config(f"I1,{size}")

    def set_buffer_feed_sense(self) -> None:
        """Select A/D readings as the talk source; storage is controlled by I1."""
        self._send_config("F0")

    def set_buffer_feed_continuous_next(self) -> None:
        """Re-arm the configured linear buffer without changing its size."""
        self._send_config(f"I1,{self._buffer_size}")

    def read_buffer(self, count: int | None = None) -> tuple[float, ...]:
        """Read all buffered voltages with F2/G0 and optionally limit the result."""
        if count is not None and count <= 0:
            raise ValueError("count must be a positive integer.")
        response = self._talk("F2", "G0")
        tokens = [token for token in re.split(r"[\r\n,]+", response) if token.strip()]
        readings = tuple(self.parse_reading(token).value for token in tokens)
        return readings if count is None else readings[:count]

    def get_capabilities(self) -> NanovoltmeterCapabilities:
        """Describe the safe generic capabilities implemented by this driver."""
        return self.CAPABILITIES


__all__ = [
    "Keithley182",
    "Keithley182FilterResponse",
    "Keithley182Protocol",
    "Keithley182Reading",
]
