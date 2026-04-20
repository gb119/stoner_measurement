"""Abstract base class for source-meter instruments.

Defines the common interface for combined voltage/current source and
measurement instruments (SMUs).  Concrete subclasses (e.g. Keithley 2400,
Keithley 2450) implement the abstract methods for the specific instrument.

The interface is divided into three tiers:

**Core abstract methods** — must be implemented by every concrete driver:
    source mode, source level, compliance, integration time (NPLC),
    single-shot voltage/current measurement, output enable, and capability
    reporting.

**Concrete composite methods** — default implementations built from the core
    abstracts: :meth:`measure_resistance`, :meth:`measure_power`, and the
    sweep convenience wrappers :meth:`configure_linear_sweep`,
    :meth:`configure_log_sweep`, and :meth:`configure_custom_sweep`.

**Optional methods** — raise :class:`NotImplementedError` by default; override
    in drivers that support the feature (check via
    :meth:`get_capabilities` before calling): measurement function selection,
    source sweep configuration, source delay, trigger/arm model, and reading
    buffer control.
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


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SourceMode(Enum):
    """Source output mode of an SMU.

    Attributes:
        VOLT:
            Voltage source mode; the instrument outputs a programmed voltage
            and measures current (or resistance).
        CURR:
            Current source mode; the instrument outputs a programmed current
            and measures voltage (or resistance).
    """

    VOLT = "VOLT"
    CURR = "CURR"


class MeasureFunction(Enum):
    """Measurement function selected on an SMU.

    Attributes:
        VOLT:
            Voltage measurement.
        CURR:
            Current measurement.
        RES:
            Resistance measurement (4-wire or 2-wire depending on driver
            configuration).
        POW:
            Power (derived from simultaneous voltage and current readings).
    """

    VOLT = "VOLT"
    CURR = "CURR"
    RES = "RES"
    POW = "POW"


class SweepSpacing(Enum):
    """Point-spacing mode for a built-in source sweep.

    Attributes:
        LIN:
            Linearly spaced sweep points from *start* to *stop*.
        LOG:
            Logarithmically spaced sweep points from *start* to *stop*.
        LIST:
            Arbitrary point list supplied in
            :attr:`SourceSweepConfiguration.values`.
    """

    LIN = "LIN"
    LOG = "LOG"
    LIST = "LIST"


class TriggerSource(Enum):
    """Trigger or arm source for a trigger-model configuration.

    Attributes:
        IMM:
            Immediate (internal) — the layer completes as soon as it is
            entered.
        BUS:
            IEEE-488 / GPIB bus trigger (``*TRG`` or ``GET``).
        EXT:
            External hardware trigger input.
        TLIN:
            Trigger link (LAN or digital I/O trigger bus, instrument-specific).
        TIM:
            Internal timer-based trigger.
    """

    IMM = "IMM"
    BUS = "BUS"
    EXT = "EXT"
    TLIN = "TLIN"
    TIM = "TIM"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

#: Minimum current magnitude used for resistance calculation.
_MIN_CURRENT_FOR_RESISTANCE_CALCULATION = 1e-12


@dataclass(frozen=True)
class SourceSweepConfiguration:
    """Configuration for a source sweep.

    Attributes:
        start (float):
            Sweep start value in source units.  Ignored for list sweeps.
        stop (float):
            Sweep stop value in source units.  Ignored for list sweeps.
        points (int):
            Number of sweep points.  For list sweeps this is inferred from
            ``len(values)`` by convenience wrappers but must be supplied
            explicitly when constructing this dataclass directly.
        spacing (SweepSpacing):
            Point-spacing mode.  Defaults to :attr:`~SweepSpacing.LIN`.
        values (tuple[float, ...] | None):
            Explicit source values for :attr:`~SweepSpacing.LIST` sweeps.
            Ignored for linear and logarithmic sweeps.
        delay (float):
            Source settling delay between sweep points in seconds.  A value
            of ``0.0`` disables the added delay.

    Notes:
        Default ``start``, ``stop``, and ``points`` values are placeholders.
        Callers should provide values appropriate for the selected spacing mode.
        For list sweeps, use ``values`` and set ``points`` to ``len(values)``.
        The default ``delay`` of ``0.0`` seconds disables added settling time.
    """

    start: float = 0.0
    stop: float = 0.0
    points: int = 0
    spacing: SweepSpacing = SweepSpacing.LIN
    values: tuple[float, ...] | None = None
    delay: float = 0.0


@dataclass(frozen=True)
class TriggerModelConfiguration:
    """Configuration for simple trigger and arm models.

    Attributes:
        trigger_source (TriggerSource):
            Source that advances the trigger layer.  Defaults to
            :attr:`~TriggerSource.IMM`.
        trigger_count (int):
            Number of times the trigger layer executes per arm.  Defaults
            to ``1``.
        trigger_delay (float):
            Delay in seconds inserted before each measurement trigger.
            Defaults to ``0.0``.
        arm_source (TriggerSource):
            Source that advances the arm layer.  Defaults to
            :attr:`~TriggerSource.IMM`.
        arm_count (int):
            Number of times the arm layer executes.  Defaults to ``1``.
    """

    trigger_source: TriggerSource = TriggerSource.IMM
    trigger_count: int = 1
    trigger_delay: float = 0.0
    arm_source: TriggerSource = TriggerSource.IMM
    arm_count: int = 1


@dataclass(frozen=True)
class SourceMeterCapabilities:
    """Static capability descriptor for a source-meter driver.

    Attributes:
        has_function_selection (bool):
            ``True`` if the driver supports selecting measurement functions
            via :meth:`~SourceMeter.get_measure_functions` and
            :meth:`~SourceMeter.set_measure_functions`.
        has_sweep (bool):
            ``True`` if the driver supports built-in source sweeps via
            :meth:`~SourceMeter.configure_source_sweep`.
        has_source_delay (bool):
            ``True`` if the driver supports a programmable source delay via
            :meth:`~SourceMeter.get_source_delay` and
            :meth:`~SourceMeter.set_source_delay`.
        has_trigger_model (bool):
            ``True`` if the driver supports trigger and arm model
            configuration via :meth:`~SourceMeter.configure_trigger_model`,
            :meth:`~SourceMeter.initiate`, and :meth:`~SourceMeter.abort`.
        has_buffer (bool):
            ``True`` if the driver supports a reading buffer via
            :meth:`~SourceMeter.set_buffer_size`,
            :meth:`~SourceMeter.get_buffer_size`,
            :meth:`~SourceMeter.clear_buffer`, and
            :meth:`~SourceMeter.read_buffer`.
    """

    has_function_selection: bool = False
    has_sweep: bool = False
    has_source_delay: bool = False
    has_trigger_model: bool = False
    has_buffer: bool = False


class SourceMeter(BaseInstrument):
    """Abstract base class for source-measure unit (SMU) instruments.

    A source-meter can source voltage or current while simultaneously
    measuring the complementary quantity, making it suitable for
    current-voltage (I–V) characterisation.

    Subclasses must implement the core abstract methods.  Optional capability
    methods raise :class:`NotImplementedError` by default; drivers override
    only those methods that their hardware supports.  Callers should consult
    :meth:`get_capabilities` to determine which optional features are available
    before invoking them.

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol instance.

    Examples:
        >>> # Demonstrate interface using a minimal concrete implementation
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import ScpiProtocol
        >>> from stoner_measurement.instruments.source_meter import (
        ...     SourceMeter, SourceMode, SourceMeterCapabilities,
        ... )
        >>> class _SM(SourceMeter):
        ...     def get_source_mode(self): return SourceMode.VOLT
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
        ...     def get_capabilities(self): return SourceMeterCapabilities()
        >>> sm = _SM(NullTransport(), ScpiProtocol())
        >>> sm.get_source_mode()
        <SourceMode.VOLT: 'VOLT'>
        >>> sm.get_capabilities().has_sweep
        False
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
        """Return the current source mode.

        Returns:
            (SourceMode):
                :attr:`~SourceMode.VOLT` if the instrument is sourcing voltage,
                :attr:`~SourceMode.CURR` if it is sourcing current.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_source_mode(self, mode: SourceMode) -> None:
        """Set the source mode.

        Args:
            mode (SourceMode):
                :attr:`~SourceMode.VOLT` for voltage source or
                :attr:`~SourceMode.CURR` for current source.

        Raises:
            ConnectionError:
                If the transport is not open.
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

    @abstractmethod
    def get_capabilities(self) -> SourceMeterCapabilities:
        """Return the static capability descriptor for this SMU driver.

        Returns:
            (SourceMeterCapabilities):
                Descriptor advertising which optional feature groups are
                supported by this driver.

        Examples:
            >>> caps = sm.get_capabilities()  # doctest: +SKIP
            >>> caps.has_sweep  # doctest: +SKIP
            False
        """

    # ------------------------------------------------------------------
    # Optional methods — measurement function selection
    # ------------------------------------------------------------------

    def get_measure_functions(self) -> tuple[MeasureFunction, ...]:
        """Return enabled measurement functions.

        Returns:
            (tuple[MeasureFunction, ...]):
                Enabled measurement functions.

        Raises:
            NotImplementedError:
                If the driver does not support function selection.
                Check :attr:`SourceMeterCapabilities.has_function_selection`
                before calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support measurement function selection. "
            "Check get_capabilities().has_function_selection before calling this method."
        )

    def set_measure_functions(self, functions: tuple[MeasureFunction, ...]) -> None:
        """Enable one or more measurement functions.

        Args:
            functions (tuple[MeasureFunction, ...]):
                Sequence of measurement functions to enable.

        Raises:
            NotImplementedError:
                If the driver does not support function selection.
                Check :attr:`SourceMeterCapabilities.has_function_selection`
                before calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support measurement function selection. "
            "Check get_capabilities().has_function_selection before calling this method."
        )

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
                If the driver does not support source sweep configuration.
                Check :attr:`SourceMeterCapabilities.has_sweep` before calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support source sweep configuration. "
            "Check get_capabilities().has_sweep before calling this method."
        )

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
                If the driver does not support source sweep configuration.
                Check :attr:`SourceMeterCapabilities.has_sweep` before calling.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.source_meter import (
            ...     SourceMeter, SourceMode, SourceMeterCapabilities,
            ... )
            >>> class _SM(SourceMeter):
            ...     def get_source_mode(self): return SourceMode.VOLT
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
            ...     def get_capabilities(self): return SourceMeterCapabilities()
            >>> _SM(NullTransport(), ScpiProtocol()).configure_linear_sweep(0.0, 1.0, 11, delay=0.01)  # doctest: +ELLIPSIS
            Traceback (most recent call last):
            ...
            NotImplementedError: _SM does not support source sweep configuration. ...
        """
        self.configure_source_sweep(
            SourceSweepConfiguration(
                start=start,
                stop=stop,
                points=points,
                spacing=SweepSpacing.LIN,
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
                If the driver does not support source sweep configuration.
                Check :attr:`SourceMeterCapabilities.has_sweep` before calling.
        """
        self.configure_source_sweep(
            SourceSweepConfiguration(
                start=start,
                stop=stop,
                points=points,
                spacing=SweepSpacing.LOG,
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
                If the driver does not support source sweep configuration.
                Check :attr:`SourceMeterCapabilities.has_sweep` before calling.
        """
        self.configure_source_sweep(
            SourceSweepConfiguration(
                points=len(values),
                spacing=SweepSpacing.LIST,
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
                If the driver does not support source delay control.
                Check :attr:`SourceMeterCapabilities.has_source_delay` before
                calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support source delay control. "
            "Check get_capabilities().has_source_delay before calling this method."
        )

    def get_source_delay(self) -> float:
        """Return source delay in seconds.

        Returns:
            (float):
                Source delay in seconds.

        Raises:
            NotImplementedError:
                If the driver does not support source delay control.
                Check :attr:`SourceMeterCapabilities.has_source_delay` before
                calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support source delay control. "
            "Check get_capabilities().has_source_delay before calling this method."
        )

    def configure_trigger_model(self, config: TriggerModelConfiguration) -> None:
        """Configure trigger and arm behaviour.

        Args:
            config (TriggerModelConfiguration):
                Trigger and arm model configuration.

        Raises:
            NotImplementedError:
                If the driver does not support trigger model configuration.
                Check :attr:`SourceMeterCapabilities.has_trigger_model` before
                calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger model configuration. "
            "Check get_capabilities().has_trigger_model before calling this method."
        )

    def initiate(self) -> None:
        """Arm and initiate acquisition.

        Raises:
            NotImplementedError:
                If the driver does not support trigger initiation.
                Check :attr:`SourceMeterCapabilities.has_trigger_model` before
                calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger initiation. "
            "Check get_capabilities().has_trigger_model before calling this method."
        )

    def abort(self) -> None:
        """Abort trigger execution.

        Raises:
            NotImplementedError:
                If the driver does not support trigger abort.
                Check :attr:`SourceMeterCapabilities.has_trigger_model` before
                calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger abort. "
            "Check get_capabilities().has_trigger_model before calling this method."
        )

    def set_buffer_size(self, size: int) -> None:
        """Set reading buffer capacity.

        Args:
            size (int):
                Number of readings the instrument should retain.

        Raises:
            NotImplementedError:
                If the driver does not support reading buffer control.
                Check :attr:`SourceMeterCapabilities.has_buffer` before calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer control. "
            "Check get_capabilities().has_buffer before calling this method."
        )

    def get_buffer_size(self) -> int:
        """Return reading buffer capacity.

        Returns:
            (int):
                Number of readings that the buffer can store.

        Raises:
            NotImplementedError:
                If the driver does not support reading buffer control.
                Check :attr:`SourceMeterCapabilities.has_buffer` before calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer control. "
            "Check get_capabilities().has_buffer before calling this method."
        )

    def clear_buffer(self) -> None:
        """Clear the instrument reading buffer.

        Raises:
            NotImplementedError:
                If the driver does not support reading buffer control.
                Check :attr:`SourceMeterCapabilities.has_buffer` before calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer control. "
            "Check get_capabilities().has_buffer before calling this method."
        )

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
                If the driver does not support reading buffer control.
                Check :attr:`SourceMeterCapabilities.has_buffer` before calling.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer control. "
            "Check get_capabilities().has_buffer before calling this method."
        )
