Instrument architecture and drivers
===================================

The instrument subsystem is built around composition and discovery:

* :class:`stoner_measurement.instruments.base_instrument.BaseInstrument` composes a
  transport and a protocol.
* :class:`stoner_measurement.instruments.driver_manager.InstrumentDriverManager`
  discovers concrete driver classes.


BaseInstrument composition model
--------------------------------

Each instrument instance contains:

* a transport object (byte-level I/O and connection lifecycle), and
* a protocol object (command/query formatting, response parsing, and error checks).

This keeps instrument behaviour independent from physical connection details. A single
driver can be reused with different transports (for example serial, Ethernet, GPIB, or
null transport for tests) as long as the protocol matches the instrument command set.

.. automodule:: stoner_measurement.instruments.base_instrument

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   BaseInstrument

.. automodule:: stoner_measurement.instruments.transport

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   base.BaseTransport
   ethernet_transport.EthernetTransport
   ftdi_d2xx_transport.FtdiD2xxError
   ftdi_d2xx_transport.FtdiD2xxTransport
   gpib_transport.GpibTransport
   gpib_transport.PassThroughGpibTransport
   null_transport.NullTransport
   serial_transport.EchoSerialTransport
   serial_transport.SerialTransport
   udp_transport.UdpTransport

.. automodule:: stoner_measurement.instruments.protocol

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   base.BaseProtocol
   ieee488.parse_ieee_block
   lakeshore.LakeshoreProtocol
   leybold.LeyboldCenterProtocol
   mks.MKSPR4000Protocol
   mks.MKSPSRProtocol
   modbus.ModbusRtuProtocol
   oxford.OxfordProtocol
   scpi.ScpiProtocol
   signal_recovery.SignalRecoveryProtocol


Driver discovery process
------------------------

:class:`~stoner_measurement.instruments.driver_manager.InstrumentDriverManager` uses two
discovery paths:

1. Built-in discovery scans modules in ``stoner_measurement.instruments`` (excluding the
   ``protocol`` and ``transport`` subpackages) and registers non-abstract
   :class:`~stoner_measurement.instruments.base_instrument.BaseInstrument` subclasses.
2. Third-party discovery loads entry points in the
   ``stoner_measurement.instruments`` group and registers non-abstract
   :class:`~stoner_measurement.instruments.base_instrument.BaseInstrument` subclasses.

Use :meth:`~stoner_measurement.instruments.driver_manager.InstrumentDriverManager.drivers_by_type`
to filter the discovered registry by an instrument base type such as
``TemperatureController``, ``MagnetController``, or ``SourceMeter``.

.. automodule:: stoner_measurement.instruments.driver_manager

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   InstrumentDriverManager


Instrument hierarchy and concrete classes
-----------------------------------------

Hierarchy overview:

* :class:`~stoner_measurement.instruments.base_instrument.BaseInstrument`
* :class:`~stoner_measurement.instruments.temperature_controller.TemperatureController`
* :class:`~stoner_measurement.instruments.magnet_controller.MagnetController`
* :class:`~stoner_measurement.instruments.source_meter.SourceMeter`
* :class:`~stoner_measurement.instruments.nanovoltmeter.Nanovoltmeter`
* :class:`~stoner_measurement.instruments.xray_diffractometer.XrayDiffractometer`

Concrete classes currently included in the package:

* Source meter drivers:
  :class:`~stoner_measurement.instruments.keithley.k2400.Keithley2400`,
  :class:`~stoner_measurement.instruments.keithley.k2400.Keithley2410`,
  :class:`~stoner_measurement.instruments.keithley.k2400.Keithley2450`
* Temperature controller drivers:
  :class:`~stoner_measurement.instruments.lakeshore.temperature_controllers.Lakeshore335`,
  :class:`~stoner_measurement.instruments.lakeshore.temperature_controllers.Lakeshore336`,
  :class:`~stoner_measurement.instruments.lakeshore.temperature_controllers.Lakeshore340`,
  :class:`~stoner_measurement.instruments.oxford.temperature_controllers.OxfordITC503`,
  :class:`~stoner_measurement.instruments.oxford.temperature_controllers.OxfordMercuryTemperatureController`
* Magnet controller drivers:
  :class:`~stoner_measurement.instruments.lakeshore.ls625.Lakeshore625`,
  :class:`~stoner_measurement.instruments.oxford.ips120.OxfordIPS120`
* X-ray diffractometer drivers:
  :class:`~stoner_measurement.instruments.xray.legacy_diffractometer.LegacyXrayDiffractometer`,
  :class:`~stoner_measurement.instruments.xray.simulated.SimulatedXrayDiffractometer`

.. automodule:: stoner_measurement.instruments

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   agilent.e5062a.AgilentE5062A
   agilent.n5222a.AgilentN5222A
   current_source.CurrentSource
   current_source.CurrentSourceCapabilities
   current_source.CurrentSweepConfiguration
   current_source.CurrentSweepSpacing
   current_source.CurrentWaveform
   current_source.PulsedSweepConfiguration
   dmm.DigitalMultimeter
   dmm.DmmCapabilities
   dmm.DmmFunction
   dmm.DmmTriggerSource
   electrometer.Electrometer
   electrometer.ElectrometerCapabilities
   electrometer.ElectrometerDataFormat
   electrometer.ElectrometerFunction
   electrometer.ElectrometerTriggerConfiguration
   electrometer.ElectrometerTriggerSource
   errors.InstrumentError
   eurotherm.temperature_controllers.Eurotherm2000Series
   eurotherm.temperature_controllers.Eurotherm3200Series
   leybold.pressure_controllers.LeyboldCenterThree
   leybold.pressure_controllers.LeyboldDisplayThree
   lockin_amplifier.LockInAmplifier
   lockin_amplifier.LockInAmplifierCapabilities
   lockin_amplifier.LockInExpandFactor
   lockin_amplifier.LockInInputCoupling
   lockin_amplifier.LockInInputShielding
   lockin_amplifier.LockInInputSource
   lockin_amplifier.LockInLineFilter
   lockin_amplifier.LockInOutputChannel
   lockin_amplifier.LockInReferenceSource
   lockin_amplifier.LockInReserveMode
   magnet_controller.KepcoBOPGL
   magnet_controller.MagnetController
   magnet_controller.MagnetLimits
   magnet_controller.MagnetState
   magnet_controller.MagnetStatus
   mass_flow_controller.MassFlowController
   mass_flow_controller.MassFlowControllerCapabilities
   mks.controllers.MKSPR4000BS
   mks.controllers.MKSPSR1A
   mks.controllers.MKSPSR4A
   motor_controller.Motor
   motor_controller.MotorController
   motor_controller.MotorStatus
   nanovoltmeter.Nanovoltmeter
   nanovoltmeter.NanovoltmeterCapabilities
   nanovoltmeter.NanovoltmeterFunction
   nanovoltmeter.NanovoltmeterTriggerSource
   network_analyser.ByteOrder
   network_analyser.DataEncoding
   network_analyser.NetworkAnalyser
   network_analyser.NetworkAnalyserCapabilities
   network_analyser.NetworkAnalyserTriggerSource
   network_analyser.NetworkSweep
   network_analyser.NetworkTraceData
   network_analyser.SweepConfiguration
   network_analyser.SweepType
   network_analyser.TraceFormat
   pressure_controller.PressureControllerCapabilities
   pressure_controller.PressureGaugeController
   pressure_controller.PressureReading
   pressure_controller.PressureRelayState
   pressure_controller.PressureSetpoint
   pressure_controller.PressureStatus
   pressure_controller.PressureUnit
   simulated.SimulatedMagnetController
   simulated.SimulatedMassFlowController
   simulated.SimulatedMotorController
   simulated.SimulatedPressureGaugeController
   simulated.SimulatedTemperatureController
   source_meter.MeasureFunction
   source_meter.SourceMeter
   source_meter.SourceMeterCapabilities
   source_meter.SourceMode
   source_meter.SourceSweepConfiguration
   source_meter.SweepSpacing
   source_meter.TriggerModelConfiguration
   source_meter.TriggerSource
   temperature_controller.AlarmState
   temperature_controller.ControlMode
   temperature_controller.ControllerCapabilities
   temperature_controller.InputChannelSettings
   temperature_controller.LoopStatus
   temperature_controller.PIDParameters
   temperature_controller.RampState
   temperature_controller.SensorStatus
   temperature_controller.TemperatureController
   temperature_controller.TemperatureReading
   temperature_controller.TemperatureStatus
   temperature_controller.ZoneEntry
   thorlabs.hdr50.ThorlabsHDR50
   thorlabs.kdc101_kprmte.ThorlabsKDC101KPRMTE
   xray.legacy_diffractometer.LegacyXrayDiffractometer
   xray.protocol.XraySnapshot
   xray.simulated.SimulatedXrayDiffractometer
   xray_diffractometer.DiffractometerMechanics
   xray_diffractometer.XrayDiffractometer

.. automodule:: stoner_measurement.instruments.keithley

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   _scpi_data_format.KeithleyByteOrder
   k182.Keithley182
   k2000.Keithley2000
   k2000.Keithley2700
   k2182.Keithley2182A
   k2400.Keithley2400
   k2400.Keithley2410
   k2400.Keithley2450
   k6221.Keithley6221
   k651x.Keithley6514
   k651x.Keithley6517
   k651x.Keithley6845

.. automodule:: stoner_measurement.instruments.lakeshore

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   current_sources.LakeshoreM81CurrentSource
   lia.LakeshoreM81LockIn
   ls625.Lakeshore625
   temperature_controllers.Lakeshore335
   temperature_controllers.Lakeshore336
   temperature_controllers.Lakeshore340

.. automodule:: stoner_measurement.instruments.oxford

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   ips120.OxfordIPS120
   mercury_ips.OxfordMercuryIPS
   temperature_controllers.OxfordITC503
   temperature_controllers.OxfordMercuryTemperatureController

.. automodule:: stoner_measurement.instruments.xray_diffractometer

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   AxisDirection
   AxisMechanics
   CountResult
   XrayMotionDisabledError
   XrayMotionError
   XrayOperationCancelled
   XrayPositionError
   XrayTravelLimitError
   cancellation_requested

.. automodule:: stoner_measurement.instruments.xray

.. autosummary::
   :toctree: ../_generated/api
   :nosignatures:

   protocol.ControllerStatus
   protocol.LegacyXrayProtocol
   protocol.XrayBcdError
   protocol.XrayFrameLengthError
   protocol.XrayOpcode
   protocol.XrayProtocolError
   protocol.decode_le_bcd
   protocol.decode_snapshot
   protocol.decode_wrapped_six_digits
