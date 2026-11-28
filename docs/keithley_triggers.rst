Keithley connections and triggering
===================================

Choose the acquisition mode before wiring triggers. The four trace plugins
use different coordination schemes; a GPIB address or serial relay selects a
command path, while Trigger Link or a reference cable carries timing signals.
Return to :doc:`keithley_meters` for the measurement choices.

6221/2182A buffered I-V
-----------------------

After settling at each point of the :doc:`keithley_6221_2182a` trace, the
source triggers the primary 2182A. The meter's completion signal permits the
next source step.

The primary settings expose the two Trigger Link lines:

* **6221 to 2182A**: source output to primary-meter external trigger input
  (default line 2).
* **2182A to 6221**: meter-complete output to source input (default line 1).

Selecting **Via 6221 serial port** sends meter commands through the source's
RS-232 relay. It still needs the Trigger Link connection for this handshake.
Selecting **Direct GPIB** gives the primary its own GPIB session; it does not
remove the hardware-trigger requirement.

With a second nanovoltmeter enabled, choose one topology on **Secondary
nanovoltmeter**:

* **Parallel**: the source triggers both meters; the primary alone returns
  completion to the source. The secondary must finish before the next source
  trigger. Increase settling/primary conversion time or shorten secondary
  integration/filtering when the timing warning indicates an overrun.
* **Daisy-chain**: source triggers primary, primary completion triggers
  secondary, and secondary completion advances source. Configure the
  primary-to-secondary and secondary-to-source lines to match the cable.
  Source progression then waits for both meters.

.. figure:: _static/screenshots/keithley-6221-detail.png
   :alt: Secondary nanovoltmeter configuration showing parallel and daisy-chain routing choices and Trigger Link line controls.
   :width: 100%

   Routing is configured with the secondary meter's conversion settings.

2400 trigger model
------------------

The 2400 buffered trace, point scan and set command expose the supported
trigger-model controls on the nested **Advanced** page.

.. list-table:: Trigger source choices
   :header-rows: 1
   :widths: 25 75

   * - Source
     - Use
   * - Immediate
     - Proceed through the instrument's configured acquisition without an
       external start signal.
   * - Bus
     - Let the plugin issue the bus trigger when starting the acquisition.
   * - External / Trigger Link
     - Wait for the corresponding external routing; configure the input line
       and provide the expected signal.
   * - Timer
     - Use the configured instrument timer interval.

The output-enable checkbox and output-line selector are separate from the
choice of incoming trigger source. Arm count, trigger-count override and
delays also affect completion. An unprovided external trigger can leave an
acquisition waiting until its timeout.

When the buffered 2400 trace enables its secondary nanovoltmeter, it configures
a dedicated SMU/meter Trigger Link handshake. The SMU's output line triggers
the meter and the meter's completion returns on the configured input line.
This acquisition chooses its own compatible counts and arm behaviour rather
than combining arbitrary manual trigger overrides. Meter integration and
filtering must fit the intended cadence. See :doc:`keithley_2400` for the
configuration screenshots.

6221 with lock-ins
------------------

The :doc:`keithley_lockin` trace uses a 6221 sine-wave phase marker on its
selected Trigger Link line as the external phase and frequency reference for
the lock-ins. Buffered IV traces use their trigger line to signal completion
of each meter conversion.

Native Pulse Delta
------------------

:doc:`keithley_pulse_delta` requires both RS-232 and Trigger Link between the
6221 and 2182A, using the native mode's factory Trigger Link assignments.
Both serial ports use 19.2 kbaud without flow control; the PC talks to the
6221 over GPIB. The source manages the pulse/meter handshake and integration.

Use the ordinary I-V trace if you need to trigger an auxiliary meter as part
of the acquisition.

Held-DC point scans and set commands
------------------------------------

For held DC, the 6221 point and set steps run without Trigger Link wiring.
The 2400 point and set steps can use the instrument's trigger routing,
including Trigger Link output. See :doc:`keithley_point_commands` for setup
examples.

For any physical rig, check the cable routing, signal compatibility,
integration/filter settings and source limits against the selected
instruments. Configuration screenshots illustrate the software controls;
they do not establish bench validation of the measurement timing.
