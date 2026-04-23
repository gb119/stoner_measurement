"""Lakeshore current-source drivers."""

from __future__ import annotations

from stoner_measurement.instruments.current_source import (
    CurrentSource,
    CurrentSourceCapabilities,
    CurrentSweepConfiguration,
    CurrentSweepSpacing,
    CurrentWaveform,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

_M81_DEFAULT_POSITIVE_CHANNEL = 1
_M81_DEFAULT_NEGATIVE_CHANNEL = 2


class LakeshoreM81CurrentSource(CurrentSource):
    """Driver for the Lakeshore M81 balanced current-source outputs.

    Models the M81 as a differential current-source backed by two matched
    output channels. The public source-level API uses channel 1 amplitude and
    mirrors channel 2 with opposite polarity for balanced drive.  Built-in
    sweeps (linear, logarithmic, custom list) are also supported; the sweep
    is mirrored across both channels so the differential current follows the
    programmed profile.
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
    ) -> None:
        """Initialise the Lakeshore M81 current-source driver, defaulting to :class:`ScpiProtocol`."""
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )

    @staticmethod
    def _validate_channel(channel: int) -> None:
        """Validate M81 channel index."""
        if channel not in (_M81_DEFAULT_POSITIVE_CHANNEL, _M81_DEFAULT_NEGATIVE_CHANNEL):
            raise ValueError("M81 supports balanced current channels 1 and 2.")

    def get_channel_level(self, channel: int) -> float:
        """Return programmed current for a specific channel in amps."""
        self._validate_channel(channel)
        return float(self.query(f":SOUR{channel}:CURR?"))

    def set_channel_level(self, channel: int, value: float) -> None:
        """Set programmed current for a specific channel in amps."""
        self._validate_channel(channel)
        self.write(f":SOUR{channel}:CURR {value}")

    def get_source_level(self) -> float:
        """Return differential source current amplitude in amps."""
        return self.get_channel_level(_M81_DEFAULT_POSITIVE_CHANNEL)

    def set_source_level(self, value: float) -> None:
        """Set differential source current amplitude in amps."""
        self.set_channel_level(_M81_DEFAULT_POSITIVE_CHANNEL, value)
        self.set_channel_level(_M81_DEFAULT_NEGATIVE_CHANNEL, -value)

    def get_compliance_voltage(self) -> float:
        """Return compliance voltage in volts."""
        return float(self.query(":SOUR1:CURR:COMP?"))

    def set_compliance_voltage(self, value: float) -> None:
        """Set compliance voltage in volts for both channels."""
        self.write(f":SOUR1:CURR:COMP {value}")
        self.write(f":SOUR2:CURR:COMP {value}")

    def output_enabled(self) -> bool:
        """Return ``True`` if both balanced outputs are enabled."""
        return self.query(":OUTP1:STAT?") == "1" and self.query(":OUTP2:STAT?") == "1"

    def enable_output(self, state: bool) -> None:
        """Enable or disable both balanced outputs."""
        bit = 1 if state else 0
        self.write(f":OUTP1:STAT {bit}")
        self.write(f":OUTP2:STAT {bit}")

    def get_waveform(self) -> CurrentWaveform:
        """Return waveform mode."""
        token = self.query(":SOUR1:FUNC?").strip().upper()
        if token.startswith("SIN"):
            return CurrentWaveform.SINE
        return CurrentWaveform(token)

    def set_waveform(self, waveform: CurrentWaveform) -> None:
        """Set waveform mode for both channels."""
        token = "SIN" if waveform is CurrentWaveform.SINE else waveform.value
        self.write(f":SOUR1:FUNC {token}")
        self.write(f":SOUR2:FUNC {token}")

    def get_frequency(self) -> float:
        """Return waveform frequency in Hz."""
        return float(self.query(":SOUR1:FREQ?"))

    def set_frequency(self, value: float) -> None:
        """Set waveform frequency in Hz for both channels."""
        if value <= 0.0:
            raise ValueError("Frequency must be positive.")
        self.write(f":SOUR1:FREQ {value}")
        self.write(f":SOUR2:FREQ {value}")

    def get_offset_current(self) -> float:
        """Return waveform offset current in amps."""
        return float(self.query(":SOUR1:CURR:OFFS?"))

    def set_offset_current(self, value: float) -> None:
        """Set waveform offset current in amps for both channels."""
        self.write(f":SOUR1:CURR:OFFS {value}")
        self.write(f":SOUR2:CURR:OFFS {-value}")

    def configure_sweep(self, config: CurrentSweepConfiguration) -> None:
        """Configure a built-in balanced current sweep.

        Channel 1 is programmed with the positive sense of the sweep;
        channel 2 is programmed with the mirrored (negated) profile so that
        the differential output follows the intended sweep.

        Args:
            config (CurrentSweepConfiguration):
                Sweep configuration.  For :attr:`~CurrentSweepSpacing.LIST`
                spacing, ``config.values`` must be non-empty.

        Raises:
            ValueError:
                If ``config.spacing`` is ``LIST`` and ``config.values`` is
                empty or ``None``.
        """
        if config.spacing is CurrentSweepSpacing.LIST:
            if not config.values:
                raise ValueError("LIST sweep requires non-empty values.")
            for ch, sign in ((_M81_DEFAULT_POSITIVE_CHANNEL, 1.0), (_M81_DEFAULT_NEGATIVE_CHANNEL, -1.0)):
                csv = ",".join(str(v * sign) for v in config.values)
                self.write(f":SOUR{ch}:SWE:MODE {config.spacing.value}")
                self.write(f":SOUR{ch}:SWE:CUST:LIST {csv}")
                self.write(f":SOUR{ch}:SWE:NPTS {len(config.values)}")
        else:
            for ch, sign in ((_M81_DEFAULT_POSITIVE_CHANNEL, 1.0), (_M81_DEFAULT_NEGATIVE_CHANNEL, -1.0)):
                self.write(f":SOUR{ch}:SWE:MODE {config.spacing.value}")
                self.write(f":SOUR{ch}:SWE:STAR {config.start * sign}")
                self.write(f":SOUR{ch}:SWE:STOP {config.stop * sign}")
                self.write(f":SOUR{ch}:SWE:NPTS {config.points}")
        if config.delay:
            for ch in (_M81_DEFAULT_POSITIVE_CHANNEL, _M81_DEFAULT_NEGATIVE_CHANNEL):
                self.write(f":SOUR{ch}:SWE:DEL {config.delay}")
        if config.count != 1:
            for ch in (_M81_DEFAULT_POSITIVE_CHANNEL, _M81_DEFAULT_NEGATIVE_CHANNEL):
                self.write(f":SOUR{ch}:SWE:COUN {config.count}")

    def sweep_start(self) -> None:
        """Arm the configured balanced sweep, making it ready for triggering."""
        for ch in (_M81_DEFAULT_POSITIVE_CHANNEL, _M81_DEFAULT_NEGATIVE_CHANNEL):
            self.write(f":SOUR{ch}:SWE:ARM")

    def sweep_abort(self) -> None:
        """Abort a running or armed balanced sweep."""
        for ch in (_M81_DEFAULT_POSITIVE_CHANNEL, _M81_DEFAULT_NEGATIVE_CHANNEL):
            self.write(f":SOUR{ch}:SWE:ABOR")

    def get_capabilities(self) -> CurrentSourceCapabilities:
        """Return static capabilities for Lakeshore M81 current source."""
        return CurrentSourceCapabilities(
            has_waveform_selection=True,
            has_frequency_control=True,
            has_offset_current=True,
            has_balanced_outputs=True,
            has_sweep=True,
            has_pulsed_sweep=False,
            channel_count=2,
        )
