"""Leybold pressure-gauge controller drivers."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.pressure_controller import (
    PressureControllerCapabilities,
    PressureGaugeController,
    PressureReading,
    PressureRelayState,
    PressureSetpoint,
    PressureStatus,
    PressureUnit,
)
from stoner_measurement.instruments.protocol.leybold import ACK, ENQ, NAK, LeyboldCenterProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

_STATUS_MAP = {
    0: PressureStatus.OK,
    1: PressureStatus.UNDERRANGE,
    2: PressureStatus.OVERRANGE,
    3: PressureStatus.TRANSMITTER_ERROR,
    4: PressureStatus.SWITCHED_OFF,
    5: PressureStatus.NO_TRANSMITTER,
    6: PressureStatus.IDENTIFICATION_ERROR,
    7: PressureStatus.ITR_ERROR,
}
_UNIT_FROM_CODE = {0: PressureUnit.MBAR, 1: PressureUnit.TORR, 2: PressureUnit.PASCAL, 3: PressureUnit.MICRON}
_CODE_FROM_UNIT = {unit: code for code, unit in _UNIT_FROM_CODE.items()}


class LeyboldCenterThree(PressureGaugeController):
    """Driver for the Leybold CENTER THREE RS232 gauge controller."""

    DISPLAY_NAME = "Leybold CENTER THREE"
    _CAPABILITIES: ClassVar[PressureControllerCapabilities] = PressureControllerCapabilities(
        serial=True,
        pressure_query=True,
        remote_setpoints=True,
        remote_gauge_control=True,
        pump_control=False,
        analogue_only=False,
        max_channels=3,
        max_relays=6,
    )

    def __init__(self, transport: BaseTransport, protocol: LeyboldCenterProtocol | None = None) -> None:
        """Initialise the CENTER THREE driver."""
        super().__init__(transport=transport, protocol=protocol or LeyboldCenterProtocol())

    def identify(self) -> str:
        """Return the firmware string reported by ``PNR``."""
        return self._transaction("PNR")

    def get_firmware(self) -> str:
        """Return the firmware string reported by ``PNR``."""
        return self.identify()

    def identify_transmitters(self) -> dict[int, str]:
        """Return transmitter IDs for channels 1 through 3."""
        values = self._split(self._transaction("TID"))
        return {channel: values[channel - 1] for channel in range(1, min(len(values), 3) + 1)}

    def get_gauge_type(self, channel: int) -> str | None:
        """Return the transmitter ID for *channel*."""
        self._validate_channel(channel)
        value = self.identify_transmitters().get(channel)
        return None if value in {None, "noSen", "noid"} else value

    def read_pressure(self, channel: int) -> PressureReading:
        """Read one pressure channel using ``PR1``/``PR2``/``PR3``."""
        self._validate_channel(channel)
        return self._parse_pressure(channel, self._split(self._transaction(f"PR{channel}")))

def read_all_pressures(self) -> dict[int, PressureReading]:
        """Read all pressure channels using ``PRX``."""
        values = self._split(self._transaction("PRX"))
        if len(values) != 6:
            raise InstrumentError(f"Expected 6 PRX fields, received {len(values)}")

        unit = self.get_unit()
        readings: dict[int, PressureReading] = {}
        for channel in range(1, 4):
            raw_status = int(values[(channel - 1) * 2])
            status = _STATUS_MAP.get(raw_status, PressureStatus.UNKNOWN)
            raw_value = values[(channel - 1) * 2 + 1]
            value = float(raw_value) if status is PressureStatus.OK else None
            readings[channel] = PressureReading(channel, value, unit, status, raw_status)
        return readings

    def get_unit(self) -> PressureUnit:
        """Return the currently selected display pressure unit."""
        return _UNIT_FROM_CODE.get(int(self._transaction("UNI")), PressureUnit.MBAR)

    def set_unit(self, unit: PressureUnit | str) -> PressureUnit:
        """Set and return the display pressure unit."""
        pressure_unit = PressureUnit(unit) if isinstance(unit, str) else unit
        return _UNIT_FROM_CODE[int(self._transaction(f"UNI,{_CODE_FROM_UNIT[pressure_unit]}"))]

    def set_gauge_on(self, channel: int, enabled: bool) -> None:
        """Switch a gauge channel on or off using ``SEN``."""
        self._validate_channel(channel)
        self._transaction(f"SEN,{channel - 1},{int(enabled)}")

    def zero_gauge(self, channel: int) -> None:
        """Zero one gauge channel using ``OFC``."""
        self._validate_channel(channel)
        self._transaction(f"OFC,{channel - 1}")

    def degas_gauge(self, channel: int, enabled: bool) -> None:
        """Enable or disable degas using ``DGS``."""
        self._validate_channel(channel)
        self._transaction(f"DGS,{channel - 1},{int(enabled)}")

    def get_setpoint(self, index: int) -> PressureSetpoint:
        """Return setpoint *index* using ``SPn``."""
        self._validate_relay(index)
        values = self._split(self._transaction(f"SP{index}"))
        if len(values) < 3:
            raise InstrumentError(f"Expected at least 3 SP fields, received {len(values)}")
        source = int(values[0]) + 1
        return PressureSetpoint(source, float(values[1]), float(values[2]), self.get_unit())

    def set_setpoint(self, index: int, setpoint: PressureSetpoint) -> None:
        """Update setpoint *index* using ``SPn``."""
        self._validate_relay(index)
        source = 0 if setpoint.source_channel is None else setpoint.source_channel - 1
        self._transaction(f"SP{index},{source},{setpoint.lower:.5E},{setpoint.upper:.5E}")

    def read_relay(self, index: int) -> PressureRelayState:
        """Return relay state using ``REL``."""
        self._validate_relay(index)
        values = self._split(self._transaction("REL"))
        raw = values[index - 1]
        return PressureRelayState(index=index, state=bool(int(raw)), raw_state=raw)

    def set_relay(self, index: int, enabled: bool) -> None:
        """Enable or disable a relay using ``RLY``."""
        self._validate_relay(index)
        self._transaction(f"RLY,{index - 1},{int(enabled)}")

    def get_error_status(self) -> str:
        """Return the raw four-bit ``ERR`` status string."""
        return self._transaction("ERR")

    def get_capabilities(self) -> PressureControllerCapabilities:
        """Return static CENTER THREE capabilities."""
        return self._CAPABILITIES

    def _transaction(self, command: str) -> str:
        """Run the Leybold ACK/NAK + ENQ transaction and return payload text."""
        with self._lock:
            self.transport.write(self.protocol.format_command(command))
            acknowledgement = self.transport.read_until(b"\n").strip()
            if acknowledgement.startswith(NAK):
                self.transport.write(ENQ)
                error = self.protocol.parse_response(self.transport.read_until(b"\n"), command=command)
                raise InstrumentError(f"Leybold command rejected: {error}", command=command)
            if not acknowledgement.startswith(ACK):
                raise InstrumentError(f"Expected ACK from Leybold controller, received {acknowledgement!r}", command=command)
            self.transport.write(ENQ)
            return self.protocol.parse_response(self.transport.read_until(b"\n"), command=command)

    def _parse_pressure(self, channel: int, fields: list[str]) -> PressureReading:
        if len(fields) != 2:
            raise InstrumentError(f"Expected status and pressure for channel {channel}")
        raw_status = int(fields[0])
        status = _STATUS_MAP.get(raw_status, PressureStatus.UNKNOWN)
        value = float(fields[1]) if status is PressureStatus.OK else None
        return PressureReading(channel, value, self.get_unit(), status, raw_status)

    @staticmethod
    def _split(response: str) -> list[str]:
        return [field.strip() for field in response.split(",") if field.strip()]

    @classmethod
    def _validate_channel(cls, channel: int) -> None:
        if not 1 <= channel <= cls._CAPABILITIES.max_channels:
            raise ValueError("channel must be in the range 1..3")

    @classmethod
    def _validate_relay(cls, index: int) -> None:
        if not 1 <= index <= cls._CAPABILITIES.max_relays:
            raise ValueError("relay/setpoint index must be in the range 1..6")


class LeyboldDisplayThree(PressureGaugeController):
    """Analogue-I/O driver facade for the Leybold DISPLAY THREE.

    The DISPLAY THREE manual does not document a serial pressure-query protocol;
    this class therefore accepts user-supplied analogue voltage readers and
    conversion functions for each channel.
    """

    DISPLAY_NAME = "Leybold DISPLAY THREE"
    _CAPABILITIES: ClassVar[PressureControllerCapabilities] = PressureControllerCapabilities(
        serial=False,
        pressure_query=True,
        remote_setpoints=False,
        remote_gauge_control=False,
        pump_control=False,
        analogue_only=True,
        max_channels=3,
        max_relays=3,
    )

    def __init__(
        self,
        transport: BaseTransport,
        voltage_reader: Callable[[int], float],
        voltage_to_pressure: Callable[[int, float], float],
        protocol: LeyboldCenterProtocol | None = None,
        *,
        unit: PressureUnit = PressureUnit.MBAR,
    ) -> None:
        """Initialise the analogue DISPLAY THREE facade."""
        super().__init__(transport=transport, protocol=protocol or LeyboldCenterProtocol())
        self._voltage_reader = voltage_reader
        self._voltage_to_pressure = voltage_to_pressure
        self._unit = unit

    def identify(self) -> str:
        """Return a fixed identity string for the analogue facade."""
        return "Leybold DISPLAY THREE (analogue facade)"

    def read_pressure(self, channel: int) -> PressureReading:
        """Read and convert an analogue pressure output for *channel*."""
        self._validate_channel(channel)
        voltage = self._voltage_reader(channel)
        return PressureReading(channel, self._voltage_to_pressure(channel, voltage), self._unit, PressureStatus.OK, "analogue")

    def read_all_pressures(self) -> dict[int, PressureReading]:
        """Read all three analogue pressure channels."""
        return {channel: self.read_pressure(channel) for channel in range(1, 4)}

    def get_gauge_type(self, channel: int) -> str | None:
        """DISPLAY THREE gauge type is configured on the front panel."""
        self._validate_channel(channel)
        return None

    def set_gauge_on(self, channel: int, enabled: bool) -> None:
        """Remote gauge switching is not available via the display unit."""
        _ = enabled
        self._validate_channel(channel)
        raise NotImplementedError("DISPLAY THREE does not provide documented remote gauge switching")

    def zero_gauge(self, channel: int) -> None:
        """Remote zero is not available via the display unit."""
        self._validate_channel(channel)
        raise NotImplementedError("DISPLAY THREE zeroing is front-panel/transmitter specific")

    def degas_gauge(self, channel: int, enabled: bool) -> None:
        """Remote degas is not available via the display unit."""
        _ = enabled
        self._validate_channel(channel)
        raise NotImplementedError("DISPLAY THREE does not provide documented remote degas control")

    def get_setpoint(self, index: int) -> PressureSetpoint:
        """Remote setpoint reads are not available via the display unit."""
        self._validate_relay(index)
        raise NotImplementedError("DISPLAY THREE setpoints are front-panel configured")

    def set_setpoint(self, index: int, setpoint: PressureSetpoint) -> None:
        """Remote setpoint writes are not available via the display unit."""
        _ = setpoint
        self._validate_relay(index)
        raise NotImplementedError("DISPLAY THREE setpoints are front-panel configured")

    def read_relay(self, index: int) -> PressureRelayState:
        """Remote relay reads require external digital I/O."""
        self._validate_relay(index)
        raise NotImplementedError("DISPLAY THREE relay state requires external digital I/O")

    def set_relay(self, index: int, enabled: bool) -> None:
        """Remote relay writes are not available via the display unit."""
        _ = enabled
        self._validate_relay(index)
        raise NotImplementedError("DISPLAY THREE relay control is front-panel configured")

    def get_capabilities(self) -> PressureControllerCapabilities:
        """Return static DISPLAY THREE capabilities."""
        return self._CAPABILITIES

    @classmethod
    def _validate_channel(cls, channel: int) -> None:
        if not 1 <= channel <= cls._CAPABILITIES.max_channels:
            raise ValueError("channel must be in the range 1..3")

    @classmethod
    def _validate_relay(cls, index: int) -> None:
        if not 1 <= index <= cls._CAPABILITIES.max_relays:
            raise ValueError("relay index must be in the range 1..3")
