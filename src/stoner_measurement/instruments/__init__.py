"""Instrument driver framework for stoner_measurement.

Provides a two-layer composition architecture for communicating with
laboratory instruments:

**Transport layer** (physical byte-level I/O):

* :class:`~stoner_measurement.instruments.transport.BaseTransport` — abstract base
* :class:`~stoner_measurement.instruments.transport.SerialTransport` — RS-232/RS-485 via pyserial
* :class:`~stoner_measurement.instruments.transport.EthernetTransport` — TCP/IP socket
* :class:`~stoner_measurement.instruments.transport.GpibTransport` — GPIB/IEEE-488 via PyVISA
* :class:`~stoner_measurement.instruments.transport.NullTransport` — loopback for testing

**Protocol layer** (command formatting and response parsing):

* :class:`~stoner_measurement.instruments.protocol.BaseProtocol` — abstract base
* :class:`~stoner_measurement.instruments.protocol.ScpiProtocol` — SCPI / IEEE 488.2
* :class:`~stoner_measurement.instruments.protocol.OxfordProtocol` — Oxford Instruments CR protocol
* :class:`~stoner_measurement.instruments.protocol.LakeshoreProtocol` — Lakeshore CRLF ASCII

**Instrument hierarchy**:

* :class:`~stoner_measurement.instruments.base_instrument.BaseInstrument` — holds transport + protocol
* :class:`~stoner_measurement.instruments.temperature_controller.TemperatureController` — abstract type
* :class:`~stoner_measurement.instruments.magnet_controller.MagnetController` — abstract type
* :class:`~stoner_measurement.instruments.source_meter.SourceMeter` — abstract type
* :class:`~stoner_measurement.instruments.nanovoltmeter.Nanovoltmeter` — abstract type
* :class:`~stoner_measurement.instruments.keithley.Keithley2400` — concrete SMU driver
* :class:`~stoner_measurement.instruments.keithley.Keithley2410` — concrete SMU driver
* :class:`~stoner_measurement.instruments.keithley.Keithley2450` — concrete SMU driver
"""

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.magnet_controller import MagnetController, MagnetLimits, MagnetState, MagnetStatus
from stoner_measurement.instruments.nanovoltmeter import Nanovoltmeter
from stoner_measurement.instruments.source_meter import (
    MeasureFunction,
    SourceMeter,
    SourceMeterCapabilities,
    SourceMode,
    SourceSweepConfiguration,
    SweepSpacing,
    TriggerModelConfiguration,
    TriggerSource,
)
from stoner_measurement.instruments.temperature_controller import (
    AlarmState,
    ControllerCapabilities,
    ControlMode,
    LoopStatus,
    PIDParameters,
    RampState,
    SensorStatus,
    TemperatureController,
    TemperatureReading,
    TemperatureStatus,
    ZoneEntry,
)

__all__ = [
    "AlarmState",
    "BaseInstrument",
    "ControllerCapabilities",
    "ControlMode",
    "InstrumentDriverManager",
    "InstrumentError",
    "LoopStatus",
    "MagnetController",
    "MagnetLimits",
    "MagnetState",
    "MagnetStatus",
    "MeasureFunction",
    "Nanovoltmeter",
    "PIDParameters",
    "RampState",
    "SensorStatus",
    "SourceMeter",
    "SourceMeterCapabilities",
    "SourceMode",
    "SourceSweepConfiguration",
    "SweepSpacing",
    "TemperatureController",
    "TemperatureReading",
    "TemperatureStatus",
    "TriggerModelConfiguration",
    "TriggerSource",
    "ZoneEntry",
]
