"""SIGNAL RECOVERY 7265 DSP lock-in amplifier driver."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum, IntFlag
from math import ceil, isclose
from time import perf_counter, sleep

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.lockin_amplifier import (
    LockInAmplifier,
    LockInAmplifierCapabilities,
    LockInInputCoupling,
    LockInInputShielding,
    LockInInputSource,
    LockInLineFilter,
    LockInOutput,
    LockinRefenceEdge,
    LockInReferenceSource,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.signal_recovery import (
    SignalRecoveryPromptError,
    SignalRecoveryProtocol,
)
from stoner_measurement.instruments.transport.base import BaseTransport
from stoner_measurement.instruments.transport.null_transport import NullTransport
from stoner_measurement.instruments.transport.serial_transport import EchoSerialTransport


class SR7265Status(IntFlag):
    """Bits in the 7265 serial-poll status byte or ``ST`` response."""

    NONE = 0
    COMMAND_COMPLETE = 1 << 0
    INVALID_COMMAND = 1 << 1
    PARAMETER_ERROR = 1 << 2
    REFERENCE_UNLOCK = 1 << 3
    OVERLOAD = 1 << 4
    NEW_ADC_VALUES = 1 << 5
    SERVICE_REQUEST = 1 << 6
    DATA_AVAILABLE = 1 << 7

    @property
    def has_command_error(self) -> bool:
        """Return whether the command or one of its parameters was rejected."""
        return bool(self & (self.INVALID_COMMAND | self.PARAMETER_ERROR))

    @property
    def has_measurement_error(self) -> bool:
        """Return whether reference unlock or overload makes data suspect."""
        return bool(self & (self.REFERENCE_UNLOCK | self.OVERLOAD))


class SR7265ReferenceInput(Enum):
    """Native reference-input choices supported by the 7265 ``IE`` command."""

    INTERNAL = 0
    EXTERNAL_TTL = 1
    EXTERNAL_ANALOG = 2


class SR7265Error(InstrumentError):
    """Structured 7265 command or measurement-status error."""

    def __init__(
        self,
        message: str,
        *,
        command: str | None = None,
        status: SR7265Status = SR7265Status.NONE,
        overload: int | None = None,
    ) -> None:
        self.status = status
        self.overload = overload
        details = [message, f"status=0x{int(status):02X}"]
        if overload is not None:
            details.append(f"overload=0x{overload:02X}")
        super().__init__(", ".join(details), command=command, error_code=int(status))


class SR7265(LockInAmplifier):
    """Concrete driver for the SIGNAL RECOVERY model 7265.

    The driver uses native 7265 commands rather than emitting SR830 SCPI.  It
    serial-polls transports that provide an out-of-band status byte and stores
    every resulting status in :attr:`last_status`.  For RS-232, use
    :class:`~stoner_measurement.instruments.transport.EchoSerialTransport`
    with ``response_suffixes=(b"*", b"?")``.
    """

    DISPLAY_NAME = "SIGNAL RECOVERY 7265"
    _EXPECTED_IDENTITY_TOKENS = ("7265",)
    _MAX_HARMONIC = 65535
    _FILTER_SLOPES = (6, 12, 18, 24)
    _VOLTAGE_SENSITIVITIES = (
        2e-9,
        5e-9,
        10e-9,
        20e-9,
        50e-9,
        100e-9,
        200e-9,
        500e-9,
        1e-6,
        2e-6,
        5e-6,
        10e-6,
        20e-6,
        50e-6,
        100e-6,
        200e-6,
        500e-6,
        1e-3,
        2e-3,
        5e-3,
        10e-3,
        20e-3,
        50e-3,
        100e-3,
        200e-3,
        500e-3,
        1.0,
    )
    _WIDE_CURRENT_SENSITIVITIES = tuple(value * 1e-6 for value in _VOLTAGE_SENSITIVITIES)
    _LOW_NOISE_CURRENT_SENSITIVITIES = (
        2e-15,
        5e-15,
        10e-15,
        20e-15,
        50e-15,
        100e-15,
        200e-15,
        500e-15,
        1e-12,
        2e-12,
        5e-12,
        10e-12,
        20e-12,
        50e-12,
        100e-12,
        200e-12,
        500e-12,
        1e-9,
        2e-9,
        5e-9,
        10e-9,
    )
    _TIME_CONSTANTS = (
        10e-6,
        20e-6,
        40e-6,
        80e-6,
        160e-6,
        320e-6,
        640e-6,
        5e-3,
        10e-3,
        20e-3,
        50e-3,
        100e-3,
        200e-3,
        500e-3,
        1.0,
        2.0,
        5.0,
        10.0,
        20.0,
        50.0,
        100.0,
        200.0,
        500.0,
        1e3,
        2e3,
        5e3,
        10e3,
        20e3,
        50e3,
        100e3,
    )
    _OUTPUT_COMMANDS = {
        LockInOutput.X: "X.",
        LockInOutput.Y: "Y.",
        LockInOutput.R: "MAG.",
        LockInOutput.THETA: "PHA.",
    }

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
        *,
        response_delimiter: str = ",",
    ) -> None:
        """Initialise a 7265 with CR/LF framing and a configurable delimiter."""
        if len(response_delimiter) != 1 or not response_delimiter.isprintable():
            raise ValueError("Response delimiter must be one printable character.")
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else SignalRecoveryProtocol(),
        )
        self.response_delimiter = response_delimiter
        self._last_status = SR7265Status.NONE
        self._time_constant: float | None = None

    @property
    def last_status(self) -> SR7265Status:
        """Return the last serial-poll or queried status value."""
        return self._last_status

    @classmethod
    def supported_time_constants(cls) -> tuple[float, ...]:
        """Return supported output time constants in seconds."""
        return cls._TIME_CONSTANTS

    @classmethod
    def supported_sensitivities(
        cls, source: LockInInputSource = LockInInputSource.A
    ) -> tuple[float, ...]:
        """Return full-scale sensitivities in the selected input's physical units."""
        if source is LockInInputSource.I_1MOHM:
            return cls._WIDE_CURRENT_SENSITIVITIES
        if source is LockInInputSource.I_100MOHM:
            return cls._LOW_NOISE_CURRENT_SENSITIVITIES
        return cls._VOLTAGE_SENSITIVITIES

    @classmethod
    def supported_filter_slopes(cls) -> tuple[int, ...]:
        """Return supported output-filter slopes in dB/octave."""
        return cls._FILTER_SLOPES

    @classmethod
    def max_harmonic(cls) -> int:
        """Return the maximum reference harmonic."""
        return cls._MAX_HARMONIC

    @staticmethod
    def _encode_index(value: float, values: tuple[float, ...], name: str) -> int:
        try:
            return values.index(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be one of {values!r}.") from exc

    @staticmethod
    def _decode_index(code: int, values: tuple[float, ...], name: str) -> float:
        if not 0 <= code < len(values):
            raise ValueError(f"{name} code {code} is out of range.")
        return values[code]

    def _parse_values(self, response: str, expected: int | None = None) -> tuple[float, ...]:
        tokens = [token.strip() for token in response.split(self.response_delimiter)]
        if expected is not None and (len(tokens) != expected or "" in tokens):
            raise ValueError(f"Malformed {expected}-value 7265 response: {response!r}")
        try:
            return tuple(float(token) for token in tokens if token != "")
        except ValueError as exc:
            raise ValueError(f"Malformed numeric 7265 response: {response!r}") from exc

    def _poll_command_complete(self, command: str) -> SR7265Status | None:
        # NullTransport deliberately has no simulated command-progress state.
        if isinstance(self.transport, NullTransport):
            return None
        first = self.read_status_byte()
        if first is None:
            return None
        deadline = perf_counter() + max(0.0, self.transport.timeout)
        status = SR7265Status(first)
        while not status & SR7265Status.COMMAND_COMPLETE:
            if perf_counter() >= deadline:
                raise TimeoutError(
                    f"Timeout waiting for 7265 command completion after {command!r}; "
                    f"last status=0x{int(status):02X}."
                )
            sleep(0.01)
            status = SR7265Status(self.read_status_byte() or 0)
        self._last_status = status
        return status

    def _read_diagnostic_value(self, command: str) -> int | None:
        """Read a diagnostic without recursively checking its status."""
        try:
            self.transport.write(self.protocol.format_query(command))
            self._poll_command_complete(command)
            raw = self.transport.read()
            return int(float(self.protocol.parse_response(raw, command=command)))
        except (InstrumentError, TimeoutError, ValueError):
            return None

    def _parse_reply(self, raw: bytes, command: str) -> str:
        """Parse one reply and enrich an RS-232 error prompt with diagnostics."""
        try:
            return self.protocol.parse_response(raw, command=command)
        except SignalRecoveryPromptError as exc:
            diagnostic_status = self._read_diagnostic_value("ST")
            overload = self._read_diagnostic_value("N")
            parsed_status = SR7265Status(diagnostic_status or 0)
            self._last_status = parsed_status
            raise SR7265Error(
                "7265 returned its RS-232 error prompt",
                command=command,
                status=parsed_status,
                overload=overload,
            ) from exc

    def _raise_command_error(self, command: str, status: SR7265Status) -> None:
        if not status.has_command_error:
            return
        overload = self._read_diagnostic_value("N") if status & SR7265Status.OVERLOAD else None
        self._last_status = status
        labels = []
        if status & SR7265Status.INVALID_COMMAND:
            labels.append("invalid command")
        if status & SR7265Status.PARAMETER_ERROR:
            labels.append("command parameter error")
        raise SR7265Error(" and ".join(labels), command=command, status=status, overload=overload)

    def write(self, command: str, slow: int | None = None) -> None:
        """Send a native command and wait for its completion status."""
        with self._lock:
            self.transport.write(self.protocol.format_command(command), slow=slow)
            status = self._poll_command_complete(command)
            if status is not None:
                self._raise_command_error(command, status)
            elif isinstance(self.transport, EchoSerialTransport):
                self._parse_reply(self.transport.read(), command)

    def query(self, command: str, slow: int | None = None) -> str:
        """Send a native parameter-less query and return its response."""
        with self._lock:
            self.transport.write(self.protocol.format_query(command), slow=slow)
            status = self._poll_command_complete(command)
            if status is not None:
                self._raise_command_error(command, status)
            raw = self.transport.read()
            return self._parse_reply(raw, command)

    def identify(self) -> str:
        """Return the model identity from the native ``ID`` query."""
        return self.query("ID")

    def reset(self) -> None:
        """Restore instrument settings without changing communications settings."""
        self.write("ADF 1")

    def clear(self) -> None:
        """Report that the 7265 has no equivalent of the IEEE-488.2 clear command."""
        raise NotImplementedError("The 7265 has no command equivalent to *CLS.")

    def read_status(self) -> SR7265Status:
        """Read the status using a serial poll or the native ``ST`` query."""
        value = self.read_status_byte()
        if value is None or isinstance(self.transport, NullTransport):
            value = int(float(self.query("ST")))
        self._last_status = SR7265Status(value)
        return self._last_status

    def read_overload_status(self) -> int:
        """Return the native overload byte from ``N``."""
        return int(float(self.query("N")))

    def check_measurement_status(self, status: SR7265Status | None = None) -> None:
        """Raise when overload or reference unlock makes measurements suspect."""
        current = self._last_status if status is None else status
        if not current.has_measurement_error:
            return
        overload = self.read_overload_status() if current & SR7265Status.OVERLOAD else None
        self._last_status = current
        raise SR7265Error(
            "reference unlock or signal overload",
            status=current,
            overload=overload,
        )

    def measure_outputs(self, outputs: Iterable[LockInOutput]) -> dict[LockInOutput, float]:
        """Read selected outputs using a single compound command."""
        requested = tuple(dict.fromkeys(outputs))
        if not requested:
            raise ValueError("At least one output must be requested.")
        try:
            command = ";".join(self._OUTPUT_COMMANDS[output] for output in requested)
        except KeyError as exc:
            raise ValueError(f"Unsupported 7265 output: {exc.args[0]!r}") from exc
        values = self._parse_values(self.query(command), expected=len(requested))
        self.check_measurement_status()
        return dict(zip(requested, values, strict=True))

    def measure_xy(self) -> tuple[float, float]:
        """Measure simultaneous X and Y outputs in volts."""
        values = self.measure_outputs((LockInOutput.X, LockInOutput.Y))
        return values[LockInOutput.X], values[LockInOutput.Y]

    def measure_rt(self) -> tuple[float, float]:
        """Measure simultaneous magnitude in volts and phase in degrees."""
        values = self.measure_outputs((LockInOutput.R, LockInOutput.THETA))
        return values[LockInOutput.R], values[LockInOutput.THETA]

    def get_sensitivity(self) -> float:
        """Return voltage sensitivity, or current sensitivity in a current mode."""
        return float(self.query("SEN."))

    def set_sensitivity(self, value: float) -> None:
        """Set full-scale sensitivity in the active input mode's physical units."""
        source = self.get_input_source()
        values: tuple[float, ...]
        if source in (LockInInputSource.A, LockInInputSource.B, LockInInputSource.A_MINUS_B):
            values = self._VOLTAGE_SENSITIVITIES
            offset = 1
        elif source is LockInInputSource.I_1MOHM:
            values = self._WIDE_CURRENT_SENSITIVITIES
            offset = 1
        else:
            values = self._LOW_NOISE_CURRENT_SENSITIVITIES
            offset = 7
        code = self._encode_index(value, values, "Sensitivity") + offset
        self.write(f"SEN {code}")

    def get_time_constant(self) -> float:
        """Return the output-filter time constant in seconds."""
        return float(self.query("TC."))

    def set_time_constant(self, value: float) -> None:
        """Set a 1-2-5 sequence output-filter time constant in seconds."""
        code = self._encode_index(value, self._TIME_CONSTANTS, "Time constant")
        self.write(f"TC {code}")
        self._time_constant = value

    def get_reference_input(self) -> SR7265ReferenceInput:
        """Return the native internal, external TTL, or external analog input."""
        try:
            return SR7265ReferenceInput(int(float(self.query("IE"))))
        except ValueError as exc:
            raise ValueError("Unexpected 7265 reference-input code.") from exc

    def set_reference_input(self, source: SR7265ReferenceInput) -> None:
        """Select a native 7265 reference input."""
        self.write(f"IE {source.value}")

    def get_reference_source(self) -> tuple[LockInReferenceSource, LockinRefenceEdge]:
        """Return the shared lock-in reference representation."""
        native = self.get_reference_input()
        if native is SR7265ReferenceInput.INTERNAL:
            return LockInReferenceSource.INTERNAL, LockinRefenceEdge.FALLING
        edge = (
            LockinRefenceEdge.FALLING
            if native is SR7265ReferenceInput.EXTERNAL_TTL
            else LockinRefenceEdge.ZERO
        )
        return LockInReferenceSource.EXTERNAL, edge

    def set_reference_source(
        self,
        source: LockInReferenceSource,
        edge: LockinRefenceEdge = LockinRefenceEdge.ZERO,
    ) -> None:
        """Select internal reference or an external TTL/analog compatibility mode."""
        if source is LockInReferenceSource.INTERNAL:
            native = SR7265ReferenceInput.INTERNAL
        elif edge is LockinRefenceEdge.ZERO:
            native = SR7265ReferenceInput.EXTERNAL_ANALOG
        else:
            native = SR7265ReferenceInput.EXTERNAL_TTL
        self.set_reference_input(native)

    def get_reference_frequency(self) -> float:
        """Return the measured reference frequency in hertz."""
        return float(self.query("FRQ."))

    def set_reference_frequency(self, value: float) -> None:
        """Set internal oscillator frequency from 1 mHz to 250 kHz."""
        if not 0.001 <= value <= 250_000.0:
            raise ValueError("Reference frequency must be between 0.001 and 250000 Hz.")
        self.write(f"OF. {value}")

    def get_reference_phase(self) -> float:
        """Return reference phase in degrees."""
        return float(self.query("REFP."))

    def set_reference_phase(self, value: float) -> None:
        """Set reference phase in degrees."""
        self.write(f"REFP. {value}")

    def get_harmonic(self) -> int:
        """Return the reference harmonic number."""
        return int(float(self.query("REFN")))

    def set_harmonic(self, harmonic: int) -> None:
        """Set a reference harmonic from 1 through 65535."""
        if not isinstance(harmonic, int) or not 1 <= harmonic <= self._MAX_HARMONIC:
            raise ValueError(f"Harmonic must be an integer between 1 and {self._MAX_HARMONIC}.")
        self.write(f"REFN {harmonic}")

    def get_filter_slope(self) -> int:
        """Return output-filter slope in dB/octave."""
        return int(
            self._decode_index(int(float(self.query("SLOPE"))), self._FILTER_SLOPES, "Filter slope")
        )

    def set_filter_slope(self, slope: int) -> None:
        """Set output-filter slope to 6, 12, 18, or 24 dB/octave."""
        try:
            code = self._FILTER_SLOPES.index(slope)
        except ValueError as exc:
            raise ValueError(f"Filter slope must be one of {self._FILTER_SLOPES!r}.") from exc
        self.write(f"SLOPE {code}")

    def get_input_coupling(self) -> LockInInputCoupling:
        """Return AC or DC input coupling."""
        return LockInInputCoupling.DC if int(float(self.query("CP"))) else LockInInputCoupling.AC

    def set_input_coupling(self, coupling: LockInInputCoupling) -> None:
        """Set AC or DC input coupling."""
        self.write(f"CP {1 if coupling is LockInInputCoupling.DC else 0}")

    def get_input_source(self) -> LockInInputSource:
        """Return voltage/current input mode, querying ``VMODE`` when needed."""
        imode = int(float(self.query("IMODE")))
        if imode == 1:
            return LockInInputSource.I_1MOHM
        if imode == 2:
            return LockInInputSource.I_100MOHM
        if imode != 0:
            raise ValueError(f"Unexpected 7265 IMODE code: {imode}")
        vmode = int(float(self.query("VMODE")))
        if vmode == 1:
            return LockInInputSource.A
        if vmode == 2:
            return LockInInputSource.B
        if vmode == 3:
            return LockInInputSource.A_MINUS_B
        raise ValueError(f"Unexpected 7265 VMODE code: {vmode}")

    def set_input_source(self, source: LockInInputSource) -> None:
        """Select A, inverted B, A-B, wide-band current, or low-noise current input."""
        commands = {
            LockInInputSource.A: "IMODE 0;VMODE 1",
            LockInInputSource.B: "IMODE 0;VMODE 2",
            LockInInputSource.A_MINUS_B: "IMODE 0;VMODE 3",
            LockInInputSource.I_1MOHM: "IMODE 1",
            LockInInputSource.I_100MOHM: "IMODE 2",
        }
        self.write(commands[source])

    def get_input_shielding(self) -> LockInInputShielding:
        """Return floating or grounded input-shell state."""
        return (
            LockInInputShielding.FLOAT
            if int(float(self.query("FLOAT")))
            else LockInInputShielding.GROUND
        )

    def set_input_shielding(self, shielding: LockInInputShielding) -> None:
        """Float or ground the input connector shell."""
        self.write(f"FLOAT {1 if shielding is LockInInputShielding.FLOAT else 0}")

    def get_line_filter(self) -> LockInLineFilter:
        """Return the line-frequency notch selection."""
        code = int(self._parse_values(self.query("LF"), expected=2)[0])
        filters = (
            LockInLineFilter.NONE,
            LockInLineFilter.LINE,
            LockInLineFilter.LINE_2X,
            LockInLineFilter.BOTH,
        )
        if not 0 <= code < len(filters):
            raise ValueError(f"Unexpected 7265 line-filter code: {code}")
        return filters[code]

    def set_line_filter(self, filter_config: LockInLineFilter) -> None:
        """Set the notch selection while preserving the 50/60 Hz setting."""
        frequency_code = int(self._parse_values(self.query("LF"), expected=2)[1])
        filter_code = {
            LockInLineFilter.NONE: 0,
            LockInLineFilter.LINE: 1,
            LockInLineFilter.LINE_2X: 2,
            LockInLineFilter.BOTH: 3,
        }[filter_config]
        self.write(f"LF {filter_code} {frequency_code}")

    def get_sync_filter_enabled(self) -> bool:
        """Return whether the synchronous filter is enabled."""
        return bool(int(float(self.query("SYNC"))))

    def set_sync_filter_enabled(self, state: bool) -> None:
        """Enable or disable the synchronous filter."""
        self.write(f"SYNC {1 if state else 0}")

    def auto_gain(self) -> None:
        """Run 7265 automatic sensitivity/gain adjustment."""
        self.write("AS")

    def auto_phase(self) -> None:
        """Run the single-shot 7265 automatic phase adjustment."""
        self.write("AQN")

    def auto_reserve(self) -> None:
        """Enable automatic AC-gain adjustment."""
        self.write("AUTOMATIC 1")

    def get_oscillator_amplitude(self) -> float:
        """Return oscillator amplitude in volts RMS."""
        return float(self.query("OA."))

    def set_oscillator_amplitude(self, value: float) -> None:
        """Set oscillator amplitude from 1 microvolt to 5 volts RMS."""
        if not 1e-6 <= value <= 5.0:
            raise ValueError("Oscillator amplitude must be between 1e-6 and 5 V RMS.")
        self.write(f"OA. {value}")

    def read_adc(self, channel: int) -> float:
        """Read auxiliary ADC channel 1 or 2 in volts."""
        if channel not in (1, 2):
            raise ValueError("ADC channel must be 1 or 2.")
        return float(self.query(f"ADC. {channel}"))

    def get_dac(self, channel: int) -> float:
        """Return auxiliary DAC channel 1 through 4 in volts."""
        if channel not in range(1, 5):
            raise ValueError("DAC channel must be between 1 and 4.")
        return float(self.query(f"DAC. {channel}"))

    def set_dac(self, channel: int, value: float) -> None:
        """Set auxiliary DAC voltage with the native 1 mV resolution."""
        if channel not in range(1, 5):
            raise ValueError("DAC channel must be between 1 and 4.")
        self.write(f"DAC. {channel} {value:.3f}")

    def start_curve(self, *, continuous: bool = False, triggered: bool = False) -> None:
        """Start one-shot, continuous, or externally triggered curve acquisition."""
        if continuous and triggered:
            raise ValueError("Curve acquisition cannot be both continuous and triggered.")
        self.write("TDT 0" if triggered else "TDC" if continuous else "TD")

    def pause_curve(self) -> None:
        """Pause curve acquisition."""
        self.write("HC")

    def clear_curve(self) -> None:
        """Stop acquisition and erase curve buffers."""
        self.write("NC")

    def get_curve_storage_interval(self) -> float:
        """Return curve-buffer storage interval in seconds."""
        milliseconds = float(self.query("STR"))
        return 0.00125 if milliseconds == 0.0 else milliseconds / 1000.0

    def set_curve_storage_interval(self, seconds: float) -> None:
        """Set curve-buffer storage interval from 1.25 ms to 1000 s."""
        if isclose(seconds, 0.00125, rel_tol=0.0, abs_tol=1e-12):
            self.write("STR 0")
            return
        milliseconds = seconds * 1000.0
        if not 5.0 <= milliseconds <= 1e6:
            raise ValueError(
                "Curve storage interval must be 0.00125 s or between 0.005 and 1000 s."
            )
        rounded_milliseconds = 5 * ceil(milliseconds / 5)
        self.write(f"STR {rounded_milliseconds}")

    def buffer_points(self) -> int:
        """Return the fourth value from the curve-acquisition monitor."""
        return int(self._parse_values(self.query("M"), expected=4)[3])

    def read_curve(self, buffer: int) -> tuple[float, ...]:
        """Read one curve buffer as floating-point values."""
        if buffer < 1:
            raise ValueError("Curve buffer number must be positive.")
        return self._parse_values(self.query(f"DC. {buffer}"))

    def wait_for_settle(self, multiples: float = 5.0) -> None:
        """Wait a configurable number of active output time constants."""
        if multiples < 0.0:
            raise ValueError("Settle-time multiplier must be non-negative.")
        time_constant = (
            self._time_constant if self._time_constant is not None else self.get_time_constant()
        )
        sleep(multiples * time_constant)

    def get_capabilities(self) -> LockInAmplifierCapabilities:
        """Return shared lock-in capabilities implemented by this driver."""
        return LockInAmplifierCapabilities(
            has_reference_source_selection=True,
            has_reference_frequency_control=True,
            has_reference_phase_control=True,
            has_harmonic_selection=True,
            has_filter_slope_control=True,
            has_input_coupling_control=True,
            has_auto_gain=True,
            has_auto_phase=True,
            has_auto_reserve=True,
            has_internal_oscillator=True,
            has_input_source_selection=True,
            has_input_shielding_control=True,
            has_line_filter_control=True,
            has_sync_filter=True,
            max_harmonic=self._MAX_HARMONIC,
        )
