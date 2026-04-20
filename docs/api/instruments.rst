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
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.instruments.transport
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.instruments.protocol
   :members:
   :undoc-members:
   :show-inheritance:


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
   :members:
   :undoc-members:
   :show-inheritance:


Instrument hierarchy and concrete classes
-----------------------------------------

Hierarchy overview:

* :class:`~stoner_measurement.instruments.base_instrument.BaseInstrument`
* :class:`~stoner_measurement.instruments.temperature_controller.TemperatureController`
* :class:`~stoner_measurement.instruments.magnet_controller.MagnetController`
* :class:`~stoner_measurement.instruments.source_meter.SourceMeter`
* :class:`~stoner_measurement.instruments.nanovoltmeter.Nanovoltmeter`

Concrete classes currently included in the package:

* Source meter drivers:
  :class:`~stoner_measurement.instruments.keithley.Keithley2400`,
  :class:`~stoner_measurement.instruments.keithley.Keithley2410`,
  :class:`~stoner_measurement.instruments.keithley.Keithley2450`
* Temperature controller drivers:
  :class:`~stoner_measurement.instruments.lakeshore.Lakeshore335`,
  :class:`~stoner_measurement.instruments.lakeshore.Lakeshore336`,
  :class:`~stoner_measurement.instruments.lakeshore.Lakeshore340`,
  :class:`~stoner_measurement.instruments.oxford.OxfordITC503`,
  :class:`~stoner_measurement.instruments.oxford.OxfordMercuryTemperatureController`
* Magnet controller drivers:
  :class:`~stoner_measurement.instruments.lakeshore.Lakeshore525`,
  :class:`~stoner_measurement.instruments.oxford.OxfordIPS120`

.. automodule:: stoner_measurement.instruments
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.instruments.keithley
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.instruments.lakeshore
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.instruments.oxford
   :members:
   :undoc-members:
   :show-inheritance:
