Keithley meters
===============

Use the :doc:`Keithleys group in Sequence commands </_generated/sequence_commands/group-keithleys>`
to find the settings, outputs and console examples for each step. The guides
below cover practical instrument setup, wiring and choice of acquisition mode.

Choose a measurement
--------------------

Use a buffered IV trace when the instruments should acquire a complete curve
under their own trigger model. Use Pulse Delta for the native low/high pulse
sequence with baseline correction, or the lock-in trace for AC measurements
with a sine-wave reference. See :doc:`keithley_triggers` before wiring the rig.

When comparing curves acquired in alternating differential mode, the two
endpoint responses use the nearest interior estimates. Keep that in mind
when interpreting the ends of a sweep.

Use a point scan when the sequence needs to perform other measurements at each
held source level. Use a set command for a single bias that later steps will
use. The setup is illustrated in :doc:`keithley_point_commands`. Standalone
electrometer and multimeter reads can also be used as children of a scan or
sweep. Select their scalar outputs in the parent's data collection to record
them together with the scan or sweep coordinate.

Common workflow
---------------

1. Choose a **Keithleys** step and review its instrument addresses, source
   limits and timing against the rig before connecting.
2. Add Plot Trace and Save for a complete curve, or collect scalar outputs
   from the children of a point scan. See :doc:`data_workflows` for examples.
3. Run the sequence and check the connection and source state before
   reconfiguring the rig.

Use one owning plugin instance per physical source where possible. See
:ref:`sequence-reconfiguration` when a procedure needs separate setups at
different times. The screenshots show example software configurations.

.. toctree::
   :maxdepth: 1

   keithley_6221_2182a
   keithley_lockin
   keithley_2400
   keithley_pulse_delta
   keithley_point_commands
   keithley_triggers
