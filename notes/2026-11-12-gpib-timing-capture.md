# Opt-in GPIB timing capture

Launch with `--telemetry-log PATH` to append synchronous standard-logging records
to a file. The capture infrastructure is in `stoner_measurement.telemetry` so
other instrumentation can use the same switch and file later. The initial
instrumentation covers native operations in GpibTransport, inherited by its
pass-through subclass where those operations are reused.

Without the switch, no handler is opened, no timing clock is read, and calls
forward directly after an enabled check. Capture uses one standard FileHandler
and flushes each record. It does not use the Log Viewer's queued GUI delivery,
so the last START remains inspectable while the UI is blocked. Normal logging
levels and handlers are unchanged. Capture stops in the entry point's finally
block. Native-call exceptions, including those subsequently suppressed by
flush, are recorded then re-raised unchanged to the existing caller.

Stages distinguish resource-manager initialisation, resource opening, each
initial attribute assignment, Device Clear, raw write, serial poll after write,
serial poll during read, raw read and close. Resource, transport/attempt and
call identifiers correlate records; thread names/IDs show GUI-thread work.
Command arguments are truncated to 200 characters. The session header includes
Python/platform/PyVISA and manager creation records the selected backend repr
without extra instrument queries or discovery.

This is diagnostic capture, not a timeout or worker-thread change. Resource
opening and the pre-existing post-write serial polls remain unchanged so the
original delay can be measured. Continued polling can generate many records;
use short capture sessions. File flush is not an fsync/power-loss guarantee.
The file identifies native calls that never return but cannot interrupt them.

Remote collection steps are in `docs/usage.rst`. No physical hardware was
available. Tests include an outstanding worker operation with the START record
read from disk before release, deterministic elapsed-time/failure checks and
the real GPIB transport over fake VISA sessions. The related 306-test selection
passed with the project Conda environment and offscreen PyQt5.
