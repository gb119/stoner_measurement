# Keithley 182 Sensitive Digital Voltmeter — driver programming guide

**Audience:** an LLM coding agent implementing a concrete Keithley Model 182 driver in
`src/stoner_measurement/instruments/nanovoltmeter.py`.

**Primary source:** Keithley *Model 182 Sensitive Digital Voltmeter Instruction Manual*, Section 4, IEEE-488 Reference
(especially §§4.2–4.5, pp. 4-1 to 4-57). Command-page citations below refer to that manual.

> **Important implementation constraint:** This is a legacy IEEE-488 instrument, **not a SCPI instrument**. Do not send
> `*IDN?`, `MEAS:VOLT?`, `CONF`, or newline-delimited SCPI command strings. Its protocol is compact one-letter
> device-dependent commands, plus IEEE-488 bus management and a talk/listen transaction model.

## 1. Scope and implementation policy

Implement `Keithley182` as a subclass of the existing nanovoltmeter abstraction. Preserve the abstraction's public
method/property names, types, lifecycle, error classes, connection handling, and metadata conventions. Add
Model-182-specific implementation behind those existing hooks.

Follow this priority order:

1. **Implement the existing base-class contract first.** A caller using the generic nanovoltmeter interface must be
   able to configure a voltage measurement and get a float reading.
2. **Expose stable Model-182-only features through clearly named extension methods/properties** rather than weakening
   generic semantics.
3. **Do not claim read-back unless it is actually queried.** The Model 182 provides rich status output via `U`
   commands; use it to confirm state where needed.
4. **Never perform calibration commands automatically.** `C` commands can alter calibration; expose them only behind an
   explicit, privileged calibration API (§4.2.3).

## 2. Transport and IEEE-488 rules

### 2.1 Required transport capabilities

The driver needs a GPIB/IEEE-488 resource that can:

- write an ASCII command message to the instrument;
- address the instrument to talk and read a complete response;
- preserve/recognise EOI, or use an explicitly selected terminator;
- set or honour the instrument primary address; and
- ideally obtain the serial-poll status byte.

Use the project’s established transport wrapper. Do **not** embed direct PyVISA calls if the surrounding driver
architecture centralises IO.

### 2.2 Remote mode

The meter accepts device-dependent commands only in remote. At connection/initialisation:

1. Set the controller to remote mode using the transport/framework mechanism.
2. Address the configured GPIB primary address.
3. Disable the front-panel `LOCAL` condition if the transport offers this operation; the manual documents `REMOTE`,
   `LOCAL`, and `LLO` as general bus controls (§4.3.1–§4.3.3).
4. Send a benign status query such as `U0` and read the response to verify communication.

Do not use a power-reset style clear as routine initialisation. `DCL`/`SDC` reset the Model 182 to power-up defaults
(§4.3.5); only expose reset explicitly.

### 2.3 Command grammar

A device-dependent command is one ASCII letter followed by an option character or numeric value. Letters are
case-insensitive. Examples:

```text
R0          # autorange
B1          # 6½-digit resolution
S0          # line-cycle integration
T1          # one-shot on talk
I1,100      # linear 100-reading buffer
```

Key grammar rules (§4.2):

- Multiple commands may be sent in one string.
- A command may be written in either order; the meter applies commands using its own hierarchy, not textual order.
- Use `X` as the execution delimiter. It executes all device-dependent commands received since the preceding `X`.
- A final `X` is required for deterministic configuration; a `talk` operation also causes pending commands to execute.
- For parameterised commands, use `LETTER<option>,<value>` with no arbitrary whitespace.
- The meter accepts fixed-point numeric values and accepts exponents. Format finite values explicitly and reject
  `NaN`/infinity before writing.
- Command errors are retained until read/corrected; after an invalid command, later commands in the same string
  (including the next `X`) are ignored (§4.5.1).

Centralise this behaviour in a private command builder, rather than scattering literal protocol strings across
properties.

Suggested private operations (adapt names to the existing base class):

```python
_send_config(*commands)       # join validated commands and append X
_talk(*commands)              # configure/select output, then read one response
_query_status(selector)       # U0–U14 alternate-output query
_parse_reading(reply)         # convert a Model-182 reading to float + metadata
_check_errors()               # inspect U1 and raise the project error type
```

### 2.4 Termination

The default output terminator is carriage-return / line-feed. `Y` selects alternative terminators (§4.2.24). Keep the
default unless the project transport has a documented incompatibility. If a different terminator is necessary, send
`Y<n>X` once during initialisation and configure the transport reader to match it.

Do not assume every response ends with `\n` alone. Strip the transport terminator and EOI cleanly, but do not strip
meaningful internal separators.

## 3. Safe driver initialisation

The factory/power-up state is approximately: 30 V range, 6½ digits, A/D reading source, filters off, medium
digital-filter response, 250 ms trigger interval, one-shot external trigger, and reading-relative disabled (Table 4-4
/ §4.4).

Do not rely on those defaults. Initialise only the settings required by the existing nanovoltmeter API, for example:

```text
R0 B1 S0 P2 N1 T1 F0 G0 X
```

This means: autorange, 6½ digits, line-cycle integration, medium digital response, filters enabled, one-shot-on-talk
trigger, latest A/D reading source, value-only output, execute.

The exact default profile must follow the established generic driver defaults. Prefer a conservative measurement
profile for nanovolt work: autorange only when requested, a line-cycle integration time, filters enabled, and a
non-streaming one-shot trigger.

After configuring, query `U0` and `U1`. Raise an instrument/protocol exception if an error bit is set. Do not silently
continue after `INVALID COMMAND`, `INVALID FORMAT`, `INVALID OPTION`, `NOT IN REMOTE`, or `TRIGGER NOT READY`
(§4.5.1).

## 4. Reading measurements

### 4.1 Recommended normal read path

For a single synchronous reading:

1. Select A/D source: `F0`.
2. Select a parseable output format: `G0` for numeric value only, or `G1` for a reading prefixed by `NDCV`/`RDCV`.
3. Select trigger source/mode: `T1` (one-shot on talk) is the simplest compatible strategy.
4. Address the meter to talk and read the response.
5. Parse the numeric reading, validate it is finite, then check `U1`/serial-poll status when the transport permits.

A compact command sequence is `F0G0T1X`; then perform the talk/read operation. `F0` sends the latest A/D reading, and
`T1` makes talk trigger a one-shot measurement (§§4.2.5, 4.2.19).

### 4.2 Parsing output

`G0` returns only a reading, suitable for conversion using `float()`. `G1` and richer modes include a prefix, for
example `NDCV+1.820000E+00` (§4.2.6).

Implement a parser that supports every reading form the driver itself enables:

- prefixes: `NDCV` (normal), `RDCV` (reading-relative), `NMAX`, and `NMIN`;
- signed decimal/scientific numeric value;
- optional comma-separated buffer location and timestamp; and
- EOI/selected terminator.

For the generic `reading`/`measure` method, use `G0` and return a plain `float` in volts. For a Model-182 extension
that returns metadata, use a `G` mode containing buffer location/time and return a structured result, not a positional
tuple with undocumented fields.

### 4.3 Trigger-not-ready and overflow

`TRIGGER NOT READY` means the meter received a trigger while it was still processing the preceding one. Treat it as a
retryable acquisition-state error only when the caller has requested retry; otherwise raise an explicit exception.
`OVERFLOW` indicates the selected range has been exceeded. It must not be converted to a plausible floating-point
reading.

## 5. Mapping to the nanovoltmeter API

The concrete mapping must follow the actual abstract/concrete members present in
`src/stoner_measurement/instruments/nanovoltmeter.py`. The following map identifies the expected implementation
semantics; adapt exact property names only where the established project API differs.

| Generic capability      | Model 182 implementation    | Command(s)        | Notes                                  |
| ----------------------- | --------------------------- | ----------------- | -------------------------------------- |
| Read voltage /          | Latest conversion, one-shot | `F0`, `T1`, `G0`  | Return volts as `float`.               |
| `reading` / `measure()` | on talk                     | or `G1`           |                                        |
| Measurement range       | Autorange or fixed          | `R0`, `R1`–`R5`,  | Ranges are 3 mV, 30 mV, 300 mV, 3 V,   |
|                         | full-scale range            | `R8`              | 30 V. `R8` disables autoranging while  |
|                         |                             |                   | retaining the present range.           |
| Resolution / digits     | Display/conversion          | `B0`–`B3`         | B0=5½, B1=6½, B2=3½, B3=4½ digits.     |
|                         | resolution                  |                   |                                        |
| Integration time /      | One line cycle, 3 ms, or    | `S0`–`S2`         | This is not a modern numeric NPLC      |
| NPLC-equivalent         | 100 ms                      |                   | setting; expose the three supported    |
|                         |                             |                   | choices only.                          |
| Filter enable           | Enable/disable both filters | `N1` / `N0`       | A global enable gate.                  |
| Digital filter response | Off, fast, medium, slow     | `P0`–`P3`         | Keep separate from global filter       |
|                         |                             |                   | enable.                                |
| Analogue filter enable  | Off/on                      | `O0` / `O1`       | Only meaningful when filters are       |
|                         |                             |                   | enabled.                               |
| Trigger mode            | On talk, GET, X, external,  | `T0`–`T10`        | Generic API normally needs only `T1`;  |
|                         | manual                      |                   | expose other modes as an extension.    |
| Trigger interval        | Interval between readings   | `Q<seconds>`      | Valid 10 ms–999.999 s.                 |
|                         | in multiple mode            |                   |                                        |
| Trigger delay           | Delay before a one-shot     | `W0` /            | Valid 1 ms–999.999 s; has effect only  |
|                         | conversion                  | `W<seconds>`      | in one-shot mode.                      |
| Relative/null reading   | Enable/disable; use         | `Z0`–`Z3`         | Do not conflate this with the generic  |
|                         | next/explicit/prior         |                   | API’s software offset unless semantics |
|                         | baseline                    |                   |                                        |
|                         |                             |                   | match.                                 |
| Device errors/status    | Alternate output status     | `U0`, `U1`        | Parse all error bits.                  |
| Reset                   | IEEE-488 device clear       | transport DCL/SDC | Explicit/destructive operation only.   |

### 5.1 Range

Provide a mapping from generic range values in volts to `R1`–`R5`:

```text
R1 = 3 mV
R2 = 30 mV
R3 = 300 mV
R4 = 3 V
R5 = 30 V
R0 = autorange
R8 = disable autorange, retain current range
```

Do not represent `R8` as a range value. It is a mode action. If the base class has an `auto_range` property, map
`True` to `R0`; map `False` to `R8` only when the desired fixed range is not separately specified.

### 5.2 Resolution and integration

The display-resolution command affects the resolution of readings supplied over IEEE-488. Map driver resolution/digits
to these exact choices only:

```text
B0 = 5½ digits
B1 = 6½ digits
B2 = 3½ digits
B3 = 4½ digits
```

The integration setting is discrete and line-frequency dependent:

```text
S0 = one power-line cycle (16.67 ms at 60 Hz; 20 ms at 50 Hz)
S1 = 3 ms
S2 = 100 ms
```

If the generic API uses NPLC, expose a constrained conversion rather than pretending that arbitrary NPLC is supported.
Use a separate Model-182 integration-period property/enum if exact representation matters.

### 5.3 Filters

The Model 182 has three distinct concepts:

1. `N0`/`N1`: master disable/enable for **both** filters;
2. `O0`/`O1`: analogue filter state; and
3. `P0`–`P3`: digital filter response (`off`, `fast`, `medium`, `slow`).

Do not collapse these into one Boolean unless the generic API has no richer concept. For the generic interface,
implement the documented default behaviour and offer Model-182-specific properties for digital response and analogue
filter state.

## 6. Model-182 extension API

Keep these capabilities out of a generic voltage-reading method. Use a dedicated extension mixin, capability protocol,
or explicit `Keithley182` methods/properties.

### 6.1 Buffered acquisition

The 1024-reading buffer is a significant capability not normally represented by a simple nanovoltmeter abstraction.
Commands:

```text
I0              disable buffer
I1,<length>     linear buffer, length 1–1024
I2              circular buffer, length 1–1024
F1              send one reading from buffer
F2              send all buffer readings
F3 / F4         maximum / minimum buffer reading
G2–G7           add location/time fields to output
U3–U5           buffer length, average, standard deviation
```

Recommended extension surface:

```python
configure_buffer(mode: Literal["linear", "circular"], length: int) -> None
clear_buffer() -> None
read_buffer(*, include_location: bool = True, include_time: bool = True) -> list[BufferedReading]
buffer_statistics() -> BufferStatistics
```

Important protocol details:

- A linear buffer stops storing at the configured length; a circular buffer overwrites oldest readings.
- Buffer position and timestamp are only meaningful when buffer operation is enabled.
- `F2` can return a multiple-reading response. Parse it as a stream of individual formatted readings, not one number.
- Reading availability and bus hold-off modes (`K`) can intentionally block a read; do not enable them implicitly.

### 6.2 Triggering

The generic one-shot measurement path should use `T1`. Expose the rest as advanced configuration:

```text
T0   multiple on talk       T1   one-shot on talk
T2   multiple on GET        T3   one-shot on GET
T4   multiple on X          T5   one-shot on X
T6   multiple on external   T7   one-shot on external
T8   multiple on manual     T9   one-shot on manual
T10  disable all triggers
Q<seconds>  multiple-trigger interval, 0.010–999.999 s
W<seconds>  one-shot trigger delay, 0.001–999.999 s
H0          immediate manual trigger
```

External trigger, GET, manual trigger, trigger interval, and trigger delay do not have a safe universal equivalent in
a basic nanovoltmeter API. Surface them in explicit extension methods and document their stateful interaction with
buffering and reading source.

### 6.3 Status, errors, serial polling, and SRQ

Implement `U0` (machine state) and `U1` (error status) parsers. `U1` is essential for meaningful protocol error
reporting. Its significant bits include invalid command/format/option, not in remote, trigger overrun, overflow,
NVRAM/RAM/calibration failures, calibration lock/error, A/D communication failure, front-panel failure, and trigger not
ready.

Serial-poll status has ready, error, buffer, and reading-availability conditions. The `M` commands choose which
conditions assert SRQ:

```text
M0 disable SRQ       M1 reading done       M2 buffer full
M4 buffer half full  M8 reading overflow   M16 ready for command
M32 error            M128 ready for trigger
```

Expose SRQ configuration only when the underlying transport can reliably serial-poll and wait for SRQ. Otherwise, do
not advertise SRQ support. Never infer a completed asynchronous operation solely from a timeout.

### 6.4 Reading-relative versus analogue-output-relative

`Z` controls **reading-relative** measurement values:

```text
Z0  off
Z1  set baseline from next reading
Z2,<value>  use explicit baseline
Z3  use previous baseline
```

`J` controls **analogue-output-relative** operation, which is separate:

```text
J0  off
J1  set from next output value
J2,<value>  explicit relative value
J3  previous relative value
```

Treat reading-relative as an advanced measurement transformation. Do not silently enable it when implementing a
software offset in the generic API.

### 6.5 Analogue output and source mode

The rear analogue output can report measurement data, or the instrument can operate as a programmable source:

```text
V0,<gain>   normal analogue-output mode; gain 0.001–999.999
V1,<value>  source mode; output −3.3 V to +3.3 V
J0–J3       analogue-output-relative controls
U7 / U8     query analogue-output relative value / gain
```

This is **not** a nanovoltmeter function. Do not map it onto voltage measurement range, setpoint, or output in the
generic driver. Implement it only as a clearly marked, opt-in extension. Entering source mode changes the instrument’s
role and must be an explicit user action.

### 6.6 Persistent setup and front-panel display

```text
L0  save current configuration as power-up setup
L1  restore factory defaults
L2  recall saved user setup
A0  restore normal display
A1,<string>  display temporary ASCII message
A2,<string>  store display string in EEPROM
A3  display stored string
```

These are not part of ordinary measurement configuration. `L0`, `L1`, and `L2` have persistent/destructive effects;
provide them only as explicit administrative methods. Do not run them during normal `connect()` or `close()`.

### 6.7 Calibration

`C` commands calibrate the measurement and analogue output paths. Commands can modify stored instrument calibration.
They require a privileged, explicit calibration API and an appropriate calibration-lock check (`U12`). They must never
be sent by automatic setup, test discovery, or recovery logic.

## 7. Command reference for implementation

The following is an implementation-oriented command index. Validate option values locally before writing them.

| Function                     | Commands                                           |
| ---------------------------- | -------------------------------------------------- |
| Display message              | `A0`, `A1,string`, `A2,string`, `A3`               |
| Resolution                   | `B0`–`B3`                                          |
| Calibration                  | `C0`–`C8,value`                                    |
| Digital filter damping alias | `D0`, `D1`                                         |
| Reading source               | `F0`–`F4`                                          |
| Reading output fields        | `G0`–`G7`                                          |
| Manual trigger / memory test | `H0`, `H1`                                         |
| Buffer                       | `I0`, `I1,length`, `I2`                            |
| Analogue-output relative     | `J0`–`J3`                                          |
| EOI / hold-off               | `K0`–`K3`                                          |
| Setup save/recall            | `L0`–`L2`                                          |
| SRQ mask                     | `M0`, `M1`, `M2`, `M4`, `M8`, `M16`, `M32`, `M128` |
| Global filter enable         | `N0`, `N1`                                         |
| Analogue filter              | `O0`, `O1`                                         |
| Digital filter response      | `P0`–`P3`                                          |
| Multiple-trigger interval    | `Qseconds`                                         |
| Range                        | `R0`–`R5`, `R8`                                    |
| Integration period           | `S0`–`S2`                                          |
| Trigger source/mode          | `T0`–`T10`                                         |
| Alternate/status output      | `U0`–`U14`                                         |
| Analogue output config       | `V0,gain`, `V1,value`                              |
| Trigger delay                | `W0`, `Wseconds`                                   |
| Execute                      | `X`                                                |
| Terminator                   | `Y0`, `Y1`, `Y2`, `Y3`, `Y10`, `Y13`               |
| Reading relative             | `Z0`–`Z3`                                          |

## 8. Error-handling requirements

1. After any configuration sequence, append `X`, then query error state (`U1`) when doing synchronous configuration.
2. Treat invalid command, format, and option errors as programming/protocol errors; do not retry them.
3. Treat `NOT IN REMOTE` as a connection-state failure; ensure remote addressing, then fail clearly if it persists.
4. Treat `TRIGGER NOT READY` / trigger overrun as an acquisition-state failure. Retry only under a caller-controlled
   retry policy.
5. Treat overflow as a measurement-range failure. Return neither the prior reading nor a fabricated finite value.
6. Treat RAM/NVRAM, A/D, front-panel, and calibration errors as instrument-health failures requiring explicit operator
   attention.
7. Preserve the original instrument status/error response in exception context/logging.

The manual specifies that once the meter detects an invalid device-dependent command it ignores subsequent commands in
the same command string, including the next `X`. On error, discard the pending configuration sequence; issue a fresh,
validated sequence rather than trying to continue it.

## 9. Testing strategy

Use a mock transport that records writes and supplies deterministic talk responses. Cover at least:

- connection makes the unit remote and verifies communication using `U0`;
- normal single read emits a valid `F0G0T1X`-style setup then performs a talk/read transaction;
- `G0` numeric output and `G1` prefixed output parse correctly;
- `RDCV`, `NMAX`, `NMIN`, optional location, and timestamp parsing work for extension paths;
- all generic-range conversions select the correct `R` command;
- out-of-range, non-finite, and unsupported configuration values fail before any write;
- command batching has exactly one final `X` and no newline-dependent SCPI assumptions;
- `U1` bit decoding raises the project’s appropriate exception hierarchy;
- trigger-not-ready and overflow behave distinctly;
- buffer configuration validates lengths from 1 through 1024; and
- source mode, calibration, setup persistence, and bus-clear/reset require explicit advanced calls.

For hardware tests, begin with a quiet known voltage source, fixed range, line-cycle integration, filters enabled, and
one-shot-on-talk triggering. Avoid automatic device clear during connection because it returns the meter to power-up
defaults.

## 10. Non-generic capabilities requiring explicit treatment

These Model 182 features are **not naturally mapped** to a normal nanovoltmeter driver and must be explicitly exposed,
left unsupported with a documented reason, or placed in an advanced extension:

1. 1024-reading linear/circular buffer, full-buffer streaming, buffer position/time, min/max/mean/standard deviation;
2. asynchronous/multiple triggering, external trigger input, manual trigger, GET trigger, trigger interval, and delay;
3. IEEE-488 serial poll, SRQ masks, EOI control, and bus hold-off;
4. reading-relative baseline and independent analogue-output-relative baseline;
5. rear analogue output gain and programmable analogue voltage **source mode**;
6. persistent save/recall of setup, factory reset, and display-message EEPROM storage;
7. calibration constants, calibration lock status, and calibration execution; and
8. low-level IEEE-488 remote/local/LLO/DCL/SDC/IFC bus-management actions.

The generic driver should provide safe voltage measurement first. Advanced functionality must not be activated as a
side-effect of obtaining a reading.

## 11. Recommended implementation order

1. Implement transport remote/talk/read integration and the command builder.
2. Implement configuration commands for range, digits, integration, filters, output format, and `T1`.
3. Implement numeric reading parsing and `U1` error decoding.
4. Implement generic API properties/methods and mock-transport tests.
5. Add status read-back (`U0` and selected `U` values).
6. Add optional buffered acquisition and advanced triggering.
7. Add SRQ/serial-poll support only when transport integration is proven.
8. Add source mode, setup persistence, and calibration only behind explicit advanced/privileged APIs.

This order produces a safe, useful nanovoltmeter driver while retaining a path to the Model 182’s distinctive legacy
IEEE-488 capabilities.
