Simulated Instruments
=====================

The application includes built-in simulated instrument drivers for development,
testing, demonstrations, and training when laboratory hardware is not
available.

The simulated drivers are ordinary instrument drivers and are discovered
automatically by the instrument driver manager. They therefore exercise the
same connection, engine, polling, charting, and configuration code paths as
real hardware.

Available Simulated Drivers
---------------------------

Temperature Controller
~~~~~~~~~~~~~~~~~~~~~~

``SimulatedTemperatureController`` provides:

* Four temperature inputs (A-D).
* Two control loops.
* PID parameter storage.
* Setpoint ramping.
* Heater output simulation.
* Thermal lag between the control setpoint and measured temperature.

The controller maintains a programmed setpoint and an active control setpoint.
When ramping is enabled, the active control setpoint moves towards the
programmed setpoint at the configured ramp rate.

Magnet Controller
~~~~~~~~~~~~~~~~~

``SimulatedMagnetController`` provides:

* Magnetic field and current readback.
* Field/current target setting.
* Ramp-rate control.
* Persistent-switch heater state.
* Simulated output voltage during ramps.

The controller reports realistic operational states:

* ``STANDBY``
* ``RAMPING``
* ``AT_TARGET``

Using Simulated Instruments
---------------------------

The simulated drivers appear in the normal driver-selection controls used by
the temperature and magnet control panels.

No special configuration is required:

1. Open the relevant control panel.
2. Select a simulated driver from the driver list.
3. Connect as normal.
4. Use the panel exactly as you would with physical hardware.

Because the simulations are ordinary instrument drivers, they are useful for:

* User-interface development.
* Testing engine behaviour.
* Demonstrating application features.
* Training new users.
* Reproducing issues without laboratory hardware.

Limitations
-----------

The simulations are intentionally simplified and are not intended to model
every aspect of real hardware.

Examples of simplifications include:

* Idealised thermal and magnetic behaviour.
* Simplified voltage and heater models.
* No communication failures.
* No hardware-specific fault conditions.

The goal is to provide realistic application behaviour rather than a detailed
physical model.