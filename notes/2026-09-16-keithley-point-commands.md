# Keithley DC point and set commands

Implemented the 6221 DC state scan and 2400/6221 leaf set commands. Set commands
reuse the point-scan objects and opt into the existing sequence lifecycle so
output remains active until normal cleanup. No changes to instrument drivers
or existing trace acquisition are required.

The two 6221 voltage meters are independent, including secondary-only operation.
No enabled meters means only the programmed source value is advertised.
Configuration persists in JSON, and enabled-meter UI changes refresh outputs.

## Trigger and pulse decision

Keep the current applied throughout the scan sub-sequence. Do not implement
pulsed-current plugins in this batch. The 2400's existing Trigger Link options
remain available. The provisional 6221 single-point LIST trigger approach was
removed: the reference manual describes conflicting post-sweep behavior
(section 4 custom sweeps says hold last value; the sweep-arm command discussion
says finite completion outputs zero). Reasserting the DC value after completion
cannot establish uninterrupted bias for externally triggered measurements.
Standalone 6221 trigger-output support is therefore deferred pending hardware
verification of an approach that preserves the held DC current.

Reference: [Keithley 6220/6221 reference manual, sections 4 and 8](https://download.tek.com/manual/622x-901-01%20(C%20-%20Oct%202008)(Ref).pdf).

## Validation

### Expanded voltmeter settings

Both DC plugins now share General, Primary and Secondary tabs. Added independent
range, digits, trigger delay, autozero, line sync, digital filter type/count,
analogue filter and relative mode/reference controls alongside NPLC. The helper
`plugins/_point_voltmeter.py` applies driver capabilities without adding trace
buffering or external-trigger behavior. Secondary driver changes refresh valid
choices and disable unsupported controls; older 182 configurations receive
compatible defaults for newly introduced settings.

Validated 125 tests across the point/set plugins and existing 6221 trace,
measurement-settings and secondary-meter tests, with exit code 0. Ruff passed.
Rendered and inspected the set command's Primary tab offscreen; controls fit
and remain top-packed. Hardware validation remains outstanding.

Focused tests cover optional-meter combinations, source-only outputs, repeated
DC points, zero-current resistance, failed measurements, reconnect and partial
connection cleanup, cleanup failures, JSON/UI behavior, runtime expressions,
generated command lifecycle and failure cleanup. Hardware timing and serial
pass-through operation remain bench-validation boundaries.

Final related run: 168 passed, exit code 0. Use the shared engine fixture in
command tests: unclosed local SequenceEngine objects caused a Qt teardown
crash after otherwise successful assertions. Ruff passed and all three new
entry points loaded successfully.

The editable-install refresh encountered a running, locked application launcher.
Recovered by staging the editable installation, restoring its path/metadata and
missing auxiliary launchers, correcting RECORD paths/hashes, and preserving the
old metadata under `.pytest-runtime/keithley-install`. The active launcher was
not replaced and no application process was stopped. Restart the application
to refresh its plugin catalogue.
