Simulated Instruments
=====================

The application includes built-in simulated instrument drivers for development,
testing, demonstrations, and training when laboratory hardware is not
available.

For a first measurement, use the hardware-free trace in :doc:`usage`; that
example needs no controller connection. This page is the reference for testing
the shared rig-control services with simulated drivers. See :doc:`rig_controls`
for their panels and :doc:`configuration` if a subsystem is hidden.

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

Motor Controller
~~~~~~~~~~~~~~~~

``SimulatedMotorController`` provides angular position and target readback,
velocity and acceleration settings, absolute/relative moves, home positioning
and moving/at-target status. Motion progresses with elapsed time as readings
are requested. It is useful for exercising motor scan and monitor workflows,
but does not reproduce a particular stage's travel limits or mechanics.

Pressure Gauge Controller
~~~~~~~~~~~~~~~~~~~~~~~~~

``SimulatedPressureGaugeController`` supplies three pressure channels in mbar,
two stored relay setpoints and named interlock states. Its capability flags
disable remote gauge switching and pump control in the UI. Relay readback is
fixed rather than a simulation of threshold switching. Developer scripts can
exercise interlock handling with ``set_simulated_interlock(name, satisfied)``.

Mass-flow Controller
~~~~~~~~~~~~~~~~~~~~

``SimulatedMassFlowController`` supplies two flow channels, initially in sccm,
with setpoint, unit and range settings. Each actual-value read moves halfway
from the previous reading towards the requested setpoint. This is a simple
response model for flow controls and monitoring, not a calibrated gas model.

X-ray Diffractometer
~~~~~~~~~~~~~~~~~~~~

``SimulatedXrayDiffractometer`` implements the same abstract
``XrayDiffractometer`` contract as the FTDI-backed legacy driver. It provides:

* independent theta and 2-theta motion;
* coupled ``2-theta = 2 * theta + offset`` motion;
* exact hardware step quantisation;
* scalar detector counts and count rates;
* a deterministic synthetic powder-diffraction peak pattern.

Select **Simulated** in the X-ray panel's instrument list. No address is
required.

Using Simulated Instruments
---------------------------

The simulated drivers appear in the normal driver-selection controls used by
the temperature, magnet, motor, pressure/flow and X-ray control panels.

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
* No automatic reproduction of hardware-specific fault conditions. Explicit
  simulated interlock changes exercise only that particular software path.

The goal is to provide realistic application behaviour rather than a detailed
physical model.
