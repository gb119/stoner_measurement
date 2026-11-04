Magnet, motor and pressure controls
====================================

This is an operational overview of the shared control panels used alongside
measurement sequences. Use :doc:`temperature_controllers` and
:doc:`xray_diffractometer` for those subsystems' detailed references. For testing
without devices, see :doc:`simulated_instruments`.

Shared panels and sequence steps
---------------------------------

Open a panel using its toolbar button or the **Engines** menu. Availability
depends on the corresponding feature in Preferences. The panel and related
sequence plugins use one shared controller service: hiding a panel does not
mean its instrument has disconnected. Use its connection controls or the
engine controls when you intend to disconnect.

Select the instrument driver and supported transport/address on **Connection**,
then connect. **Save Settings to YAML** preserves connection settings for the
rig. A disabled automatic polling rate stops periodic reads while retaining
the connection; explicit reads and commands still require a responsive device.
Driver capabilities determine which optional controls are available.

Magnetic field
----------------

The magnet panel exposes field/current readback, target and ramp controls,
status, and supported persistent-switch functions. Rig limits such as magnet
constant, compliance and ramp bounds belong to its configuration. Confirm
their meaning for the selected magnet/power supply before applying targets.

Set Field, Magnet Controller Scan/Sweep and Magnetic Field Monitor share this
service. Use a scan for measurements after discrete points and a sweep for
sampling while the state changes. Configure collection/plotting on the
sequence steps as shown in :doc:`data_workflows`; a control-panel chart is not
automatically a saved measurement table.

Motor position
----------------

The motor panel has **Connection** and **Control** pages. Connection fields
depend on the selected transport, including serial/VISA/network controls and
the controller serial number for Kinesis. Control provides target angle,
velocity, acceleration, direction, reads and supported movement operations.
The dial is a readback display; it is not a draggable movement command.

Set Position, Motor Controller Scan/Sweep and Motor Angle Monitor use the same
session. Movement and homing behavior depend on the driver. The simulated
motor supports motion-profile testing without connecting a real stage.

Pressure and flow
------------------

The pressure panel exposes gauge and mass-flow controller choices. Its
channel readings, flow settings and optional interlocks/remote controls depend
on the selected driver. A gauge query and a flow setpoint are different
operations; select the device/channel that owns the required capability.

Pressure Monitor, Set Flow and Gauge Channel sequence commands borrow the
shared pressure service. Their configuration and output selectors determine
which channels participate in a measurement. Use Plot Points for current
scalar readings and enable scan/sweep collection to retain them in a result
table; Save then writes that table independently of the panel's live chart.

Script and extension boundaries
--------------------------------

Use public controller services for direct scripted control, with explicit
connection/capability checks. The sequence engine namespace is not itself a
magnet, motor or pressure controller. See :doc:`console_api` for the shared
namespace model, and the appropriate classes in :doc:`api/core` and
:doc:`api/instruments` for method signatures. Plugin authors must preserve
borrowed-session ownership as specified in :doc:`third_party_plugins`.
