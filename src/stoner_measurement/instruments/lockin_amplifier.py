"""Abstract base class for lock-in amplifier instruments."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class LockInReferenceSource(Enum):
    """Reference-source selection for lock-in amplifiers."""

    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class LockInInputCoupling(Enum):
    """Input-coupling selection for lock-in amplifiers."""

    AC = "AC"
    DC = "DC"


class LockInReserveMode(Enum):
    """Dynamic-reserve operating modes."""

    HIGH_RESERVE = "HIGH_RESERVE"
    NORMAL = "NORMAL"
    LOW_NOISE = "LOW_NOISE"


class LockInInputSource(Enum):
    """Input source selection for lock-in amplifiers."""

    A = "A"
    A_MINUS_B = "A_MINUS_B"
    I_1MOHM = "I_1MOHM"
    I_100MOHM = "I_100MOHM"


class LockInInputShielding(Enum):
    """Input shield grounding selection for lock-in amplifiers."""

    FLOAT = "FLOAT"
    GROUND = "GROUND"


class LockInLineFilter(Enum):
    """Line-frequency notch filter configuration for lock-in amplifiers."""

    NONE = "NONE"
    LINE = "LINE"
    LINE_2X = "LINE_2X"
    BOTH = "BOTH"


class LockInOutputChannel(Enum):
    """Output channel selection for offset and expand operations."""

    X = "X"
    Y = "Y"
    R = "R"


class LockInExpandFactor(Enum):
    """Expand factor for output offset operations."""

    X1 = 1
    X10 = 10
    X100 = 100


@dataclass(frozen=True)
class LockInAmplifierCapabilities:
    """Static capability descriptor for a lock-in amplifier driver."""

    has_reference_source_selection: bool = True
    has_reference_frequency_control: bool = True
    has_reference_phase_control: bool = True
    has_harmonic_selection: bool = False
    has_filter_slope_control: bool = False
    has_input_coupling_control: bool = False
    has_reserve_mode_control: bool = False
    has_auto_gain: bool = False
    has_auto_phase: bool = False
    has_auto_reserve: bool = False
    has_output_offset: bool = False
    has_internal_oscillator: bool = False
    has_input_source_selection: bool = False
    has_input_shielding_control: bool = False
    has_line_filter_control: bool = False
    has_sync_filter: bool = False
    max_harmonic: int = 0


class LockInAmplifier(BaseInstrument):
    """Abstract base class for lock-in amplifier instruments.

    Provides a common interface for dual-output lock-in amplifiers where
    the measured signal is available as in-phase/quadrature components
    (``X``, ``Y``) and polar components (magnitude ``R``, angle ``theta``).

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol instance.
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        """Initialise the lock-in amplifier.

        Args:
            transport (BaseTransport):
                Transport layer instance.
            protocol (BaseProtocol):
                Protocol instance.
        """
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def measure_xy(self) -> tuple[float, float]:
        """Measure and return the in-phase and quadrature outputs.

        Returns:
            (tuple[float, float]):
                ``(x, y)`` values in volts, where ``x`` is the in-phase
                component and ``y`` is the quadrature component.
        """

    @abstractmethod
    def measure_rt(self) -> tuple[float, float]:
        """Measure and return magnitude and phase outputs.

        Returns:
            (tuple[float, float]):
                ``(magnitude, theta)`` where magnitude is in volts and
                ``theta`` is in degrees.
        """

    @abstractmethod
    def get_sensitivity(self) -> float:
        """Return the active sensitivity scale.

        Returns:
            (float):
                Sensitivity in volts.
        """

    @abstractmethod
    def set_sensitivity(self, value: float) -> None:
        """Set the active sensitivity scale.

        Args:
            value (float):
                Sensitivity in volts.
        """

    @abstractmethod
    def get_time_constant(self) -> float:
        """Return the active output filter time constant.

        Returns:
            (float):
                Time constant in seconds.
        """

    @abstractmethod
    def set_time_constant(self, value: float) -> None:
        """Set the output filter time constant.

        Args:
            value (float):
                Time constant in seconds.
        """

    @abstractmethod
    def get_reference_source(self) -> LockInReferenceSource:
        """Return the active reference source.

        Returns:
            (LockInReferenceSource):
                Active reference source.
        """

    @abstractmethod
    def set_reference_source(self, source: LockInReferenceSource) -> None:
        """Set the active reference source.

        Args:
            source (LockInReferenceSource):
                Source to select.
        """

    @abstractmethod
    def get_reference_frequency(self) -> float:
        """Return the reference frequency in hertz.

        Returns:
            (float):
                Reference frequency in hertz.
        """

    @abstractmethod
    def set_reference_frequency(self, value: float) -> None:
        """Set the reference frequency in hertz.

        Args:
            value (float):
                Frequency in hertz.
        """

    @abstractmethod
    def get_reference_phase(self) -> float:
        """Return the reference phase in degrees.

        Returns:
            (float):
                Reference phase in degrees.
        """

    @abstractmethod
    def set_reference_phase(self, value: float) -> None:
        """Set the reference phase in degrees.

        Args:
            value (float):
                Phase in degrees.
        """

    @abstractmethod
    def get_capabilities(self) -> LockInAmplifierCapabilities:
        """Return static capability metadata.

        Returns:
            (LockInAmplifierCapabilities):
                Capability descriptor.
        """

    def get_harmonic(self) -> int:
        """Return the selected detection harmonic.

        Raises:
            NotImplementedError:
                If harmonic selection is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support harmonic selection. "
            "Check get_capabilities().has_harmonic_selection before calling this method."
        )

    def set_harmonic(self, harmonic: int) -> None:
        """Set the selected detection harmonic.

        Raises:
            NotImplementedError:
                If harmonic selection is not supported by the instrument.
        """
        _ = harmonic
        raise NotImplementedError(
            f"{type(self).__name__} does not support harmonic selection. "
            "Check get_capabilities().has_harmonic_selection before calling this method."
        )

    def get_filter_slope(self) -> int:
        """Return the output filter roll-off slope in dB/octave.

        Raises:
            NotImplementedError:
                If filter-slope control is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support filter-slope control. "
            "Check get_capabilities().has_filter_slope_control before calling this method."
        )

    def set_filter_slope(self, slope: int) -> None:
        """Set the output filter roll-off slope in dB/octave.

        Raises:
            NotImplementedError:
                If filter-slope control is not supported by the instrument.
        """
        _ = slope
        raise NotImplementedError(
            f"{type(self).__name__} does not support filter-slope control. "
            "Check get_capabilities().has_filter_slope_control before calling this method."
        )

    def get_input_coupling(self) -> LockInInputCoupling:
        """Return the input coupling mode.

        Raises:
            NotImplementedError:
                If input-coupling control is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support input-coupling control. "
            "Check get_capabilities().has_input_coupling_control before calling this method."
        )

    def set_input_coupling(self, coupling: LockInInputCoupling) -> None:
        """Set the input coupling mode.

        Raises:
            NotImplementedError:
                If input-coupling control is not supported by the instrument.
        """
        _ = coupling
        raise NotImplementedError(
            f"{type(self).__name__} does not support input-coupling control. "
            "Check get_capabilities().has_input_coupling_control before calling this method."
        )

    def get_reserve_mode(self) -> LockInReserveMode:
        """Return the dynamic reserve mode.

        Raises:
            NotImplementedError:
                If reserve-mode control is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support reserve-mode control. "
            "Check get_capabilities().has_reserve_mode_control before calling this method."
        )

    def set_reserve_mode(self, mode: LockInReserveMode) -> None:
        """Set the dynamic reserve mode.

        Raises:
            NotImplementedError:
                If reserve-mode control is not supported by the instrument.
        """
        _ = mode
        raise NotImplementedError(
            f"{type(self).__name__} does not support reserve-mode control. "
            "Check get_capabilities().has_reserve_mode_control before calling this method."
        )

    def auto_gain(self) -> None:
        """Run instrument auto-gain adjustment.

        Raises:
            NotImplementedError:
                If auto-gain is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support auto-gain adjustment. "
            "Check get_capabilities().has_auto_gain before calling this method."
        )

    def auto_phase(self) -> None:
        """Run instrument auto-phase adjustment.

        Raises:
            NotImplementedError:
                If auto-phase is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support auto-phase adjustment. "
            "Check get_capabilities().has_auto_phase before calling this method."
        )

    def auto_reserve(self) -> None:
        """Run instrument auto-reserve adjustment.

        Raises:
            NotImplementedError:
                If auto-reserve is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support auto-reserve adjustment. "
            "Check get_capabilities().has_auto_reserve before calling this method."
        )

    def get_oscillator_amplitude(self) -> float:
        """Return the internal oscillator sine output amplitude in volts.

        Returns:
            (float):
                Oscillator amplitude in volts.

        Raises:
            NotImplementedError:
                If the instrument does not have a controllable internal oscillator.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support internal oscillator control. "
            "Check get_capabilities().has_internal_oscillator before calling this method."
        )

    def set_oscillator_amplitude(self, value: float) -> None:
        """Set the internal oscillator sine output amplitude in volts.

        Args:
            value (float):
                Amplitude in volts.

        Raises:
            NotImplementedError:
                If the instrument does not have a controllable internal oscillator.
        """
        _ = value
        raise NotImplementedError(
            f"{type(self).__name__} does not support internal oscillator control. "
            "Check get_capabilities().has_internal_oscillator before calling this method."
        )

    def get_output_offset(self, channel: LockInOutputChannel) -> tuple[float, LockInExpandFactor]:
        """Return the output offset percentage and expand factor for a channel.

        Args:
            channel (LockInOutputChannel):
                Output channel to query.

        Returns:
            (tuple[float, LockInExpandFactor]):
                ``(offset_pct, expand_factor)`` where ``offset_pct`` is the
                offset as a percentage and ``expand_factor`` is the expand
                multiplier.

        Raises:
            NotImplementedError:
                If output offset and expand are not supported by the instrument.
        """
        _ = channel
        raise NotImplementedError(
            f"{type(self).__name__} does not support output offset and expand. "
            "Check get_capabilities().has_output_offset before calling this method."
        )

    def set_output_offset(
        self,
        channel: LockInOutputChannel,
        offset_pct: float,
        expand_factor: LockInExpandFactor,
    ) -> None:
        """Set the output offset and expand factor for a channel.

        Args:
            channel (LockInOutputChannel):
                Output channel to configure.
            offset_pct (float):
                Offset as a percentage (typically −105 % to +105 %).
            expand_factor (LockInExpandFactor):
                Expand multiplier to apply.

        Raises:
            NotImplementedError:
                If output offset and expand are not supported by the instrument.
        """
        _, _, _ = channel, offset_pct, expand_factor
        raise NotImplementedError(
            f"{type(self).__name__} does not support output offset and expand. "
            "Check get_capabilities().has_output_offset before calling this method."
        )

    def get_input_source(self) -> LockInInputSource:
        """Return the active input source.

        Returns:
            (LockInInputSource):
                Active input source selection.

        Raises:
            NotImplementedError:
                If input source selection is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support input source selection. "
            "Check get_capabilities().has_input_source_selection before calling this method."
        )

    def set_input_source(self, source: LockInInputSource) -> None:
        """Set the active input source.

        Args:
            source (LockInInputSource):
                Input source to select.

        Raises:
            NotImplementedError:
                If input source selection is not supported by the instrument.
        """
        _ = source
        raise NotImplementedError(
            f"{type(self).__name__} does not support input source selection. "
            "Check get_capabilities().has_input_source_selection before calling this method."
        )

    def get_input_shielding(self) -> LockInInputShielding:
        """Return the input shield grounding mode.

        Returns:
            (LockInInputShielding):
                Active input shield grounding mode.

        Raises:
            NotImplementedError:
                If input shielding control is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support input shielding control. "
            "Check get_capabilities().has_input_shielding_control before calling this method."
        )

    def set_input_shielding(self, shielding: LockInInputShielding) -> None:
        """Set the input shield grounding mode.

        Args:
            shielding (LockInInputShielding):
                Shielding mode to select.

        Raises:
            NotImplementedError:
                If input shielding control is not supported by the instrument.
        """
        _ = shielding
        raise NotImplementedError(
            f"{type(self).__name__} does not support input shielding control. "
            "Check get_capabilities().has_input_shielding_control before calling this method."
        )

    def get_line_filter(self) -> LockInLineFilter:
        """Return the line-frequency notch filter configuration.

        Returns:
            (LockInLineFilter):
                Active notch filter configuration.

        Raises:
            NotImplementedError:
                If line filter control is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support line filter control. "
            "Check get_capabilities().has_line_filter_control before calling this method."
        )

    def set_line_filter(self, filter_config: LockInLineFilter) -> None:
        """Set the line-frequency notch filter configuration.

        Args:
            filter_config (LockInLineFilter):
                Notch filter configuration to apply.

        Raises:
            NotImplementedError:
                If line filter control is not supported by the instrument.
        """
        _ = filter_config
        raise NotImplementedError(
            f"{type(self).__name__} does not support line filter control. "
            "Check get_capabilities().has_line_filter_control before calling this method."
        )

    def get_sync_filter_enabled(self) -> bool:
        """Return whether the synchronous output filter is enabled.

        Returns:
            (bool):
                ``True`` when the synchronous filter is enabled.

        Raises:
            NotImplementedError:
                If synchronous filter control is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support synchronous filter control. "
            "Check get_capabilities().has_sync_filter before calling this method."
        )

    def set_sync_filter_enabled(self, state: bool) -> None:
        """Enable or disable the synchronous output filter.

        Args:
            state (bool):
                ``True`` to enable the synchronous filter.

        Raises:
            NotImplementedError:
                If synchronous filter control is not supported by the instrument.
        """
        _ = state
        raise NotImplementedError(
            f"{type(self).__name__} does not support synchronous filter control. "
            "Check get_capabilities().has_sync_filter before calling this method."
        )

    def get_dynamic_reserve_db(self) -> float:
        """Return the dynamic reserve (signal stability) in decibels.

        A higher value indicates that the instrument can tolerate larger
        interfering signals relative to the signal of interest without
        introducing significant errors.

        Returns:
            (float):
                Dynamic reserve in dB.

        Raises:
            NotImplementedError:
                If numeric dynamic reserve control is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support numeric dynamic reserve control. "
            "Check get_capabilities().has_dynamic_reserve_db before calling this method."
        )

    def set_dynamic_reserve_db(self, value_db: float) -> None:
        """Set the dynamic reserve (signal stability) in decibels.

        Args:
            value_db (float):
                Desired dynamic reserve in dB.

        Raises:
            NotImplementedError:
                If numeric dynamic reserve control is not supported by the instrument.
        """
        _ = value_db
        raise NotImplementedError(
            f"{type(self).__name__} does not support numeric dynamic reserve control. "
            "Check get_capabilities().has_dynamic_reserve_db before calling this method."
        )
