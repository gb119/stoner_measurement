# Secondary electrometer in the SourceMeter trace

The existing 2400-family buffered trace now owns an optional second auxiliary
instrument, independently of the secondary nanovoltmeter. The Electrometer
page selects the 6485, 6514 or 6517 and edits a bounded setting/value table.
Settings persist under `secondary_electrometer`, including when disabled; older
sequences default to disabled. Numeric input-range, NPLC and delay expressions
are evaluated against the live sequence namespace during configuration.

The table covers model/resource/prefix, one measurement function, range and
autorange, NPLC, averaging enable/count, zero check, trigger delay/count,
arm count, buffer size, transfer format and completion line. Trigger Link and
immediate arming are derived acquisition constraints, rather than independent
editable sources: free-running or bus-triggered readings cannot be attached to
source points reliably by their buffer index. Trigger count × arm count and
buffer size must match the sweep length. Automatic sizing is the default.
The common buffer minimum is two points. The 6485 offers current; the
electrometers also offer voltage, resistance and charge. Transfer-format
choices follow the model (6514 has no double-precision transfer).

## Acquisition and wiring

The source holds each value while the auxiliary measurements complete. With
both options enabled, the hardware chain is:

1. SMU source-event output (Advanced page, default line 2) triggers the
   nanovoltmeter.
2. Nanovoltmeter completion (Advanced input line, default line 1) triggers the
   electrometer.
3. Electrometer completion (Electrometer page, default line 3) releases the
   SMU's next source event.

Without a nanovoltmeter, the electrometer input uses the SMU source-event line
directly. All three configured lines must be distinct. Configure the Trigger
Link cables/adapters to route these signals; two measurement-complete outputs
must not be connected to the same line. The meters measure sequentially within
each source point. Both channels remain available in the same IV trace.

Each acquisition clears and arms the electrometer buffer before initiating
the source. The last conversion is awaited with `*OPC?` using a bounded,
temporarily adjusted transport timeout. Reading-only elements make buffer
parsing independent of the front-panel format. The driver reads the entire
buffer using `TRAC:DATA?` (no unsupported start/count query arguments), handles
ASCII and IEEE-754 blocks, and the plugin requires the exact point count.
The new channel carries the selected measurement's SI unit and supports the
existing mean/std output option. In differential mode its raw physical-point
readings are retained rather than applying a voltage-only reduction to other
quantities. Every new session is owned by this instance; reconnect and failed
connections release partial resources, and cleanup attempts all instruments
before propagating failures.

## Manufacturer evidence

- [6485/6487 user manual, Rev. C](https://download.tek.com/manual/6487-900-01%28C-Mar2011%29%28User%29.pdf):
  section 6 (sense-buffer feed and reading elements), appendix C (single-
  precision binary transfer and byte order).
- [6514 instruction manual, Rev. D](https://download.tek.com/manual/6514-901-01%28D-May2003%29%28Instruction%29.pdf):
  sections 8–9 (buffer and Trigger Link), section 14 (`INIT`/`*OPC?` and deferred
  commands), section 16 (ASCII/single precision and reading-only elements).
- [6517B reference manual, Rev. E](https://download.tek.com/manual/6517B-901-01E_Aug_2022_Ref.pdf):
  sections 11-57–11-61 (format/byte order), 11-168 onwards (buffer), and
  11-185–11-198 (asynchronous trigger lines and bypass). Its measure-layer
  completion output is always enabled; the 6485/6514 output-selection commands
  are not sent to the 6517. Variant/firmware compatibility still needs a bench
  check on the particular 6517 in use.

## Validation boundary

Automated tests use fake instruments and NullTransport. They cover model
selection, expression timing, buffer configuration and ASCII/binary parsing,
trigger-chain routing, simultaneous nanovoltmeter/electrometer acquisition,
point counts, statistics/units, partial connection failure, reconnect and
cleanup errors. The configuration page was rendered offscreen with Windows
fonts and visually inspected. The focused plugin docstring audit found no
structural omissions; the class documentation and custom About HTML were both
updated.

Final local checks: 127 focused tests passed on Python 3.14.7/PyQt5, all 4652
tests collected, and targeted Ruff and `git diff --check` passed. Other Qt
bindings and remote CI were not checked in this task.

Before a hardware run, check the three trigger routes with a short known sweep,
verify the source holds through both conversions, compare buffer lengths and
known input readings, repeat a sweep to exclude stale data, and exercise stop
and reconnect. Fake-instrument results do not establish hardware timing or
model/firmware command compatibility.
