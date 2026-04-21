"""Abstract base class for current-source instruments.

Defines a common API for precision current sources, including DC sourcing and
optional AC waveform features. Drivers can also expose balanced multi-channel
behaviour via capability flags and channel helper methods.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class CurrentWaveform(Enum):
    """Output waveform mode of a current-source instrument."""

    DC = "DC"
    SINE = "SINE"


class CurrentSweepSpacing(Enum):
    """Point-spacing mode for a built-in current sweep.

    Attributes:
        LIN:
            Linearly spaced sweep points from *start* to *stop*.
        LOG:
            Logarithmically spaced sweep points from *start* to *stop*.
        LIST:
            Arbitrary point list supplied in
            :attr:`CurrentSweepConfiguration.values`.
    """

    LIN = "LIN"
    LOG = "LOG"
    LIST = "LIST"


@dataclass(frozen=True)
class CurrentSweepConfiguration:
    """Configuration for a current-source sweep.

    Attributes:
        start (float):
            Sweep start value in amps.  Ignored for list sweeps.
        stop (float):
            Sweep stop value in amps.  Ignored for list sweeps.
        points (int):
            Number of sweep points.  For list sweeps this is inferred from
            ``len(values)`` by the driver; ignored when *values* is provided.
        spacing (CurrentSweepSpacing):
            Point-spacing mode.  Defaults to :attr:`~CurrentSweepSpacing.LIN`.
        values (tuple[float, ...] | None):
            Explicit source values for :attr:`~CurrentSweepSpacing.LIST`
            sweeps.  Ignored for linear and logarithmic sweeps.
        delay (float):
            Source settling delay between sweep points in seconds.
        count (int):
            Number of sweep repetitions.  Defaults to ``1``.

    Notes:
        Default *start*, *stop*, and *points* values are placeholders.
        For list sweeps supply *values* and omit *start*/*stop*/*points*.
    """

    start: float = 0.0
    stop: float = 0.0
    points: int = 0
    spacing: CurrentSweepSpacing = CurrentSweepSpacing.LIN
    values: tuple[float, ...] | None = None
    delay: float = 0.0
    count: int = 1


@dataclass(frozen=True)
class PulsedSweepConfiguration:
    """Pulse parameters for a pulsed current sweep.

    When used alongside :class:`CurrentSweepConfiguration`, each point in the
    sweep becomes a pulse: the output ramps to the programmed current for
    *width* seconds, then falls to *low_level* for *off_time* seconds before
    the next point.

    Attributes:
        width (float):
            Pulse-on duration in seconds.
        off_time (float):
            Duration at *low_level* between pulses, in seconds.
        low_level (float):
            Output current during the off phase, in amps.  Defaults to ``0.0``.
    """

    width: float
    off_time: float
    low_level: float = 0.0


@dataclass(frozen=True)
class CurrentSourceCapabilities:
    """Static capability descriptor for a current-source driver.

    Attributes:
        has_waveform_selection (bool):
            ``True`` if the source can select waveform mode.
        has_frequency_control (bool):
            ``True`` if AC waveform frequency can be configured.
        has_offset_current (bool):
            ``True`` if waveform DC offset current can be configured.
        has_balanced_outputs (bool):
            ``True`` if the source supports balanced multi-channel output pairs.
        has_sweep (bool):
            ``True`` if the source supports built-in source sweeps via
            :meth:`~CurrentSource.configure_sweep`,
            :meth:`~CurrentSource.sweep_start`, and
            :meth:`~CurrentSource.sweep_abort`.
        has_pulsed_sweep (bool):
            ``True`` if the source supports pulsed sweeps via
            :meth:`~CurrentSource.configure_pulsed_sweep`.
        channel_count (int):
            Number of independently addressable output channels.
    """

    has_waveform_selection: bool = False
    has_frequency_control: bool = False
    has_offset_current: bool = False
    has_balanced_outputs: bool = False
    has_sweep: bool = False
    has_pulsed_sweep: bool = False
    channel_count: int = 1


class CurrentSource(BaseInstrument):
    """Abstract base class for precision current-source instruments.

    Provides a shared API for DC current level, compliance voltage, and output
    enable control, with optional AC waveform and balanced-channel extensions
    advertised via :meth:`get_capabilities`.
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def get_source_level(self) -> float:
        """Return programmed source current in amps."""

    @abstractmethod
    def set_source_level(self, value: float) -> None:
        """Set source current in amps."""

    @abstractmethod
    def get_compliance_voltage(self) -> float:
        """Return compliance voltage in volts."""

    @abstractmethod
    def set_compliance_voltage(self, value: float) -> None:
        """Set compliance voltage in volts."""

    @abstractmethod
    def output_enabled(self) -> bool:
        """Return ``True`` if source output is enabled."""

    @abstractmethod
    def enable_output(self, state: bool) -> None:
        """Enable or disable source output."""

    @abstractmethod
    def get_capabilities(self) -> CurrentSourceCapabilities:
        """Return the static capability descriptor for this driver."""

    def get_waveform(self) -> CurrentWaveform:
        """Return the configured output waveform.

        Raises:
            NotImplementedError:
                If waveform selection is not supported by the driver.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support waveform selection. "
            "Check get_capabilities().has_waveform_selection before calling this method."
        )

    def set_waveform(self, waveform: CurrentWaveform) -> None:
        """Set output waveform mode.

        Raises:
            NotImplementedError:
                If waveform selection is not supported by the driver.
        """
        _ = waveform
        raise NotImplementedError(
            f"{type(self).__name__} does not support waveform selection. "
            "Check get_capabilities().has_waveform_selection before calling this method."
        )

    def get_frequency(self) -> float:
        """Return AC waveform frequency in Hz.

        Raises:
            NotImplementedError:
                If AC frequency control is not supported by the driver.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support frequency control. "
            "Check get_capabilities().has_frequency_control before calling this method."
        )

    def set_frequency(self, value: float) -> None:
        """Set AC waveform frequency in Hz.

        Raises:
            NotImplementedError:
                If AC frequency control is not supported by the driver.
        """
        _ = value
        raise NotImplementedError(
            f"{type(self).__name__} does not support frequency control. "
            "Check get_capabilities().has_frequency_control before calling this method."
        )

    def get_offset_current(self) -> float:
        """Return AC waveform DC offset current in amps.

        Raises:
            NotImplementedError:
                If offset-current control is not supported by the driver.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support offset-current control. "
            "Check get_capabilities().has_offset_current before calling this method."
        )

    def set_offset_current(self, value: float) -> None:
        """Set AC waveform DC offset current in amps.

        Raises:
            NotImplementedError:
                If offset-current control is not supported by the driver.
        """
        _ = value
        raise NotImplementedError(
            f"{type(self).__name__} does not support offset-current control. "
            "Check get_capabilities().has_offset_current before calling this method."
        )

    def get_channel_level(self, channel: int) -> float:
        """Return programmed current for a specific output channel.

        Raises:
            NotImplementedError:
                If per-channel current control is not supported by the driver.
        """
        _ = channel
        raise NotImplementedError(
            f"{type(self).__name__} does not support per-channel current control. "
            "Check get_capabilities().has_balanced_outputs before calling this method."
        )

    def set_channel_level(self, channel: int, value: float) -> None:
        """Set current for a specific output channel.

        Raises:
            NotImplementedError:
                If per-channel current control is not supported by the driver.
        """
        _ = (channel, value)
        raise NotImplementedError(
            f"{type(self).__name__} does not support per-channel current control. "
            "Check get_capabilities().has_balanced_outputs before calling this method."
        )

    def configure_sweep(self, config: CurrentSweepConfiguration) -> None:
        """Configure a built-in current sweep.

        Args:
            config (CurrentSweepConfiguration):
                Sweep configuration (spacing, start, stop, points, values, delay,
                count).

        Raises:
            NotImplementedError:
                If sweep is not supported by the driver.  Check
                ``get_capabilities().has_sweep`` before calling.
        """
        _ = config
        raise NotImplementedError(
            f"{type(self).__name__} does not support source sweeps. "
            "Check get_capabilities().has_sweep before calling this method."
        )

    def configure_linear_sweep(
        self,
        start: float,
        stop: float,
        points: int,
        *,
        delay: float = 0.0,
        count: int = 1,
    ) -> None:
        """Configure a linearly spaced current sweep.

        Args:
            start (float):
                Sweep start current in amps.
            stop (float):
                Sweep stop current in amps.
            points (int):
                Number of sweep points.

        Keyword Parameters:
            delay (float):
                Source settling delay between sweep points in seconds.
            count (int):
                Number of sweep repetitions.

        Raises:
            NotImplementedError:
                If sweep is not supported.  Check
                ``get_capabilities().has_sweep`` before calling.
        """
        self.configure_sweep(
            CurrentSweepConfiguration(
                start=start,
                stop=stop,
                points=points,
                spacing=CurrentSweepSpacing.LIN,
                delay=delay,
                count=count,
            )
        )

    def configure_log_sweep(
        self,
        start: float,
        stop: float,
        points: int,
        *,
        delay: float = 0.0,
        count: int = 1,
    ) -> None:
        """Configure a logarithmically spaced current sweep.

        Args:
            start (float):
                Sweep start current in amps.
            stop (float):
                Sweep stop current in amps.
            points (int):
                Number of sweep points.

        Keyword Parameters:
            delay (float):
                Source settling delay between sweep points in seconds.
            count (int):
                Number of sweep repetitions.

        Raises:
            NotImplementedError:
                If sweep is not supported.  Check
                ``get_capabilities().has_sweep`` before calling.
        """
        self.configure_sweep(
            CurrentSweepConfiguration(
                start=start,
                stop=stop,
                points=points,
                spacing=CurrentSweepSpacing.LOG,
                delay=delay,
                count=count,
            )
        )

    def configure_custom_sweep(
        self,
        values: tuple[float, ...],
        *,
        delay: float = 0.0,
        count: int = 1,
    ) -> None:
        """Configure a custom point-by-point current sweep.

        Args:
            values (tuple[float, ...]):
                Explicit current values in amps.

        Keyword Parameters:
            delay (float):
                Source settling delay between points in seconds.
            count (int):
                Number of sweep repetitions.

        Raises:
            NotImplementedError:
                If sweep is not supported.  Check
                ``get_capabilities().has_sweep`` before calling.
        """
        self.configure_sweep(
            CurrentSweepConfiguration(
                spacing=CurrentSweepSpacing.LIST,
                values=values,
                points=len(values),
                delay=delay,
                count=count,
            )
        )

    def sweep_start(self) -> None:
        """Arm the configured sweep, making it ready for triggering.

        Raises:
            NotImplementedError:
                If sweep is not supported by the driver.  Check
                ``get_capabilities().has_sweep`` before calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support source sweeps. "
            "Check get_capabilities().has_sweep before calling this method."
        )

    def sweep_abort(self) -> None:
        """Abort a running or armed sweep.

        Raises:
            NotImplementedError:
                If sweep is not supported by the driver.  Check
                ``get_capabilities().has_sweep`` before calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support source sweeps. "
            "Check get_capabilities().has_sweep before calling this method."
        )

    def configure_pulsed_sweep(
        self,
        sweep: CurrentSweepConfiguration,
        pulse: PulsedSweepConfiguration,
    ) -> None:
        """Configure a pulsed current sweep.

        Each point in *sweep* becomes a pulse of duration
        ``pulse.width`` seconds followed by ``pulse.off_time`` seconds at
        ``pulse.low_level`` before the next sweep point.

        Args:
            sweep (CurrentSweepConfiguration):
                Sweep point configuration.
            pulse (PulsedSweepConfiguration):
                Pulse timing and baseline current configuration.

        Raises:
            NotImplementedError:
                If pulsed sweep is not supported by the driver.  Check
                ``get_capabilities().has_pulsed_sweep`` before calling.
        """
        _ = (sweep, pulse)
        raise NotImplementedError(
            f"{type(self).__name__} does not support pulsed sweeps. "
            "Check get_capabilities().has_pulsed_sweep before calling this method."
        )
