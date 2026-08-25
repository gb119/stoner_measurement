# Programming Guide: Agilent/Keysight E5062A ENA Driver for `stoner_measurement`

## Purpose

This document is an implementation brief for an LLM coding agent. Its task is to add a production-quality driver for the **Agilent/Keysight E5062A ENA Series RF network analyser** to the `gb119/stoner_measurement` repository.

The driver must:

1. Conform to the repository’s existing instrument-driver architecture, naming conventions, transport abstraction, units system, descriptors, discovery mechanism, documentation style, and tests.
2. Expose the analyser’s useful measurement functionality rather than wrapping only a few SCPI commands.
3. Model the instrument’s channel, trace, marker, calibration, trigger, data-transfer, limit-test, display, file, and handler-I/O structure in a typed and discoverable API.
4. Support GPIB and repository-supported LAN/VISA transports without creating a second communications framework.
5. Correctly handle ASCII and IEEE-488.2 binary-block data transfer.
6. Be testable without physical hardware.
7. Avoid unsafe or surprising side effects, particularly RF output changes, resets, calibration erasure, file deletion, front-panel locking, instrument shutdown, and writes to internal trace arrays.
8. Detect firmware- and option-dependent functionality rather than assuming every command is available.

The instrument-behaviour source of truth is the attached **Agilent E5061A/E5062A ENA Series Programmer’s Guide**, Fifth Edition, manufacturing number E5061-90042, October 2008. The manual applies directly to firmware revision A.03.00; some features have additional firmware requirements. Page references below use the printed manual page numbers.

---

# 1. Mandatory repository reconnaissance

**Do not begin implementation until this section is complete.** The guide intentionally does not invent framework APIs that have not been observed in the checked-out repository.

## 1.1 Inspect the repository

From the repository root, locate:

- the package containing instrument drivers;
- the base class for VISA, SCPI, message-based, or network instruments;
- descriptor or parameter classes used for get/set properties;
- the units/quantity system;
- enum conventions;
- instrument registration and identification logic;
- transport abstractions for GPIB, TCP/IP, raw sockets, and binary blocks;
- timeout context managers;
- simulator, replay, dummy-resource, or mock-resource support;
- examples of instruments with channels, traces, subcomponents, or grouped settings;
- examples that return arrays or structured measurement results;
- tests for at least three existing instruments;
- package exports and documentation conventions;
- lint, formatting, typing, and test configuration.

Suggested searches:

```bash
find . -maxdepth 6 -type f | sort
rg -n "class .*Instrument|class .*Driver|Visa|VISA|pyvisa|SCPI|write\(|query\(" .
rg -n "register|registry|discover|identify|IDN|instrument.*class" .
rg -n "binary|block|query_binary|read_raw|write_raw|FORM:BORD|FORM:DATA" .
rg -n "channel|trace|subsystem|component|proxy|group" src tests .
rg -n "Quantity|pint|units|Enum|StrEnum|validator|range" src tests .
rg -n "Mock|Fake|Dummy|Simulator|Replay|Resource" tests src .
```

## 1.2 Select structural reference drivers

Choose existing drivers that collectively demonstrate:

1. a SCPI/VISA instrument with ordinary scalar properties;
2. an instrument exposing indexed channels or subcomponents;
3. an instrument returning numeric arrays;
4. an instrument performing IEEE-488.2 binary-block transfers;
5. an instrument with trigger/wait semantics;
6. an instrument with enums and unit-aware values;
7. transcript-based or fake-transport tests.

Record before coding:

- exact module path for the new driver;
- exact base class and constructor signature;
- registration metadata and ID matching rules;
- whether subcomponents are descriptors, cached objects, dataclasses, or ordinary properties;
- public naming style;
- units representation;
- expected exceptions;
- test location and fixture style;
- whether setters return `None`, `self`, or the applied value;
- how raw write/query access is preserved;
- how binary query responses are read and decoded.

## 1.3 Repository-conformance rule

Where this guide conflicts with an established repository convention, follow the repository convention unless doing so would misrepresent the analyser or operate it unsafely. Document intentional deviations.

Do not introduce a new VISA wrapper, units package, descriptor system, or generic network-analyser framework solely for this driver unless the repository clearly needs one and the change is separately justified.

---

# 2. Recommended deliverables

Adapt paths to the actual repository layout.

Minimum deliverables:

- one E5062A driver module;
- registration/export changes;
- enums and compact result data structures;
- channel, trace, marker, calibration, and handler-I/O interfaces using repository conventions;
- unit tests with a fake/replay transport;
- binary-block parsing tests for REAL32 and REAL64;
- command-transcript tests for measurement, calibration, limits, and state changes;
- a short example or documentation page;
- changelog/release-note entry if required.

Do not submit only a skeleton or a class containing raw SCPI constants.

A staged implementation is acceptable, but the initial merged version should support a complete useful workflow:

1. identify instrument and options;
2. configure one channel and one trace;
3. configure a linear sweep;
4. trigger and wait for one measurement;
5. read stimulus and complex corrected data;
6. return a structured result;
7. inspect the error queue.

---

# 3. Instrument identity, capabilities, and transport

## 3.1 Identity

The `*IDN?` response contains four comma-separated fields:

```text
Agilent Technologies,E5062A,<serial>,<firmware>
```

See manual p. 198.

The identification matcher should accept:

- manufacturer variants consistent with repository policy, including Agilent and Keysight naming where appropriate;
- model exactly `E5062A`;
- harmless whitespace and case variation.

Do not accidentally register an E5061A as E5062A unless the repository deliberately uses a shared base class plus separate registered subclasses.

Recommended class name, subject to repository convention:

```text
AgilentE5062A
```

A `KeysightE5062A` alias should be added only if aliases are normal and do not create duplicate registration.

## 3.2 Capability discovery

At connection or lazily on first use, support querying:

- `*IDN?` — manufacturer, model, serial, firmware;
- `*OPT?` — installed options, manual p. 199;
- `:SERV:PORT:COUN?` — number of ports, p. 430;
- `:SERV:CHAN:COUN?` — maximum channel count, p. 429;
- `:SERV:CHAN:TRAC:COUN?` — maximum traces per channel, p. 429;
- `:SERV:CHAN:ACT?` — active channel, p. 428;
- `:SERV:CHAN<n>:TRAC:ACT?` — active trace, p. 429.

Do not hard-code four channels, four traces, or two ports in generic helpers when the instrument can report these limits. The E5062A-specific public API may still validate against two physical ports after capability discovery.

Store parsed firmware as a comparable version object if the repository has one. Otherwise use a small internal parser that tolerates forms such as `03.00` and `A.03.00`.

Firmware gates from Appendix A include:

- system characteristic impedance command `:SENS:CORR:IMP` requires firmware 3.01 or later (manual pp. 43, 369);
- notch search and several display/reference-tracking functions require A.02.00 or later (pp. 502–503);
- bandwidth-limit, ripple-limit, and offset-limit features require versions later than those excluded in Appendix A (pp. 501–502).

When a feature is unsupported, raise the repository’s capability/unsupported-feature exception rather than sending a known-invalid command.

## 3.3 Supported remote interfaces

The analyser supports:

- GPIB talker/listener control;
- LAN control through SICL-LAN/VISA;
- raw TCP socket control through the telnet server’s programming port 5025.

See manual pp. 24–35.

Use the repository’s existing message-resource abstraction. Prefer standard VISA resource strings where supported. Raw socket support should be provided only through an existing transport abstraction or a small reusable transport already accepted by the repository.

Do not embed old SICL or WinSock APIs in the driver.

### Message termination

SCPI program messages accept newline and GPIB EOI terminators; a newline resets the SCPI command path to root. See manual pp. 36–37.

Use repository defaults. If explicit configuration is required, use newline write/read termination for ordinary ASCII operations, while ensuring binary reads do not stop prematurely on payload bytes.

### Raw socket caveat

Port 5025 does not provide every GPIB capability; notably service requests are unavailable over the telnet-server socket path (manual p. 35). Therefore:

- polling or `:TRIG:SING` plus `*OPC?` must work on all transports;
- SRQ-based APIs must advertise transport requirements or gracefully fall back;
- the driver must not assume a serial-poll implementation exists on raw TCP.

## 3.4 Timeouts

Use the repository’s temporary-timeout mechanism for:

- long sweeps;
- averaging cycles;
- calibration-standard acquisition;
- ECal;
- file transfer;
- large trace-array transfer;
- save/recall operations.

Do not globally set an excessive timeout during construction.

Provide a timeout estimate or user override for `measure()`, calibration, and file transfer. Sweep time alone is not always the total measurement time because multiple enabled channels are measured sequentially and sweep delay is applied.

---

# 4. Driver architecture

## 4.1 Prefer indexed subcomponents

The analyser has up to four channels, each with up to four traces, and each trace has markers, display settings, analysis state, limit-test state, and data arrays. A flat driver with hundreds of names such as `channel_1_trace_2_marker_3_x` is unacceptable.

Use the repository’s grouped-component pattern. If none exists, the recommended conceptual API is:

```text
instrument
├── channels[1..N]
│   ├── sweep settings
│   ├── source settings
│   ├── averaging
│   ├── correction/calibration
│   ├── traces[1..M]
│   │   ├── S-parameter
│   │   ├── display format and scale
│   │   ├── data/memory arrays
│   │   ├── markers[1..9]
│   │   ├── reference marker
│   │   ├── analysis/search
│   │   └── limit/bandwidth/ripple tests
│   └── trigger initiation state
├── trigger
├── display
├── files
├── status
└── handler_io
```

Subcomponents should retain a reference to the parent transport and validate indices before issuing SCPI.

## 4.2 Explicit indexed commands are preferred

Many commands operate on the currently active channel or trace. Active-state dependence creates race conditions and hidden side effects. Prefer commands that explicitly include channel and trace indices.

For commands whose SCPI syntax inherently targets the active trace:

- centralise selection in one helper;
- select the required trace immediately before the operation;
- avoid cached assumptions about active trace;
- optionally restore the previous active trace only if repository conventions favour restoration and the extra traffic is acceptable;
- document that the operation changes active selection if it does.

Only displayed channels/traces can become active (manual p. 40). Helpers that need activation must ensure the required channel/trace is displayed or raise a clear error; they must not silently rearrange the display unless explicitly requested.

## 4.3 Suggested public data structures

Use repository conventions, but structured results are strongly recommended.

### Identity/capabilities

```text
AnalyzerIdentity
- manufacturer
- model
- serial
- firmware
- options
- ports
- channels
- traces_per_channel
```

### Trace data

```text
TraceData
- stimulus: one-dimensional frequency/power/time array
- primary: one-dimensional response array
- secondary: optional second response array
- complex_data: optional complex array
- channel
- trace
- parameter
- format
- corrected
- metadata
```

For corrected data (`SDAT`/`SMEM`), combine interleaved real/imaginary values into a complex array. For formatted data (`FDAT`/`FMEM`), preserve primary and secondary arrays because the meaning depends on display format.

### Marker and analysis results

```text
MarkerReading
- stimulus
- primary
- secondary

BandwidthResult
- bandwidth
- center_frequency
- q
- loss

StatisticsResult
- span
- mean
- standard_deviation
- peak_to_peak

SearchPoint
- stimulus
- response
```

### Limit-test results

```text
LimitPointResult
- stimulus
- status: fail/pass/no-limit
- upper_limit
- lower_limit

LimitTestResult
- passed
- failed_stimulus
- points
```

Use NumPy arrays if already a project dependency and repository convention. Otherwise return ordinary sequences while avoiding a new heavy dependency.

## 4.4 Typed enums

Define enums, subject to repository conventions, for:

- `SweepType`: linear, logarithmic, segment, power;
- `SParameter`: S11, S21, S12, S22;
- `TraceFormat`: MLOG, PHAS, GDEL, SLIN, SLOG, SCOM, SMIT, SADM, PLIN, PLOG, POL, MLIN, SWR, REAL, IMAG, UPH, PPH;
- `TriggerSource`: internal, external, manual, bus;
- `DataTransferFormat`: ASCII, REAL64, REAL32;
- `ByteOrder`: normal, swapped;
- `SearchType`, `PeakPolarity`, `TargetTransition`;
- `ConversionFunction`;
- `CalibrationType`, `CalibrationStandardType`;
- `StateSaveType`;
- `HandlerDirection`;
- display/window layout enums if exposed.

Parse query responses using abbreviated uppercase forms.

---

# 5. Core analyser configuration

## 5.1 Preset and reset are not identical

Expose separate methods:

- `reset()` → `*RST`;
- `preset()` → `:SYST:PRES`;
- optionally `user_preset()` → `:SYST:UPR` when supported.

`*RST` sets channel 1 continuous initiation off, while `:SYST:PRES` sets channel 1 continuous initiation on (manual pp. 199, 479). Do not treat these commands as aliases.

Neither should run automatically during ordinary construction unless that is a repository-wide convention and explicitly documented. Automatic reset would destroy user setup and may disable/alter measurement state.

## 5.2 RF stimulus output

Expose `output_enabled` using `:OUTP` (manual p. 365).

Safety rules:

- do not enable RF output merely by opening a connection;
- do not automatically re-enable after receiver overload;
- document that port overload errors 221/222 automatically turn stimulus output off;
- provide a deliberate method such as `recover_output_after_overload()` only if it first checks/drains errors and requires an explicit call.

## 5.3 Sweep configuration

Per channel expose:

- sweep type;
- start/stop frequency;
- center/span frequency;
- CW frequency for power sweep;
- points, 2 to 1601;
- IF bandwidth;
- sweep delay;
- sweep time and automatic sweep-time mode;
- source power;
- optional attenuator range;
- optional per-port power coupling and levels;
- power slope enable/value;
- averaging enable/count/restart;
- system Z0 where supported.

Use unit-aware values if the repository supports them. SCPI transfers should use base units: hertz, seconds, dBm, ohms.

The driver should query instrument limits when feasible rather than duplicating every firmware/option-dependent bound. Where local validation is stable, validate early but still treat the instrument as authoritative.

### Log sweep constraint

The analyser requires approximately a two-octave minimum span for log sweep; otherwise it reports error 53 and changes to linear sweep. The driver should pre-validate that stop frequency is roughly four times or more the start frequency before selecting log sweep, while still checking the error queue after compound configuration.

## 5.4 Segment sweep

Expose a typed segment table rather than forcing users to construct the raw `:SENS<n>:SEGM:DATA` parameter stream.

Recommended segment model:

```text
SweepSegment
- start or center
- stop or span
- points
- if_bandwidth: optional
- power: optional
- delay: optional
- sweep_time: optional; zero may request automatic time
```

Recommended APIs:

```text
channel.set_segments(segments, mode="start_stop")
channel.get_segments()
channel.segment_total_points
channel.segment_total_time
channel.save_segments(path)
channel.load_segments(path)
```

The encoder must construct the header fields correctly:

```text
5,<mode>,<ifbw-enabled>,<power-enabled>,<delay-enabled>,<time-enabled>,<count>,...
```

See manual pp. 421–423.

Test mixed optional fields and verify the exact outgoing transcript.

## 5.5 Trace configuration

Per trace expose:

- measurement parameter;
- active selection;
- format;
- data trace visible;
- memory trace visible;
- copy data to memory;
- trace math operation;
- smoothing enable/aperture;
- electrical delay;
- phase offset;
- display scale, reference level, reference position, autoscale;
- optional conversion to impedance/admittance/inverse S-parameter.

The analyser supports S11, S21, S12, and S22 for the E5062A command set shown in the manual. Validate parameter availability against port count.

---

# 6. Triggering and measurement workflow

## 6.1 Model the trigger state machine

The instrument has system-wide Hold, Waiting-for-Trigger, and Measurement states plus per-channel Idle/Initiate states (manual pp. 80–82). Driver methods must not assume that sending a trigger always starts a sweep.

Expose:

- per-channel `continuous` via `:INIT<n>:CONT`;
- one-shot channel initiation via `:INIT<n>`;
- trigger source via `:TRIG:SOUR`;
- `abort()` via `:ABOR`;
- immediate trigger via `:TRIG`;
- blocking single measurement via `:TRIG:SING` plus `*OPC?`;
- bus trigger via `*TRG` where appropriate.

## 6.2 Preferred high-level measurement API

Provide a robust high-level method such as:

```text
measure(channel=1, traces=None, timeout=None, corrected=True)
```

Recommended sequence:

1. validate channel/trace indices;
2. configure only requested channels for initiation, preserving unrelated state where practical;
3. set trigger source to BUS or use `:TRIG:SING` independently of trigger source;
4. issue `:TRIG:SING`;
5. issue `*OPC?` and wait for `1` using a suitable timeout;
6. retrieve stimulus once per channel;
7. retrieve requested trace arrays;
8. inspect errors if the operation failed or returned malformed data;
9. return structured results.

`:TRIG:SING` is preferred because its command execution completes after all sweeps initiated by it finish and it can be paired with `*OPC?` (manual pp. 87–88, 484).

Do not use fixed sleep as the default synchronisation strategy. A wait-time fallback may exist only where transport limitations make proper synchronisation unavailable.

## 6.3 SRQ support

Optional advanced support may expose measurement-complete SRQ using:

- operation condition bit 4;
- negative transition filter bit 4;
- operation enable bit 4;
- status-byte operation-summary bit 7.

See manual pp. 84–86 and Appendix B.

This must be transport-gated. Raw TCP port 5025 lacks GPIB service-request behaviour. Polling and `*OPC?` remain the portable baseline.

---

# 7. Reading and writing measurement data

## 7.1 Data-array semantics

Support the four principal trace arrays:

- `SDAT`: corrected complex measurement data;
- `SMEM`: corrected complex memory data;
- `FDAT`: formatted display data;
- `FMEM`: formatted memory data.

See manual pp. 108–110 and 215–218.

Also support per-channel stimulus arrays with `:SENS<n>:FREQ:DATA?`.

High-level methods should make semantics explicit:

```text
trace.read_corrected() -> complex array
trace.read_corrected_memory() -> complex array
trace.read_formatted() -> primary/secondary arrays
trace.read_formatted_memory() -> primary/secondary arrays
channel.read_stimulus() -> numeric array
```

Do not label formatted data as complex unless the selected format actually uses real/imaginary primary/secondary values.

## 7.2 ASCII and binary formats

Support:

- `:FORM:DATA ASC`;
- `:FORM:DATA REAL` for IEEE-754 64-bit floats;
- `:FORM:DATA REAL32` for IEEE-754 32-bit floats;
- `:FORM:BORD NORM|SWAP`.

See manual pp. 104–107, 337–338.

Important behaviour:

- `:SYST:PRES` and `*RST` do not reset data format or byte order;
- do not assume factory defaults after reset;
- a public data-read method should either set the required format explicitly for each transfer or use a context manager that restores the previous format;
- binary payloads are IEEE-488.2 definite-length blocks followed by a terminator;
- validate payload byte count against element width;
- reject incomplete blocks and odd/unexpected payload lengths;
- decode byte order exactly as configured.

Prefer REAL32 for throughput if precision is sufficient and repository conventions allow a caller-selectable choice. Default to REAL64 if preserving full analyser transfer precision is more important.

## 7.3 Binary-block parser requirements

The block parser must:

1. read `#`;
2. read the digit-count character;
3. read exactly that many length digits;
4. parse payload length;
5. read exactly payload-length bytes;
6. consume the trailing message terminator without treating it as payload;
7. decode as 32- or 64-bit IEEE float using selected endianness;
8. verify expected element count where known.

Do not rely on newline-delimited reads for binary payloads.

## 7.4 Writing trace arrays is advanced and hazardous

Commands can write `FDAT`, `FMEM`, `SDAT`, and `SMEM`. Expose writes only through explicit methods such as:

```text
trace.write_formatted_data(...)
trace.write_formatted_memory(...)
```

Avoid ordinary property setters because writes replace internal arrays and can mislead users into believing displayed data came from a fresh measurement.

Validate that the caller supplies exactly two numeric values per sweep point. For corrected arrays, interpret pairs as real/imaginary. For formatted arrays, preserve primary/secondary semantics.

---

# 8. Calibration and error correction

## 8.1 Calibration must be procedural

Calibration is a multi-step operation with physical user intervention. Do not represent it as a single casually settable property.

Recommended API layers:

### Low-level calibration object

```text
channel.calibration.select_kit(number)
channel.calibration.select_response_open(port)
channel.calibration.select_response_short(port)
channel.calibration.select_response_thru(response_port, stimulus_port)
channel.calibration.select_enhanced_response(response_port, stimulus_port)
channel.calibration.select_solt1(port)
channel.calibration.select_solt2(port1, port2)
channel.calibration.acquire_open(port)
channel.calibration.acquire_short(port)
channel.calibration.acquire_load(port)
channel.calibration.acquire_thru(response_port, stimulus_port)
channel.calibration.acquire_isolation(response_port, stimulus_port)
channel.calibration.calculate_and_apply()
channel.calibration.clear()
```

### High-level guided procedures

If repository style permits callbacks or iterators, provide a guided procedure that yields required connection steps rather than attempting physical calibration autonomously.

```text
for step in channel.calibration.solt2_steps(1, 2):
    user_connects(step.standard, step.ports)
    step.acquire()
channel.calibration.finish()
```

Every acquisition command must complete before the next begins. Use `*OPC?` after each acquisition. The manual warns that issuing another calibration acquisition before the current one completes aborts the current operation (manual p. 60).

## 8.2 Required calibration data

Implement or document the matrix from manual p. 61:

- response OPEN: OPEN required, LOAD optional;
- response SHORT: SHORT required, LOAD optional;
- response THRU: THRU required, isolation optional;
- enhanced response: reflection standards on response port, THRU, optional isolation;
- full 1-port: OPEN, SHORT, LOAD;
- full 2-port: OPEN/SHORT/LOAD on both ports, bidirectional THRU, optional bidirectional isolation.

`calculate_and_apply()` maps to `:SENS<n>:CORR:COLL:SAVE`. This command clears measured calibration data and calibration-type selection after calculating coefficients; error correction is enabled automatically (manual p. 62 and p. 407).

## 8.3 ECal

Expose explicit ECal operations:

- full one-port;
- full two-port;
- enhanced response;
- response THRU;
- isolation enable.

ECal is long-running and requires an attached module. Use `*OPC?` and then inspect the error queue. If multiple ECal modules are attached, the instrument uses the first module’s kit data (manual p. 63).

Do not claim ECal succeeded solely because the write returned.

## 8.4 Calibration kits

Calibration-kit editing is advanced. It may be a second implementation phase but should be designed for:

- kit selection and label;
- 21 standard definitions;
- standard type and label;
- C0–C3, L0–L3;
- offset delay, loss, Z0;
- arbitrary impedance;
- OPEN/SHORT/LOAD/THRU class assignments;
- kit reset.

Use typed standard objects and validate port/standard indices.

## 8.5 Correction and extensions

Expose:

- error correction enable;
- applied calibration type per trace;
- port extension enable and delay per port;
- velocity factor;
- electrical delay and phase offset on traces;
- optional calibration coefficient readout.

Calibration coefficient queries return interleaved complex values and should be decoded to complex arrays.

---

# 9. Markers and analysis

## 9.1 Markers

Provide markers 1–9 and reference marker 10.

Expose:

- visibility;
- activation;
- stimulus position;
- primary/secondary response;
- discrete mode;
- reference-marker mode;
- marker coupling;
- set sweep start/stop/center, reference level, or delay from marker.

Marker reads must return two response values because Smith/polar formats use both.

## 9.2 Marker search

Expose search range and search types:

- maximum/minimum;
- peak, left peak, right peak;
- target, left target, right target;
- peak excursion and polarity;
- target value and transition;
- execute and tracking.

Errors 40 and 41 indicate target/peak not found. Translate these into a specific search-result exception or a `None`/empty result according to repository conventions, but do not leave the caller blocked waiting for a query response that the instrument will not send.

## 9.3 Analysis command

Expose trace analysis independent of marker position:

- peak-to-peak;
- standard deviation;
- mean;
- max/min;
- peak/all peaks;
- all targets;
- optional analysis domain.

Query `:CALC<n>:FUNC:POIN?` before `:CALC<n>:FUNC:DATA?`, then parse response/stimulus pairs.

## 9.4 Bandwidth, notch, and statistics

Expose structured methods:

```text
trace.bandwidth(marker=1, threshold=-3)
trace.notch(marker=1, threshold=-3)
trace.statistics()
trace.flatness()
trace.filter_statistics()
```

Bandwidth/notch queries may return no response if the search is impossible and instead generate an error. Implement timeout-safe query handling and inspect `:SYST:ERR?` on failure.

---

# 10. Limit, bandwidth-limit, and ripple tests

## 10.1 Limit table

Expose a typed list of up to 100 segments:

```text
LimitSegment
- kind: off, upper, lower
- stimulus_start
- stimulus_stop
- response_start
- response_stop
```

Encode/decode `:CALC<n>:LIM:DATA` exactly. Support clearing with a zero segment count.

Expose:

- enable;
- line visibility;
- clipped/whole-line display;
- trace pass/fail;
- failed point count and stimulus values;
- full per-point report including pass/fail/no-limit and upper/lower limits;
- amplitude and stimulus offsets where firmware supports them.

## 10.2 Result hierarchy

The manual provides results at several levels:

- per point via limit reports;
- per trace via `:CALC<n>:LIM:FAIL?`;
- per channel via questionable-limit status registers;
- overall via questionable status bit 10.

The high-level API should prefer direct query commands for trace/point results and reserve status-register decoding for channel/overall results.

## 10.3 Bandwidth and ripple limit tests

These can be a second-phase feature, but design them as trace-level objects with typed settings and structured reports. Gate them by firmware.

---

# 11. Display and automation controls

Expose ordinary display controls where useful:

- display update enable;
- update once;
- frequency annotation;
- clock;
- title and title text;
- autoscale;
- trace/data visibility;
- window and graph layouts;
- echo window text;
- screen image save.

## 11.1 Display-update optimisation

Provide a context manager if repository style permits:

```text
with instrument.display_updates(False, refresh_on_exit=True):
    ... configure, measure, read arrays ...
```

The context must restore display updates even when an exception occurs. Turning updates off improves command throughput; `:DISP:UPD` updates once while continuous update remains off (manual pp. 163, 312, 318).

## 11.2 Front-panel locks

The analyser does not automatically enter a remote mode; front-panel, keyboard, mouse, and touchscreen remain operable during remote communication (manual p. 38).

Expose explicit methods or a context manager for:

- keyboard/front-panel lock;
- mouse/touchscreen lock.

Never lock controls during construction. Always provide an exception-safe unlock path.

---

# 12. File management and instrument state

## 12.1 State save/recall

Expose:

- save type: state only, state+calibration, state+trace, all;
- save all versus displayed channels/traces;
- save state file;
- load state file;
- channel state registers A–D;
- calibration-coefficient registers A–D.

The filename `autorec.sta` has power-on auto-recall semantics. Do not create or overwrite it without a clearly named method and explicit user request.

## 12.2 Internal filesystem

Expose advanced methods:

- catalog directory;
- make directory;
- copy;
- delete;
- transfer file to/from analyser;
- save trace CSV;
- save screen image;
- save/load segment and limit tables.

Safety requirements:

- file deletion must be an explicit method, never a property setter;
- recursive directory deletion must be documented;
- overwrite behaviour must be explicit;
- validate extensions where the command requires `.sta`, `.csv`, `.bmp`, or `.png`;
- normalise path separators conservatively without converting analyser paths into host filesystem paths;
- never expose arbitrary host filesystem operations as if they operated on analyser storage.

## 12.3 File transfer limits

The manual gives different block-size limits for GPIB and LAN for `:MMEM:TRAN`. Implement chunked transfer if the transport or command requires it, and test definite-length block framing in both directions.

---

# 13. Handler I/O

Handler I/O is valuable for automated test systems but should be isolated in an advanced `handler_io` component.

Expose:

- port A/B 8-bit output;
- port C/D 4-bit input/output plus direction;
- port E combined 8-bit input/output;
- port F combined 16-bit output;
- output 1/2 control;
- INDEX enable;
- READY-FOR-TRIGGER enable.

Important semantics:

- logic is active-low: binary `1` corresponds to low level for handler data bits;
- C and D default to input at power-on;
- B6/B7 are unavailable as ordinary data bits while INDEX/READY-FOR-TRIGGER outputs are enabled;
- writing output ports generates write-strobe behaviour;
- handler I/O power and electrical limits are hardware facts, not software validation guarantees.

Use integer range validation:

- A/B/C/D/E/F according to 8/8/4/4/8/16-bit widths;
- direction must be configured before writing C/D/E.

Do not automatically change direction on every read/write unless the API name makes that side effect explicit.

---

# 14. Status and error handling

## 14.1 Error queue

`:SYST:ERR?` returns the oldest queued error and removes it. The queue holds up to 100 errors (manual p. 476).

Provide:

```text
read_error() -> InstrumentErrorRecord
drain_errors(limit=100) -> list[InstrumentErrorRecord]
check_errors() -> None or raises
clear_status()
```

Do not drain errors invisibly after every scalar setter; doing so adds latency and destroys diagnostic ordering. Prefer explicit checks after compound/high-risk operations and in tests.

Manual-operation and VBA COM-object errors are not necessarily returned by `:SYST:ERR?`; document that limitation.

## 14.2 Status registers

Expose raw register read/write methods and decoded helpers for:

- status byte;
- standard event status;
- operation condition/event/enable/transition filters;
- questionable status;
- limit/bandwidth/ripple status hierarchies.

Use named bit masks or `IntFlag` enums.

Important bits include:

- operation condition bit 4: measurement active;
- operation condition bit 5: waiting for trigger;
- status byte bit 2: error/event queue;
- bit 4: message available;
- bit 5: standard event summary;
- bit 7: operation summary;
- questionable condition bits 8/9/10: bandwidth/ripple/limit summaries.

Event-register reads may clear the event register; condition-register reads do not. Preserve this distinction in method names and documentation.

## 14.3 Exception mapping

At minimum recognise and provide clearer messages for:

- 20 additional calibration standard needed;
- 21 overlapping ports;
- 22 calibration method not selected;
- 32 ECal module not in appropriate RF path;
- 40 target not found;
- 41 peak not found;
- 50 hidden channel activation;
- 51 nonexistent trace;
- 53 invalid logarithmic sweep span;
- 61 power unleveled;
- 100–107 file failures;
- 200 option not installed;
- 220 PLL unlocked;
- 221/222 receiver overload and output shutdown;
- standard IEEE command, execution, query, and block-data errors.

Do not create an enormous bespoke exception hierarchy if repository convention uses one instrument exception. A parsed record plus a few safety-critical specialised exceptions is sufficient.

---

# 15. Hazardous and advanced operations

The following must not appear as casual properties and must never run during initialisation:

- `:SYST:POFF` instrument shutdown;
- `:SYST:SEC:LEV` security changes;
- internal file deletion/copy/overwrite;
- VBA project load/run/stop;
- writing trace arrays;
- calibration-kit modification/reset;
- calibration coefficient clearing;
- front-panel/mouse lock;
- RF output enable;
- state reset/preset;
- arbitrary handler output changes.

Use explicit imperative names such as:

```text
power_off()
delete_file(path)
run_macro(name)
clear_calibration()
lock_front_panel()
```

Where practical, require confirmation flags for destructive operations, consistent with repository policy.

---

# 16. Test strategy

All core functionality must be testable without hardware.

## 16.1 Identification and capabilities

Test:

- Agilent and accepted Keysight manufacturer strings;
- exact E5062A matching;
- rejection of E5061A and unrelated ENA models;
- firmware parsing;
- option parsing;
- dynamic port/channel/trace counts.

## 16.2 Scalar command tests

For each public property/method, verify:

- exact SCPI command;
- query parsing;
- enum round trip;
- unit conversion;
- index validation;
- no unintended extra queries/writes.

## 16.3 Active selection tests

Test that:

- selecting a hidden channel/trace raises or follows the documented display-selection policy;
- trace-scoped commands select the intended trace;
- operations do not rely on stale cached active state;
- concurrent callers are serialised if the repository supports threading.

## 16.4 Measurement transcript

A canonical one-channel S21 workflow should assert a transcript similar to:

```text
:SYST:PRES
:CALC1:PAR:COUN 1
:CALC1:PAR1:DEF S21
:CALC1:PAR1:SEL
:SENS1:SWE:TYPE LIN
:SENS1:FREQ:STAR ...
:SENS1:FREQ:STOP ...
:SENS1:SWE:POIN ...
:SENS1:BAND ...
:SOUR1:POW ...
:OUTP ON
:TRIG:SOUR BUS
:INIT1:CONT ON
:TRIG:SING
*OPC?
:SENS1:FREQ:DATA?
:CALC1:DATA:SDAT?
```

Exact sequence should follow the final API design and avoid reset/output enable unless requested.

## 16.5 Binary-block tests

Test:

- REAL32 normal order;
- REAL32 swapped order;
- REAL64 normal order;
- REAL64 swapped order;
- one and many values;
- complex pair conversion;
- formatted primary/secondary deinterleaving;
- malformed header;
- truncated payload;
- payload length not divisible by element size;
- extra trailing bytes;
- terminator consumption;
- data format and byte order not assumed after reset.

Use known byte fixtures generated independently of the parser.

## 16.6 Segment and limit table tests

Test exact flattening/unflattening of:

- all optional segment fields disabled;
- each optional field enabled independently;
- mixed segment values;
- maximum valid segment/limit counts where practical;
- zero-count clear operations;
- malformed response lengths.

## 16.7 Calibration tests

Transcript-test:

- response calibration;
- one-port SOLT;
- two-port SOLT including both THRU directions;
- optional isolation;
- `*OPC?` after every acquisition;
- finish only after all required standards;
- error on duplicate ports;
- ECal timeout/error handling.

## 16.8 Trigger tests

Test:

- continuous internal mode;
- bus-trigger one-shot;
- `:TRIG` versus `:TRIG:SING` semantics;
- measurement-complete polling;
- timeout and abort;
- raw-socket fallback without SRQ.

## 16.9 Error and safety tests

Test that:

- overload errors do not auto-enable RF output;
- construction sends no reset, output-enable, lock, shutdown, or file-delete commands;
- destructive methods require explicit calls;
- context managers restore display and lock states after exceptions;
- query failures that produce no response are converted into deterministic exceptions rather than indefinite hangs.

---

# 17. Documentation and examples

Provide at least these examples using the repository’s actual API:

## 17.1 Basic S21 measurement

- connect;
- configure linear sweep;
- select S21;
- set points, IF bandwidth, and power;
- explicitly enable RF output;
- perform one blocking measurement;
- retrieve frequency and complex S21 data;
- disable output in `finally` if the example owns output state.

## 17.2 Two-trace measurement

- S11 and S21 on one channel;
- configure trace formats;
- measure once;
- retrieve both traces using a single stimulus array.

## 17.3 Marker bandwidth analysis

- move marker to maximum;
- perform minus-3-dB bandwidth search;
- print bandwidth, center, Q, and loss;
- handle “not found” cleanly.

## 17.4 Calibration workflow

- choose kit;
- guide OPEN/SHORT/LOAD/THRU connections;
- wait after each acquisition;
- calculate/apply coefficients;
- save state with calibration.

## 17.5 High-throughput acquisition

- disable display updates in a context manager;
- use REAL32 or REAL64 binary transfer;
- perform repeated blocking measurements;
- update display once or restore updates on exit.

Examples must not hide RF-output and calibration side effects.

---

# 18. Suggested implementation order

## Phase 1 — repository-conformant measurement core

- identity and capabilities;
- channels/traces;
- sweep, power, IFBW, points, averaging;
- output enable;
- trigger and blocking `measure()`;
- stimulus and corrected/formatted arrays;
- ASCII and binary transfer;
- error queue;
- tests and basic documentation.

## Phase 2 — analysis and state

- markers;
- peak/target search;
- bandwidth/notch/statistics;
- memory trace and trace math;
- state save/recall;
- display-update optimisation;
- limit tables and reports.

## Phase 3 — calibration

- guided manual calibration;
- ECal;
- calibration kits;
- port extension and applied-calibration inspection;
- calibration coefficient query.

## Phase 4 — advanced automation

- file transfer;
- handler I/O;
- SRQ support;
- ripple/bandwidth limit status;
- screen/image operations;
- macro integration only if repository scope justifies it.

A broad but shallow wrapper is less useful than a thoroughly tested Phase 1 plus selected Phase 2 features.

---

# 19. Acceptance criteria

The implementation is complete when:

1. the repository identifies an E5062A without matching unrelated models;
2. construction is side-effect minimal;
3. a user can configure and perform a complete S-parameter measurement through the public API;
4. channel/trace/marker indexing is validated and discoverable;
5. `:TRIG:SING` plus `*OPC?` provides reliable blocking measurement;
6. corrected data are returned as complex values with a matching stimulus array;
7. formatted data preserve primary/secondary semantics;
8. REAL32 and REAL64 binary blocks work in both byte orders;
9. reset and preset semantics are distinct;
10. RF output, calibration, file deletion, locking, and shutdown are explicit operations;
11. firmware/option-dependent features are gated;
12. calibration acquisitions are synchronised and test-covered;
13. errors and no-response query failures produce deterministic Python exceptions;
14. unit tests pass without hardware and include transcript and malformed-binary cases;
15. documentation includes at least one safe end-to-end measurement example.

---

# 20. Manual cross-reference

Use these sections while implementing:

- remote control and transport: pp. 24–38;
- active channel/trace and setup: pp. 40–58;
- calibration: pp. 60–78;
- trigger and measurement completion: pp. 80–88;
- markers and analysis: pp. 90–101;
- data transfer and internal arrays: pp. 104–118;
- limit tests: pp. 120–130;
- file management: pp. 132–145;
- handler I/O: pp. 148–160;
- automation and performance: pp. 162–168;
- SCPI command reference: pp. 194–497;
- firmware compatibility: pp. 500–503;
- status reporting: pp. 506–524;
- errors: pp. 526–537.

When the task-based chapters and command reference appear inconsistent, prefer the detailed command reference plus firmware-change appendix, and add a regression test for the chosen behaviour.