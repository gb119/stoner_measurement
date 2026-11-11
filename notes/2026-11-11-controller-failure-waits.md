# Controller worker failure and blocked-I/O audit

The temperature, magnet, motor and pressure engines run in this application's
process. Their ControllerPoller starts at most one daemon Python thread for a
scheduled read. There is no controller subprocess, IPC request queue or dead
process awaiting a reply.

## Existing guarantees

- Ordinary driver exceptions are caught by engine read methods, set ERROR and
  invalidate successful completion/stability data. Setters propagate failures.
- ControllerPoller clears its pending flag in finally, including when a worker
  exits through BaseException. A subsequent timer tick can schedule another read.
- ControllerUpdates waits have deadlines and check sequence cancellation every
  50 ms. A missing publication alone does not trap a consumer in that wait.
- Panels receive state/status signals. Scheduled reads do not hold the GUI event
  loop. Commands and explicit reads can still execute synchronously.

## Repairs

The ordinary GPIB MAV loop previously checked its deadline only when a special
command-complete mask was configured. A device which never asserted MAV, or
never cleared it during response collection, could therefore keep the worker
inside Python indefinitely. Both loops now apply the transport timeout.
The existing opt-in command-executing behaviour remains: its response deadline
is refreshed while the instrument reports that the command is still executing.

SetEngineStateCommand previously treated failed state as ordinary settling.
Set Field and other unbounded waits could keep retrying forever; temperature
could consume its entire stability timeout. Commands now reject ERROR,
DISCONNECTED and STOPPED snapshots before checking target completion and after
update notifications. Previous scalar outputs are cleared before starting.
Scan waits and sweep iteration apply the same check. Temperature checks use
the selected slot's status rather than conflating primary and secondary health.
Make Safe rejects failed magnet readback before accepting zero-field completion
or switching the persistent-switch heater off.

Polling diagnostics include exception type and message in their main log entry,
retaining tracebacks. The Mercury connection warning separately includes the
selected driver, transport, address and original exception.

## Remaining limits

These changes do not make a hung native call safely cancellable. All engines
use transaction RLocks. A driver or VISA library which ignores its configured
timeout can hold that lock indefinitely; another panel/plugin action and engine
shutdown can then block acquiring it. ControllerPoller.join also has no timeout.
The command-complete extension can intentionally wait indefinitely for the
executing flag to clear. No hardware action is retried or concurrent replacement
session opened to work around those situations.

A native access violation can terminate the entire application because these
are threads in one process. Recovering from that, or reliably abandoning a
wedged native driver, requires isolated controller processes with bounded IPC,
worker-liveness monitoring and explicit ownership/reconnection rules. Merely
timing out a Python waiter does not stop the hardware transaction and must not
be described as crash isolation.

Tests cover worker exceptions and fatal thread exit, pending-state recovery,
publication timeout/cancellation, missing/stuck MAV, initial/mid-wait controller
failures, scans/sweeps, independent temperature slots and the Make Safe heater
gate. Existing real-engine checks cover invalidated completion flags and GUI
responsiveness during slow polling. Hardware/native-library crashes were not
executed.

The combined regression selection passed 404 tests on Python 3.14.10 with
offscreen PyQt5 through Miniforge Conda. Ruff is unavailable in that environment.
The final command/failure selection passed 47 tests after adding connection-failure
output-reset coverage.
