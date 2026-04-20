"""Abstract base class for source-meter instruments.

Defines the common interface for combined voltage/current source and
measurement instruments (SMUs).  Concrete subclasses (e.g. Keithley 2400,
Keithley 2450) implement the abstract methods for the specific instrument.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport

#: Possible source modes for an SMU.
SourceMode = str  # Literal["VOLT", "CURR"]

#: Possible measured functions for an SMU.
MeasureFunction = str  # Literal["VOLT", "CURR", "RES", "POW"]

#: Sweep spacing options for built-in source sweeps.
SweepSpacing = str  # Literal["LIN", "LOG", "LIST"]

#: Trigger and arm source options.
TriggerSource = str  # Literal["IMM", "BUS", "EXT", "TLIN", "TIM"]

#: Minimum current magnitude used for resistance calculation.
_MIN_CURRENT_FOR_RESISTANCE_CALCULATION = 1e-12


@dataclass(frozen=True)
class SourceSweepConfiguration:
    """Configuration for a source sweep.

    Notes:
        Default ``start``, ``stop``, and ``points`` values are placeholders.
        Callers should provide values appropriate for the selected spacing mode.
        For list sweeps, use ``values`` and set ``points`` to ``len(values)``.
        The default ``delay`` of ``0.0`` seconds disables added settling time.
    """

    start: float = 0.0
    stop: float = 0.0
    points: int = 0
    spacing: SweepSpacing = "LIN"
    values: tuple[float, ...] | None = None
    delay: float = 0.0


@dataclass(frozen=True)
class TriggerModelConfiguration:
    """Configuration for simple trigger and arm models."""

    trigger_source: TriggerSource = "IMM"
    trigger_count: int = 1
    trigger_delay: float = 0.0
    arm_source: TriggerSource = "IMM"
    arm_count: int = 1


class SourceMeter(BaseInstrument):
    """Abstract base class for source-measure unit (SMU) instruments.

    A source-meter can source voltage or current while simultaneously
    measuring the complementary quantity, making it suitable for
    current-voltage (I–V) characterisation.

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol instance.

    Examples:
        >>> # Demonstrate interface using a minimal concrete implementation
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import ScpiProtocol
        >>> from stoner_measurement.instruments.source_meter import SourceMeter
        >>> class _SM(SourceMeter):
        ...     def get_source_mode(self): return "VOLT"
        ...     def set_source_mode(self, mode): pass
        ...     def get_source_level(self): return 1.0
        ...     def set_source_level(self, value): pass
        ...     def get_compliance(self): return 0.1
        ...     def set_compliance(self, value): pass
        ...     def get_nplc(self): return 1.0
        ...     def set_nplc(self, value): pass
        ...     def measure_voltage(self): return 1.0
        ...     def measure_current(self): return 0.001
        ...     def output_enabled(self): return False
        ...     def enable_output(self, state): pass
        >>> sm = _SM(NullTransport(), ScpiProtocol())
        >>> sm.get_source_mode()
        'VOLT'
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        """Initialise the source meter.

        Args:
            transport (BaseTransport):
                Transport layer instance.
            protocol (BaseProtocol):
                Protocol instance.
        """
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def get_source_mode(self) -> SourceMode:
        """Return the current source mode (``"VOLT"`` or ``"CURR"``).

        Returns:
            (str):
                Source mode: ``"VOLT"`` for voltage source or ``"CURR"`` for
                current source.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_source_mode(self, mode: SourceMode) -> None:
        """Set the source mode.

        Args:
            mode (str):
                ``"VOLT"`` for voltage source or ``"CURR"`` for current source.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *mode* is not ``"VOLT"`` or ``"CURR"``.
        """

    @abstractmethod
    def get_source_level(self) -> float:
        """Return the programmed source level (V or A).

        Returns:
            (float):
                Source amplitude in volts or amps depending on
                :meth:`get_source_mode`.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_source_level(self, value: float) -> None:
        """Set the source output level (V or A).

        Args:
            value (float):
                Source amplitude in volts (voltage mode) or amps (current mode).

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def get_compliance(self) -> float:
        """Return the compliance limit (A in voltage mode, V in current mode).

        Returns:
            (float):
                Compliance value in amps or volts.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_compliance(self, value: float) -> None:
        """Set the compliance limit.

        Args:
            value (float):
                Compliance in amps (voltage mode) or volts (current mode).

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *value* exceeds the instrument's maximum compliance.
        """

    @abstractmethod
    def get_nplc(self) -> float:
        """Return the integration time in power-line cycles (NPLC).

        Returns:
            (float):
                Integration time in power-line cycles.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_nplc(self, value: float) -> None:
        """Set the integration time in power-line cycles.

        Args:
            value (float):
                Integration time in power-line cycles.  Typical range is
                0.01–10.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *value* is outside the valid range.
        """

    @abstractmethod
    def measure_voltage(self) -> float:
        """Trigger a voltage measurement and return the result in volts.

        Returns:
            (float):
                Measured voltage in volts.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def measure_current(self) -> float:
        """Trigger a current measurement and return the result in amps.

        Returns:
            (float):
                Measured current in amps.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def output_enabled(self) -> bool:
        """Return ``True`` if the source output is currently enabled.

        Returns:
            (bool):
                ``True`` when the output is on, ``False`` when off.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def enable_output(self, state: bool) -> None:
        """Enable or disable the source output.

        Args:
            state (bool):
                ``True`` to enable the output, ``False`` to disable it.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    def get_measure_functions(self) -> tuple[MeasureFunction, ...]:
        """Return enabled measurement functions.

        Returns:
            (tuple[str, ...]):
                Enabled measurement function names.

        Raises:
            NotImplementedError:
                If the driver does not implement function selection.
        """
        raise NotImplementedError("This source-meter driver does not expose measurement function selection.")

    def set_measure_functions(self, functions: tuple[MeasureFunction, ...]) -> None:
        """Enable one or more measurement functions.

        Args:
            functions (tuple[str, ...]):
                Sequence of measurement function names to enable.

        Raises:
            NotImplementedError:
                If the driver does not implement function selection.
        """
        raise NotImplementedError("This source-meter driver does not expose measurement function selection.")

    def measure_resistance(self) -> float:
        """Return resistance calculated from measured voltage and current.

        Returns:
            (float):
                Resistance in ohms.

        Raises:
            ZeroDivisionError:
                If the measured current magnitude is below ``1e-12`` A.

        Notes:
            Currents with absolute magnitude smaller than
            ``_MIN_CURRENT_FOR_RESISTANCE_CALCULATION`` are treated as zero to
            avoid numerically unstable resistance values.
        """
        current = self.measure_current()
        if abs(current) < _MIN_CURRENT_FOR_RESISTANCE_CALCULATION:
            raise ZeroDivisionError("Measured current is zero; cannot calculate resistance.")
        return self.measure_voltage() / current

    def measure_power(self) -> float:
        """Return power calculated from measured voltage and current.

        Returns:
            (float):
                Electrical power in watts.
        """
        return self.measure_voltage() * self.measure_current()

    def configure_source_sweep(self, config: SourceSweepConfiguration) -> None:
        """Configure a source sweep.

        Args:
            config (SourceSweepConfiguration):
                Source sweep configuration.

        Raises:
            NotImplementedError:
                If the driver does not expose source sweep configuration.
        """
        raise NotImplementedError("This source-meter driver does not expose source sweep configuration.")

    def configure_linear_sweep(self, start: float, stop: float, points: int, *, delay: float = 0.0) -> None:
        """Configure a linear source sweep.

        Args:
            start (float):
                Sweep start value in source units.
            stop (float):
                Sweep stop value in source units.
            points (int):
                Number of points in the sweep.

        Keyword Parameters:
            delay (float):
                Source settling delay between sweep points in seconds.

        Raises:
            NotImplementedError:
                If the driver does not expose source sweep configuration.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.source_meter import SourceMeter
            >>> class _SM(SourceMeter):
            ...     def get_source_mode(self): return "VOLT"
            ...     def set_source_mode(self, mode): pass
            ...     def get_source_level(self): return 0.0
            ...     def set_source_level(self, value): pass
            ...     def get_compliance(self): return 0.0
            ...     def set_compliance(self, value): pass
            ...     def get_nplc(self): return 1.0
            ...     def set_nplc(self, value): pass
            ...     def measure_voltage(self): return 0.0
            ...     def measure_current(self): return 0.0
            ...     def output_enabled(self): return False
            ...     def enable_output(self, state): pass
            >>> _SM(NullTransport(), ScpiProtocol()).configure_linear_sweep(0.0, 1.0, 11, delay=0.01)
            Traceback (most recent call last):
            ...
            NotImplementedError: This source-meter driver does not expose source sweep configuration.
        """
        self.configure_source_sweep(
            SourceSweepConfiguration(
                start=start,
                stop=stop,
                points=points,
                spacing="LIN",
                delay=delay,
            )
        )

    def configure_log_sweep(self, start: float, stop: float, points: int, *, delay: float = 0.0) -> None:
        """Configure a logarithmic source sweep.

        Args:
            start (float):
                Sweep start value in source units.
            stop (float):
                Sweep stop value in source units.
            points (int):
                Number of points in the sweep.

        Keyword Parameters:
            delay (float):
                Source settling delay between sweep points in seconds.

        Raises:
            NotImplementedError:
                If the driver does not expose source sweep configuration.
        """
        self.configure_source_sweep(
            SourceSweepConfiguration(
                start=start,
                stop=stop,
                points=points,
                spacing="LOG",
                delay=delay,
            )
        )

    def configure_custom_sweep(self, values: tuple[float, ...], *, delay: float = 0.0) -> None:
        """Configure a custom point-by-point source sweep.

        Args:
            values (tuple[float, ...]):
                Explicit source values to program.

        Keyword Parameters:
            delay (float):
                Source settling delay between points in seconds.

        Raises:
            NotImplementedError:
                If the driver does not expose source sweep configuration.
        """
        self.configure_source_sweep(
            SourceSweepConfiguration(
                points=len(values),
                spacing="LIST",
                values=values,
                delay=delay,
            )
        )

    def set_source_delay(self, delay: float) -> None:
        """Set source delay in seconds before each measurement trigger.

        Args:
            delay (float):
                Source delay in seconds.

        Raises:
            NotImplementedError:
                If the driver does not expose source delay control.
        """
        raise NotImplementedError("This source-meter driver does not expose source delay control.")

    def get_source_delay(self) -> float:
        """Return source delay in seconds.

        Returns:
            (float):
                Source delay in seconds.

        Raises:
            NotImplementedError:
                If the driver does not expose source delay control.
        """
        raise NotImplementedError("This source-meter driver does not expose source delay control.")

    def configure_trigger_model(self, config: TriggerModelConfiguration) -> None:
        """Configure trigger and arm behaviour.

        Args:
            config (TriggerModelConfiguration):
                Trigger and arm model configuration.

        Raises:
            NotImplementedError:
                If the driver does not expose trigger model configuration.
        """
        raise NotImplementedError("This source-meter driver does not expose trigger model configuration.")

    def initiate(self) -> None:
        """Arm and initiate acquisition.

        Raises:
            NotImplementedError:
                If the driver does not expose trigger initiation.
        """
        raise NotImplementedError("This source-meter driver does not expose trigger initiation.")

    def abort(self) -> None:
        """Abort trigger execution.

        Raises:
            NotImplementedError:
                If the driver does not expose trigger abort.
        """
        raise NotImplementedError("This source-meter driver does not expose trigger abort.")

    def set_buffer_size(self, size: int) -> None:
        """Set reading buffer capacity.

        Args:
            size (int):
                Number of readings the instrument should retain.

        Raises:
            NotImplementedError:
                If the driver does not expose reading buffer control.
        """
        raise NotImplementedError("This source-meter driver does not expose reading buffer control.")

    def get_buffer_size(self) -> int:
        """Return reading buffer capacity.

        Returns:
            (int):
                Number of readings that the buffer can store.

        Raises:
            NotImplementedError:
                If the driver does not expose reading buffer control.
        """
        raise NotImplementedError("This source-meter driver does not expose reading buffer control.")

    def clear_buffer(self) -> None:
        """Clear the instrument reading buffer.

        Raises:
            NotImplementedError:
                If the driver does not expose reading buffer control.
        """
        raise NotImplementedError("This source-meter driver does not expose reading buffer control.")

    def read_buffer(self, count: int | None = None) -> tuple[float, ...]:
        """Return readings from the instrument buffer.

        Args:
            count (int | None):
                Optional count of readings to request.

        Returns:
            (tuple[float, ...]):
                Flat tuple of numeric readings from the instrument buffer.

        Raises:
            NotImplementedError:
                If the driver does not expose reading buffer control.
        """
        raise NotImplementedError("This source-meter driver does not expose reading buffer control.")
