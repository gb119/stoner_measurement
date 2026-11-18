Keithley meters
===============

Keithley measurement steps have their own instrument connections and settings.
Choose a trace for a complete acquired curve, a point scan to run child steps
at each source level, or a set command to hold one bias for later steps. These
steps do not borrow the temperature, magnet or motor engines described in
:doc:`rig_controls`.

Choose a measurement
--------------------

.. list-table:: Trace plugins
   :header-rows: 1
   :widths: 25 45 30

   * - Guide
     - Measurement
     - Returned trace
   * - :doc:`6221/2182 IV Trace <keithley_6221_2182a>`
     - Current list from a 6221; synchronised buffered voltage from an 2182A,
       with an optional second nanovoltmeter
     - ``IV``: voltage, resistance and power
   * - :doc:`6221/Lockins Trace <keithley_lockin>`
     - 6221 sine amplitude, DC offset or frequency scanned with one or more
       SR830 or SIGNAL RECOVERY 7265 lock-ins
     - ``Signals``: selected lock-in outputs and optional resistance channels
   * - :doc:`2400 IV Trace <keithley_2400>`
     - Buffered current- or voltage-source LIST sweep on a 2400 SMU, with an
       optional second nanovoltmeter
     - ``IV``: measured current, voltage, resistance, power and time
   * - :doc:`keithley_pulse_delta`
     - Native 6221/2182A pulse acquisition with one or two baseline readings
     - ``IV``: corrected voltage, resistance and peak power

The ordinary 6221/2182A, current-source 2400 and native Pulse Delta traces also
offer alternating delta-current acquisition for differential resistance or
conductance. This optional setting changes the response columns; it does not
make the ordinary I-V trace use the native Pulse Delta timing model. Each
guide explains the mode and its returned columns.

Use :doc:`keithley_point_commands` for **2400 Point by Point Scan**,
**6221/2182 Point by Point Scan**, **Set 2400** and **Set 6221/2182**.
See :doc:`keithley_triggers` for trigger routing and the distinction between
buffered handshakes, AC reference signals, native pulses and held DC.

Single electrometer readings
----------------------------

Choose **Keithleys → Read Electrometer** to take one fresh reading from a
Keithley 6485 picoammeter or 6514/6517 electrometer. On **General**, choose the
model, GPIB resource, measurement function, range/autorange, integration,
averaging, zero check, trigger delay and timeout. The 6485 reads current; the
6514/6517 can also read voltage, resistance or charge. Numeric expressions
are evaluated at configuration time.

Each execution publishes one scalar output named **Current**, **Voltage**,
**Resistance** or **Charge**, with its SI unit. Select that output in an outer
scan's data collection or use it in Plot Points, Save and later expressions.
For an instance named ``read_electrometer``, the most recent reading is also
available as ``read_electrometer.value``. Failed reads clear it to NaN.

Startup opens and configures the command's owned connection; cleanup closes
it. Every execution takes a new measurement using immediate triggering,
without external trigger wiring or buffer acquisition. Averaging may combine
several conversions into that one result. See the
:class:`~stoner_measurement.plugins.command.read_electrometer.ReadElectrometerCommand`
API documentation for script attributes and console examples.

Single multimeter readings
--------------------------

For a single 2000/2700 multimeter reading, choose **Keithleys → Read Multimeter**.
On General, select the model, GPIB resource and function. Controls include
range/autorange, NPLC, averaging, AC bandwidth, frequency/period gate time,
trigger delay and timeout, with unavailable settings disabled. AC NPLC applies
at 300 Hz bandwidth; frequency/period use gate time. Temperature uses kelvin
and the instrument's existing sensor configuration.

Each execution publishes the reading and applicable numeric setting readbacks
(including the actual range after autoranging). For an instance named
``read_multimeter``, inspect ``read_multimeter.value`` and
``read_multimeter.settings_readback``. Settings can be selected as scalar
outputs alongside the measurement. Filter Type is 0 for repeating and 1 for
moving; boolean settings use 0/1. Timeout is the local transport setting.

The 2700 is used as a multimeter on its currently selected input terminals.
No relay, routing, scan-list, channel-list or reset commands are sent; configure
it for ordinary DMM operation beforehand. Switching support is deferred.

Common workflow
---------------

1. Add the required step from the **Keithleys** catalogue.
2. Set the instrument connections, ranges, compliance, integration and timing
   on **Settings** for traces/point scans, or **General** for set commands.
   Trace and point-scan plugins choose source values on **Scan**; set commands
   take a **Source value** instead.
3. For traces, add Plot Trace and Save steps to use the acquired result. For
   point scans, put the required measurement steps inside the scan and select
   the scalar outputs to collect. See :doc:`data_workflows`.
4. Run the sequence. Startup connects and configures the owning instances;
   cleanup releases their sessions. Ordinary DC/AC steps may retain output
   between executions; Pulse Delta aborts to zero/off after each acquisition.

Use one owning plugin instance per physical source in a sequence. Reconfigure
can defer an instance's connection/configuration until its execution point;
see :ref:`sequence-reconfiguration`. Screenshots in these guides show the real
dark-mode configuration pages with example addresses; they do not establish
that any physical instruments were connected.

.. toctree::
   :maxdepth: 1

   keithley_6221_2182a
   keithley_lockin
   keithley_2400
   keithley_pulse_delta
   keithley_point_commands
   keithley_triggers
