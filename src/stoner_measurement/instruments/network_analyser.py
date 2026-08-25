"""Abstract interface and shared data types for vector network analysers."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class SweepType(Enum):
    """Portable network-analyser sweep modes."""

    LINEAR = "linear"
    LOGARITHMIC = "logarithmic"
    CW = "cw"
    POWER = "power"
    SEGMENTED = "segmented"


class NetworkAnalyserTriggerSource(Enum):
    """Portable network-analyser trigger sources."""

    INTERNAL = "internal"
    MANUAL = "manual"
    EXTERNAL = "external"
    BUS = "bus"


class TraceFormat(Enum):
    """Portable display formats for network-analyser traces."""

    LOG_MAGNITUDE = "log_magnitude"
    LINEAR_MAGNITUDE = "linear_magnitude"
    PHASE = "phase"
    UNWRAPPED_PHASE = "unwrapped_phase"
    GROUP_DELAY = "group_delay"
    SMITH = "smith"
    POLAR = "polar"
    REAL = "real"
    IMAGINARY = "imaginary"
    SWR = "swr"


class DataEncoding(Enum):
    """Numeric transfer encodings supported by network analysers."""

    ASCII = "ascii"
    REAL32 = "real32"
    REAL64 = "real64"


class ByteOrder(Enum):
    """SCPI binary-transfer byte orders."""

    NORMAL = "normal"
    SWAPPED = "swapped"


@dataclass(frozen=True)
class NetworkAnalyserCapabilities:
    """Runtime capability descriptor for a network analyser."""

    port_count: int
    max_channels: int
    max_traces_per_channel: int
    frequency_min_hz: float | None
    frequency_max_hz: float | None
    supported_sweep_types: tuple[SweepType, ...]
    supported_trace_formats: tuple[TraceFormat, ...]
    has_segmented_sweep: bool = False
    has_binary_transfer: bool = False
    has_guided_calibration: bool = False
    has_ecal: bool = False
    has_frequency_offset: bool = False
    has_power_sweep: bool = False
    has_limit_test: bool = False
    has_markers: bool = False
    has_handler_io: bool = False
    installed_options: tuple[str, ...] = ()
    firmware: str | None = None


@dataclass(frozen=True)
class SweepConfiguration:
    """Portable configuration for one network-analyser channel."""

    sweep_type: SweepType
    start_hz: float
    stop_hz: float
    points: int
    if_bandwidth_hz: float | None = None
    source_power_dbm: float | None = None
    averaging_count: int | None = None


@dataclass(frozen=True)
class NetworkTraceData:
    """One acquired network-analyser trace."""

    channel: int
    trace: int
    parameter: str
    stimulus: np.ndarray
    values: np.ndarray
    corrected: bool


@dataclass(frozen=True)
class NetworkSweep:
    """A synchronized collection of network-analyser traces."""

    traces: tuple[NetworkTraceData, ...]


class NetworkAnalyser(BaseInstrument):
    """Abstract base class for vector network analysers."""

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
        *,
        auto_check_errors: bool = True,
    ) -> None:
        """Initialise the analyser with repository transport/protocol layers."""
        super().__init__(
            transport=transport,
            protocol=protocol,
            auto_check_errors=auto_check_errors,
        )

    @abstractmethod
    def get_capabilities(self) -> NetworkAnalyserCapabilities:
        """Return runtime capability metadata."""

    @abstractmethod
    def get_sweep_configuration(self, channel: int = 1) -> SweepConfiguration:
        """Return the sweep configuration for *channel*."""

    @abstractmethod
    def set_sweep_configuration(
        self, configuration: SweepConfiguration, channel: int = 1
    ) -> None:
        """Apply a sweep configuration to *channel*."""

    @abstractmethod
    def get_measurement_parameter(self, channel: int = 1, trace: int = 1) -> str:
        """Return the measurement parameter assigned to a trace."""

    @abstractmethod
    def set_measurement_parameter(
        self, parameter: str, channel: int = 1, trace: int = 1
    ) -> None:
        """Assign a measurement parameter to a trace."""

    @abstractmethod
    def get_if_bandwidth(self, channel: int = 1) -> float:
        """Return channel IF bandwidth in hertz."""

    @abstractmethod
    def set_if_bandwidth(self, value_hz: float, channel: int = 1) -> None:
        """Set channel IF bandwidth in hertz."""

    @abstractmethod
    def get_source_power(self, channel: int = 1, port: int | None = None) -> float:
        """Return ordinary source power in dBm."""

    @abstractmethod
    def set_source_power(
        self, value_dbm: float, channel: int = 1, port: int | None = None
    ) -> None:
        """Set ordinary source power in dBm without enabling RF output."""

    def get_cw_frequency(self, channel: int = 1) -> float:
        """Return the fixed frequency used for a power sweep."""
        raise NotImplementedError(
            f"{type(self).__name__} does not expose a CW frequency."
        )

    def set_cw_frequency(self, value_hz: float, channel: int = 1) -> None:
        """Set the fixed frequency used for a power sweep."""
        _ = (value_hz, channel)
        raise NotImplementedError(
            f"{type(self).__name__} does not expose a CW frequency."
        )

    def get_power_sweep_range(self, channel: int = 1) -> tuple[float, float]:
        """Return power-sweep start and stop levels in dBm."""
        raise NotImplementedError(
            f"{type(self).__name__} does not expose a power-sweep range."
        )

    def set_power_sweep_range(
        self, start_dbm: float, stop_dbm: float, channel: int = 1
    ) -> None:
        """Set power-sweep start and stop levels in dBm."""
        _ = (start_dbm, stop_dbm, channel)
        raise NotImplementedError(
            f"{type(self).__name__} does not expose a power-sweep range."
        )

    def has_external_pulse_modulator(self, channel: int = 1) -> bool:
        """Return whether a TTL-controlled external RF pulse modulator exists."""
        self._validate_channel(channel)
        return False

    def get_external_pulse_modulation(
        self, channel: int = 1, port: int = 1
    ) -> bool:
        """Return whether external TTL pulse gating is enabled for a source port."""
        _ = (channel, port)
        raise NotImplementedError(
            f"{type(self).__name__} does not expose external pulse modulation."
        )

    def set_external_pulse_modulation(
        self, enabled: bool, channel: int = 1, port: int = 1
    ) -> None:
        """Enable or disable external TTL on/off gating for a source port."""
        _ = (enabled, channel, port)
        raise NotImplementedError(
            f"{type(self).__name__} does not expose external pulse modulation."
        )

    @abstractmethod
    def get_averaging(self, channel: int = 1) -> tuple[bool, int]:
        """Return averaging enable state and count."""

    @abstractmethod
    def set_averaging(
        self, enabled: bool, count: int | None = None, channel: int = 1
    ) -> None:
        """Set averaging enable state and optionally its count."""

    @abstractmethod
    def get_continuous(self, channel: int = 1) -> bool:
        """Return whether continuous acquisition is enabled."""

    @abstractmethod
    def set_continuous(self, enabled: bool, channel: int = 1) -> None:
        """Enable or disable continuous acquisition."""

    @abstractmethod
    def get_trigger_source(self) -> NetworkAnalyserTriggerSource:
        """Return the active trigger source."""

    @abstractmethod
    def set_trigger_source(self, source: NetworkAnalyserTriggerSource) -> None:
        """Set the trigger source."""

    @abstractmethod
    def initiate(self, channel: int = 1) -> None:
        """Initiate one channel."""

    @abstractmethod
    def trigger(self) -> None:
        """Issue an immediate trigger."""

    @abstractmethod
    def abort(self) -> None:
        """Abort acquisition."""

    @abstractmethod
    def perform_single_sweep(self, channel: int = 1) -> None:
        """Block until one complete sweep of *channel* has finished."""

    @abstractmethod
    def read_stimulus(self, channel: int = 1, trace: int = 1) -> np.ndarray:
        """Read the measured X-axis values for a trace."""

    @abstractmethod
    def read_complex(
        self, channel: int = 1, trace: int = 1, *, corrected: bool = True
    ) -> np.ndarray:
        """Read complex trace values independently of display format."""

    def acquire(
        self,
        channel: int = 1,
        traces: tuple[int, ...] | None = None,
        *,
        timeout: float | None = None,
        corrected: bool = True,
    ) -> NetworkSweep:
        """Acquire one synchronized sweep and return matching trace arrays."""
        self._validate_channel(channel)
        selected_traces = traces if traces is not None else (1,)
        if not selected_traces:
            raise ValueError("At least one trace must be requested.")
        if len(set(selected_traces)) != len(selected_traces):
            raise ValueError("Trace numbers must not be repeated.")
        for trace in selected_traces:
            self._validate_trace(trace)

        with self._lock:
            previous_timeout = self.transport.timeout
            if timeout is not None:
                if timeout <= 0:
                    raise ValueError("timeout must be positive.")
                self.transport.timeout = timeout
            try:
                self.perform_single_sweep(channel)
                stimulus = self.read_stimulus(channel, selected_traces[0])
                results: list[NetworkTraceData] = []
                for trace in selected_traces:
                    values = self.read_complex(channel, trace, corrected=corrected)
                    if len(values) != len(stimulus):
                        raise ValueError(
                            f"Trace {trace} returned {len(values)} values for "
                            f"{len(stimulus)} stimulus points."
                        )
                    results.append(
                        NetworkTraceData(
                            channel=channel,
                            trace=trace,
                            parameter=self.get_measurement_parameter(channel, trace),
                            stimulus=stimulus.copy(),
                            values=values,
                            corrected=corrected,
                        )
                    )
                return NetworkSweep(tuple(results))
            finally:
                if timeout is not None:
                    self.transport.timeout = previous_timeout

    @staticmethod
    def _validate_channel(channel: int) -> None:
        if not isinstance(channel, int) or isinstance(channel, bool) or channel < 1:
            raise ValueError("channel must be a positive integer.")

    @staticmethod
    def _validate_trace(trace: int) -> None:
        if not isinstance(trace, int) or isinstance(trace, bool) or trace < 1:
            raise ValueError("trace must be a positive integer.")

    @staticmethod
    def _validate_port(port: int | None) -> None:
        if port is not None and (
            not isinstance(port, int) or isinstance(port, bool) or port < 1
        ):
            raise ValueError("port must be a positive integer.")

    def _validate_s_parameter(self, parameter: str, *, port_count: int) -> str:
        token = parameter.strip().upper()
        if len(token) != 3 or token[0] != "S" or not token[1:].isdigit():
            raise ValueError("Only two-port-style S-parameter names such as 'S21' are supported.")
        response_port = int(token[1])
        source_port = int(token[2])
        if not 1 <= response_port <= port_count or not 1 <= source_port <= port_count:
            raise ValueError(f"{token} refers to a port outside 1..{port_count}.")
        return token

    def get_correction_enabled(self, channel: int = 1) -> bool:
        """Return whether vector error correction is enabled."""
        raise NotImplementedError(
            f"{type(self).__name__} does not expose correction state."
        )

    def set_correction_enabled(self, enabled: bool, channel: int = 1) -> None:
        """Enable or disable vector error correction."""
        _ = (enabled, channel)
        raise NotImplementedError(
            f"{type(self).__name__} does not expose correction state."
        )
