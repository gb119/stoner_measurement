"""Keithley 6221 AC/DC precision current-source driver."""

from __future__ import annotations

from stoner_measurement.instruments.current_source import (
    CurrentSource,
    CurrentSourceCapabilities,
    CurrentSweepConfiguration,
    CurrentSweepSpacing,
    CurrentWaveform,
    PulsedSweepConfiguration,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport


class Keithley6221(CurrentSource):
    """Driver for the Keithley 6221 precision AC/DC current source.

    Provides DC source-level and compliance control plus AC waveform controls
    (waveform shape, frequency, and offset current) using SCPI commands.
    Built-in staircase sweeps (linear, logarithmic, custom list) and pulsed
    sweeps are also supported.
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
    ) -> None:
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )

    def get_source_level(self) -> float:
        """Return programmed source current in amps."""
        return float(self.query(":SOUR:CURR?"))

    def set_source_level(self, value: float) -> None:
        """Set source current in amps."""
        self.write(f":SOUR:CURR {value}")

    def get_compliance_voltage(self) -> float:
        """Return compliance voltage in volts."""
        return float(self.query(":SOUR:CURR:COMP?"))

    def set_compliance_voltage(self, value: float) -> None:
        """Set compliance voltage in volts."""
        self.write(f":SOUR:CURR:COMP {value}")

    def output_enabled(self) -> bool:
        """Return ``True`` if source output is enabled."""
        return self.query(":OUTP:STAT?") == "1"

    def enable_output(self, state: bool) -> None:
        """Enable or disable source output."""
        self.write(f":OUTP:STAT {1 if state else 0}")

    def get_waveform(self) -> CurrentWaveform:
        """Return waveform mode."""
        token = self.query(":SOUR:WAVE:FUNC?").strip().upper()
        if token.startswith("SIN"):
            return CurrentWaveform.SINE
        return CurrentWaveform(token)

    def set_waveform(self, waveform: CurrentWaveform) -> None:
        """Set waveform mode."""
        token = "SIN" if waveform is CurrentWaveform.SINE else waveform.value
        self.write(f":SOUR:WAVE:FUNC {token}")

    def get_frequency(self) -> float:
        """Return AC waveform frequency in Hz."""
        return float(self.query(":SOUR:WAVE:FREQ?"))

    def set_frequency(self, value: float) -> None:
        """Set AC waveform frequency in Hz."""
        if value <= 0.0:
            raise ValueError("Frequency must be positive.")
        self.write(f":SOUR:WAVE:FREQ {value}")

    def get_offset_current(self) -> float:
        """Return AC waveform DC offset current in amps."""
        return float(self.query(":SOUR:WAVE:OFFS?"))

    def set_offset_current(self, value: float) -> None:
        """Set AC waveform DC offset current in amps."""
        self.write(f":SOUR:WAVE:OFFS {value}")

    def configure_sweep(self, config: CurrentSweepConfiguration) -> None:
        """Configure a built-in current sweep.

        Args:
            config (CurrentSweepConfiguration):
                Sweep configuration.  For :attr:`~CurrentSweepSpacing.LIST`
                spacing, ``config.values`` must be non-empty.

        Raises:
            ValueError:
                If ``config.spacing`` is ``LIST`` and ``config.values`` is
                empty or ``None``.
        """
        self.write(f":SOUR:SWE:SPAC {config.spacing.value}")
        if config.spacing is CurrentSweepSpacing.LIST:
            if not config.values:
                raise ValueError("LIST sweep requires non-empty values.")
            csv = ",".join(str(v) for v in config.values)
            self.write(f":SOUR:LIST:CURR {csv}")
            self.write(f":SOUR:SWE:POIN {len(config.values)}")
        else:
            self.write(f":SOUR:SWE:STAR {config.start}")
            self.write(f":SOUR:SWE:STOP {config.stop}")
            self.write(f":SOUR:SWE:POIN {config.points}")
        self.write(f":SOUR:DEL {config.delay}")
        if config.count != 1:
            self.write(f":SOUR:SWE:COUN {config.count}")

    def sweep_start(self) -> None:
        """Arm the configured sweep, making it ready for triggering."""
        self.write(":SOUR:SWE:ARM")

    def sweep_abort(self) -> None:
        """Abort a running or armed sweep."""
        self.write(":SOUR:SWE:ABOR")

    def configure_pulsed_sweep(
        self,
        sweep: CurrentSweepConfiguration,
        pulse: PulsedSweepConfiguration,
    ) -> None:
        """Configure a pulsed current sweep.

        Calls :meth:`configure_sweep` to programme the sweep points, then
        enables pulsed mode and sets pulse timing parameters.

        Args:
            sweep (CurrentSweepConfiguration):
                Sweep point configuration.
            pulse (PulsedSweepConfiguration):
                Pulse timing and baseline current.  ``pulse.width`` and
                ``pulse.off_time`` must both be positive.

        Raises:
            ValueError:
                If ``pulse.width`` or ``pulse.off_time`` is not positive.
        """
        if pulse.width <= 0.0:
            raise ValueError("Pulse width must be positive.")
        if pulse.off_time <= 0.0:
            raise ValueError("Pulse off_time must be positive.")
        self.configure_sweep(sweep)
        self.write(":SOUR:PULS:STAT 1")
        self.write(f":SOUR:PULS:WIDT {pulse.width}")
        self.write(f":SOUR:PULS:DEL {pulse.off_time}")
        self.write(f":SOUR:PULS:CURR:LOW {pulse.low_level}")

    def get_capabilities(self) -> CurrentSourceCapabilities:
        """Return static capabilities for Keithley 6221."""
        return CurrentSourceCapabilities(
            has_waveform_selection=True,
            has_frequency_control=True,
            has_offset_current=True,
            has_balanced_outputs=False,
            has_sweep=True,
            has_pulsed_sweep=True,
            channel_count=1,
        )
