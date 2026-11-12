# Model 340 monitoring with unavailable loop targets

The observed exception originates in `Lakeshore340.get_setpoint`: CSET units 3
means sensor units, which cannot be converted generically to kelvin. Units 1
and 2 mean kelvin and Celsius. CSET enable is independent of these units.
The command evidence remains in `notes/lakeshore_temp_controllers.md` (CSET,
manual page 9-31); this change adds no instrument commands.

## Paths and behaviour

- Automatic and explicit controller reads reach `_build_state`, then
  `_collect_loop_data`, then `get_setpoint`. Previously this exception reached
  `read_controller_state`, set ERROR and discarded valid sensor readings.
- Polling now reads mode first. OFF loops retain their mode but skip all other
  loop telemetry. On the 340 this needs only CSET, without CMODE. Sensors still
  update, and re-enabling the loop is detected on the next poll.
- Unsupported individual loop reads are omitted and retried on subsequent polls.
  Other active loops and temperature readings remain available. Communication
  and malformed required-read errors still invalidate the snapshot.
- Missing targets clear cached targets and stability continuity, histories and
  diagnostics. A disabled or unsupported loop cannot satisfy stability waits.
- Explicit engine `get_loop_settings` previously substituted a fictitious 0 K
  target after any setpoint error. It now returns None with a warning. The UI
  already handles this return without populating the editor.
- Direct driver `get_loop_status`, `get_controller_status` and
  `wait_for_setpoint` also reach `get_setpoint`. These APIs require a Kelvin
  target and continue to raise rather than fabricate a complete status or
  successful wait. Explicit sensor-unit Kelvin writes remain rejected.

There is currently no app loop-units selector for the 340. Its native input
editor's Sensor units setting selects volts/ohms, independently of CSET.

## Validation

Focused tests use the real Model 340 read methods with scripted native query
responses, covering primary/secondary sessions, enabled/disabled loops,
unsupported fields, target loss/recovery, and genuine connection failure.
An exact-query assertion verifies OFF loops issue only CSET after sensor reads.
Physical hardware remains untested: confirm continuous A/B monitoring with both
loops OFF and with an enabled sensor-unit loop, then restore Kelvin units and
check target/stability recovery.
