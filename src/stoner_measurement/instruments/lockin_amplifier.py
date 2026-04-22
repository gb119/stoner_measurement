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
                ``(x, y)`` values.
        """

    @abstractmethod
    def measure_rt(self) -> tuple[float, float]:
        """Measure and return magnitude and phase outputs.

        Returns:
            (tuple[float, float]):
                ``(magnitude, theta)`` values.
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
        """Return the active reference source."""

    @abstractmethod
    def set_reference_source(self, source: LockInReferenceSource) -> None:
        """Set the active reference source.

        Args:
            source (LockInReferenceSource):
                Source to select.
        """

    @abstractmethod
    def get_reference_frequency(self) -> float:
        """Return the reference frequency in hertz."""

    @abstractmethod
    def set_reference_frequency(self, value: float) -> None:
        """Set the reference frequency in hertz.

        Args:
            value (float):
                Frequency in hertz.
        """

    @abstractmethod
    def get_reference_phase(self) -> float:
        """Return the reference phase in degrees."""

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
