# Read Electrometer command

`ReadElectrometerCommand` is registered as `read_electrometer`, with a bundled
**Keithleys → Read Electrometer** catalogue entry. It owns a connection to a
6485, 6514 or 6517, configures one selected measurement function, and exposes
one fresh scalar per execution. Current is the only 6485 choice; the 6514/6517
also offer voltage, resistance and charge. The SI unit and output label follow
the selected function. The value is available as `instance.value` and through
the normal scalar-output catalogue for scan collection and downstream steps.

General settings cover model, GPIB resource, function, range/autorange, NPLC,
averaging and count, zero check, trigger delay and timeout. Expressions are
evaluated during configuration; a fixed-range expression is ignored in
autorange mode. The command's lifecycle connects/configures once, reads on
every execution, then aborts/closes during cleanup. Repeated connection attempts
release the old session. Results survive successful cleanup but a failed read
clears the previous output to NaN. Live connections and results are not saved.

The concrete driver prepares one immediate trigger and one immediate arm,
disables buffer storage/continuous initiation, selects numeric reading-only
ASCII output, and issues `READ?` for each new conversion. It rejects empty,
multiple or malformed responses rather than silently keeping the first value.
Model/quantity registries are shared with the trace's electrometer helper;
buffer-only settings are absent from this command.

Validation: 99 focused tests passed on Python 3.14.7/PyQt5, including generated
sequence execution, persistence, output catalogue updates, driver command
bytes, fresh single readings, failed connection retry and cleanup failure.
Targeted Ruff, the focused plugin docstring audit, and `git diff --check`
passed. The configuration page was rendered offscreen and visually inspected.
The editable installation was refreshed and PluginManager discovery verified
the new class. Physical instrument operation and other Qt bindings were not
tested.
