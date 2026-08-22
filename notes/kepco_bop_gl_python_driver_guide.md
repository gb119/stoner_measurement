# Kepco BOP-GL 1 kW — Python Driver Programming Guide

> **Applies to:** Kepco BOP-GL 1 kW, manual P/N 243-1293-p, firmware 3.05+.
> **Purpose:** implementation guide for a Python driver over GPIB or RS-232 using SCPI.

## 1. Instrument model and driver scope

The BOP-GL is a **four-quadrant bipolar** programmable power supply: it can source and sink voltage and
current. The driver must support signed voltage/current values and must not assume a unipolar supply.

Known 1 kW models:

| Model        | Rated voltage | Rated current |
|--------------|--------------=|---------------|
| BOP 10-100GL | ±10 V         | ±100 A        |
| BOP 20-50GL  | ±20 V         | ±50 A         |
| BOP 50-20GL  | ±50 V         | ±20 A         |

Do not hard-code a model range. Query `*IDN?`, parse the model/ratings where possible, and allow explicit
configured limits as a fallback.

### Recommended driver API

Implement these high-level operations:

- connect / close / identify
- set remote mode (required for RS-232)
- enable / disable output
- select voltage or current mode
- set voltage or current setpoint
- set positive/negative software limits
- set positive/negative complementary protection limits
- read programmed setpoints and measured voltage/current
- configure output-off load behavior
- configure trigger source and execute triggered setpoints
- program, execute, stop, and inspect LIST waveforms
- read status and drain errors
- save / recall setups
- persist selected configuration fields
- optional: serial configuration, GPIB address, calibration, analog control configuration

Keep **calibration**, password manipulation, factory reset/security commands, and persistent configuration changes in
 a privileged/explicit API namespace. Do not call them during normal initialization.

## 2. Transport and message rules

### GPIB

- IEEE-488.2 / SCPI, address range 0–30; factory address is commonly 6.
- A GPIB command automatically puts the instrument into digital remote control.
- Use a VISA backend such as `pyvisa`; configure `read_termination` and `write_termination` as `"\n"`.
- For flash-writing commands, append `;*OPC?` in the **same program message** and read its response before sending
  the next command.

### RS-232

- 8 data bits, no parity, 1 stop bit; no hardware flow-control protocol is used (RTS/CTS pins are present but unused).
- Manual sections disagree on the default baud state: use `9600` initially, then provide configurable baud rates
  `2400`, `4800`, `9600`, and `19200`.
- The instrument parses on CR or LF; send one newline (`\n`) consistently.
- Before commands which affect output, send `SYST:REM ON`, then confirm `SYST:REM?` returns `1`.
- Default serial flow control is XON/XOFF enabled. A robust serial implementation must process XON (`0x11`) and
  XOFF (`0x13`) if enabled.
- On receiving XOFF, stop sending. When XON arrives, the supply emits buffered data followed by `!`; `!` is an
  idle/buffer-cleared marker, not part of a SCPI response.
- If prompt mode is enabled, wait for `CR LF >` before the next command.
- If echo mode is enabled, verify echoed bytes; normally leave it disabled.
- Maximum received/transmitted message length is 253 characters. Chunk long LIST uploads well below that limit.

### SCPI syntax

- Commands are ASCII and case-insensitive.
- Short forms are preferred: `VOLT`, `CURR`, `OUTP`, `MEAS:VOLT?`.
- A query ends with `?`.
- Commands in one message are separated by `;`.
- A leading `:` resets parsing to the command-tree root after a semicolon.
- Use explicit root resets in driver-generated multi-command messages, e.g.:

```text
FUNC:MODE VOLT;:VOLT 5;:CURR:PROT 1;:OUTP ON
```

- Numeric responses use scientific notation. Parse with Python `float`.
- Numeric inputs accept approximately four digits before, and eight digits after, a decimal point. Avoid oversized
  numeric formatting.
- `MAX` and `MIN` are accepted by many setpoint/limit commands.

## 3. State model: mode, setpoint, and protection

The BOP has a selected **main mode** and a complementary protection channel.

| Selected main mode         | Main setpoint | Complementary protection |
| -------------------------- | ------------- | ------------------------ |
| Voltage (`FUNC:MODE VOLT`) | `VOLT`        | `CURR:PROT`              |
| Current (`FUNC:MODE CURR`) | `CURR`        | `VOLT:PROT`              |

The selected mode means the intended regulating mode; actual operation may cross over to the complementary limit due
 to the load.

### Main-channel software limits

These are hard software bounds on values the driver is allowed to request, in either analog or digital control.

```text
VOLT:LIM <symmetric_abs_limit>
VOLT:LIM:POS <positive_limit>
VOLT:LIM:NEG <absolute_negative_limit>
VOLT:LIM?              # returns positive,negative limits

CURR:LIM <symmetric_abs_limit>
CURR:LIM:POS <positive_limit>
CURR:LIM:NEG <absolute_negative_limit>
CURR:LIM?
```

Although `:NEG` takes a positive magnitude, the resulting allowable output is negative. Example: `VOLT:LIM:NEG 5`
permits down to `-5 V`.

### Protection values versus protection-limit bounds

There are two layers:

1. `VOLT:PROT` / `CURR:PROT`: the active complementary clamp values.
2. `VOLT:PROT:LIM` / `CURR:PROT:LIM`: bounds on what the active protection values may be set to.

Use the active protection values in normal operation. Only change the `...:PROT:LIM` bounds when intentionally
constraining the instrument’s permitted configuration.

```text
CURR:PROT <symmetric_abs_limit>
CURR:PROT:POS <positive_limit>
CURR:PROT:NEG <absolute_negative_limit>
CURR:PROT?
CURR:PROT:MODE {FIX|EXT|LESS}

VOLT:PROT <symmetric_abs_limit>
VOLT:PROT:POS <positive_limit>
VOLT:PROT:NEG <absolute_negative_limit>
VOLT:PROT?
VOLT:PROT:MODE {FIX|EXT|LESS}
```

`FIX` selects SCPI-programmed protection. `EXT` selects analog protection inputs. `LESS` uses the protection closest
to zero from the analog and SCPI sources.

### Safe normal programming sequence

For voltage regulation:

```text
FUNC:MODE VOLT
VOLT <desired_signed_voltage>
CURR:PROT <safe_symmetric_current_limit>
OUTP ON
```

For current regulation:

```text
FUNC:MODE CURR
CURR <desired_signed_current>
VOLT:PROT <safe_symmetric_voltage_limit>
OUTP ON
```

For lower transient risk, select the intended mode once, set its main setpoint to zero, set a safe nonzero
complementary limit, and subsequently alter only the active main setpoint. Do not program both active and
complementary values to zero.

## 4. Essential SCPI command reference

### Identity, reset, synchronization

| Capability                | Command/query   | Notes                                                               |
| ------------------------- | --------------- | ------------------------------------------------------------------- |
| Identify                  | `*IDN?`         | Returns manufacturer, model, ratings/serial, firmware.              |
| Clear status/errors       | `*CLS`          | Clears error queue and event registers.                             |
| Reset                     | `*RST`          | Reset may leave output on; behavior depends on setup and load type. |
| Wait for prior operations | `*WAI`          | Blocks execution of subsequent commands.                            |
| Operation complete        | `*OPC`; `*OPC?` | For flash writes, send `COMMAND;*OPC?` together and read the reply. |
| Self test                 | `*TST?`         | `0` means pass.                                                     |
| SCPI version              | `SYST:VERS?`    |                                                                     |

### Output and load behavior

| Capability                | Command/query                          | Values                                         |
| ------------------------- | -------------------------------------- | ---------------------------------------------- |
| Output enable             | `OUTP ON`                              |                                                |
| Output disable            | `OUTP OFF`                             | Behavior depends on `OUTP:MODE`.               |
| Output state              | `OUTP?`                                | `1` on, `0` off.                               |
| Load/off-state behavior   | `OUTP:MODE ACTIVE\|RESISTIVE\|BATTERY` | Choose to match load.                          |
| Read load behavior        | `OUTP:MODE?`                           |                                                |
| Trigger-port ON/OFF       | `OUTP:CONT {HIGH\|LOW\|STAN\|OFF}`     | Set `OFF` when software alone controls `OUTP`. |
| Read trigger-port control | `OUTP:CONT?`                           |                                                |

**Load type is safety-critical.**

- `ACTIVE` (default): appropriate for inductive loads and constant-current active loads; when output is disabled it
  drives voltage to zero while retaining an energy absorption path.
- `RESISTIVE`: appropriate for resistive loads.
- `BATTERY`: appropriate for batteries or constant-voltage active loads; disabled state is current mode at zero
  current to avoid battery discharge.

Output OFF does not necessarily make output terminals benign. The application must use the load type appropriate to
 the connected system and independently manage hazardous-energy loads.

### Setpoints and measurements

| Capability                    | Command/query                           |
| ----------------------------- | --------------------------------------- |
| Select voltage mode           | `FUNC:MODE VOLT`                        |
| Select current mode           | `FUNC:MODE CURR`                        |
| Select mode from analog input | `FUNC:MODE EXT`                         |
| Mode query                    | `FUNC:MODE?` (`0` voltage, `1` current) |
| Program voltage               | `VOLT <signed_volts>`                   |
| Program current               | `CURR <signed_amps>`                    |
| Programmed voltage/current    | `VOLT?`, `CURR?`                        |
| Actual voltage/current        | `MEAS:VOLT?`, `MEAS:CURR?`              |
| Measurement integration/rate  | `MEAS:MODE {50\|60\|125}`               |

`VOLT?` and `CURR?` read programmed values. `MEAS:VOLT?` and `MEAS:CURR?` read actual output values. The
measurement rate is nominally 5 ms; readback samples are filtered/integrated per `MEAS:MODE`.

## 5. Output control and safe sequencing

### Digital output control

If software controls output state, first disable trigger-port output override:

```text
OUTP:CONT OFF
OUTP OFF
```

`OUTP:CONT` options:

- `HIGH`: Trigger Port pin 2 high/open means ON; low/short means OFF.
- `LOW`: Trigger Port pin 2 low/short means ON; high/open means OFF.
- `STAN`: a low pulse disables output; a later `OUTP ON` is required to re-enable.
- `OFF`: disables Trigger Port pin 2 control. Required for purely SCPI-controlled `OUTP ON`/`OUTP OFF`.

### Output OFF behavior

`OUTP OFF` changes internal control state according to `OUTP:MODE`:

- **ACTIVE:** voltage mode, zero voltage, with maximum protection channels to absorb energy. Use for inductive
  and constant-current active loads.
- **RESISTIVE:** zero output with low complementary protection values. Use for resistive loads.
- **BATTERY:** current mode at zero current with maximum voltage protection. Use for batteries and
  constant-voltage active loads.

For a hazardous or energy-storing load, `OUTP OFF` is not an isolation or safety-disconnect mechanism. Implement
external switching/interlocks as required by the system safety design.

## 6. Main and protection limit API mapping

### Main-channel limits

These persistently constrain requested main-channel setpoints, including analog input:

```text
VOLT:LIM <abs>       # symmetric ± voltage limit
VOLT:LIM:POS <pos>   # + voltage maximum
VOLT:LIM:NEG <abs>   # − voltage magnitude
CURR:LIM <abs>       # symmetric ± current limit
CURR:LIM:POS <pos>   # + current maximum
CURR:LIM:NEG <abs>   # − current magnitude
```

The `:NEG` values are entered as positive magnitudes. Attempting to set a main setpoint beyond a configured software
limit causes an error and the command is ignored; analog requests are clamped.

### Active complementary protection

Set active clamps, normally after selecting the main mode:

```text
# Voltage mode: current is the complementary protection channel.
CURR:PROT <symmetric_abs_amps>
CURR:PROT:POS <positive_amps>
CURR:PROT:NEG <absolute_negative_amps>

# Current mode: voltage is the complementary protection channel.
VOLT:PROT <symmetric_abs_volts>
VOLT:PROT:POS <positive_volts>
VOLT:PROT:NEG <absolute_negative_volts>
```

### Protection-limit bounds

The `...:PROT:LIM...` commands do **not** normally set the active clamp; they restrict what `...:PROT...` may later
be set to:

```text
CURR:PROT:LIM <abs>
CURR:PROT:LIM:POS <positive_amps>
CURR:PROT:LIM:NEG <absolute_negative_amps>
VOLT:PROT:LIM <abs>
VOLT:PROT:LIM:POS <positive_volts>
VOLT:PROT:LIM:NEG <absolute_negative_volts>
```

Protection values cannot be set near zero because the supply has a model-dependent internal “minimum box” region.
The driver should read back values after configuration and report range errors clearly.

### Protection source selection

```text
CURR:PROT:MODE FIX|EXT|LESS
VOLT:PROT:MODE FIX|EXT|LESS
```

- `FIX`: SCPI values are used.
- `EXT`: analog protection-limit inputs are used.
- `LESS`: the magnitude closer to zero of the external and SCPI limit applies.

## 7. Triggered setpoints

Use `VOLT:TRIG`, `CURR:TRIG`, and `FUNC:MODE:TRIG` to preconfigure values applied on a trigger.

```text
TRIG:SOUR BUS
VOLT:TRIG 5
CURR:TRIG 1
INIT
*TRG
```

Trigger sources:

- `TRIG:SOUR BUS`: trigger with `*TRG` or GPIB GET after arming with `INIT` or `INIT:CONT ON`.
- `TRIG:SOUR EXT`: external Trigger Port input creates the trigger after arming.
- `TRIG:SOUR IMM`: a `VOLT:TRIG` or `CURR:TRIG` command applies immediately; `*RST` selects this source.

Use `ABOR` to cancel a single armed trigger. `INIT:CONT ON` continuously rearms the trigger system.

## 8. LIST waveform programming

The LIST subsystem supports temporary voltage **or** current waveforms. A list cannot mix voltage and current entries,
and LIST commands are rejected while the list is executing.

### Basic point list

```text
LIST:CLE
LIST:VOLT -5,0,5
LIST:DWEL 0.1
LIST:COUN 10
VOLT:MODE LIST
```

- `LIST:CLE`: clear existing volatile list.
- `LIST:VOLT` or `LIST:CURR`: append values. Do not mix types.
- `LIST:DWEL`: append dwell times in seconds. A single dwell applies globally; otherwise dwell count must match
  point count.
- `LIST:COUN 1..255`: repeat count; `0` repeats indefinitely.
- `VOLT:MODE LIST` or `CURR:MODE LIST`: execute.
- `VOLT:MODE FIX` / `CURR:MODE FIX`: stop immediately; output remains at the current point.
- `VOLT:MODE HALT` / `CURR:MODE HALT`: stop at the end of a cycle.

List dwell range is approximately 93 µs to 34 ms. The list capacity depends on dwell-time usage: up to 5900 points
with a global dwell, 3933 with up to 126 distinct dwells, and 2950 with more distinct dwells. Keep uploads well below
the 253-character transport limit.

### Generated waveform segments

```text
LIST:CLE
LIST:VOLT:APPL SINE,50,10,0
LIST:COUN 0
VOLT:MODE LIST
```

`LIST:VOLT:APPL` and `LIST:CURR:APPL` use:

```text
LIST:<VOLT|CURR>:APPL <type>,<frequency_or_period>,<amplitude>[,<offset>]
```

Supported types: `SQUARE`, `RAMP+`, `RAMP-`, `TRIANGLE`, `SINE`, and `LEVEL`.

- For `LEVEL`, the second parameter is duration in seconds and the third is the level amplitude; no offset.
- For other types, the second parameter is frequency, the third is peak-to-peak amplitude, and optional offset is the
  centre value.
- Sine/triangle start and stop angles are global settings: `LIST:<VOLT|CURR>:APPL:SWE <start>,<stop>`.
- Maximum 126 segments, subject to total point capacity.

### LIST synchronization, waits, and sampling

- `LIST:SET:WAIT <seconds>` sets timeout for LIST wait commands; zero means wait indefinitely.
- `LIST:WAIT:HIGH`, `LIST:WAIT:LOW`, and `LIST:WAIT:LEDG` set a list value then wait on the Trigger Port input.
- `LIST:SET:TRIG <seconds>,ON|OFF` configures an external trigger pulse using the external-protection output flag.
- `LIST:TRIG <value>` emits that configured external pulse at a list point.
- `LIST:SET:SAMP <seconds>`, `LIST:SAMP:VOLT`, and `LIST:SAMP:CURR` configure transient measurements;
  retrieve results with `MEAS:TRAN?`.

## 9. Analog I/O reference

Use only if the driver/application explicitly supports analog programming. Main digital and analog control should not be
assumed safely composable unless mode/reference selection has been explicitly configured.

|  Pin( s) |   Signal                        | Meaning                                                     |
|------==--|---------------------------------|-------------------------------------------------------------|
| 11 / 10  | `EXT_REF` / return              | ±10 V main reference maps to ±rated output; 20 kΩ input.    |
| 2 / 9    | mode control / ground           | low/short = current mode; high/open = voltage mode.         |
| 13 / 12  | + current limit / return        | +1 to +10 V maps to +10% to +100% rated current.            |
| 5 / 12   | − current limit / return        | +1 to +10 V maps to −10% to −100% rated current.            |
| 14 / 12  | + voltage limit / return        | +1 to +10 V maps to +10% to +100% rated voltage.            |
| 6 / 12   | − voltage limit / return        | +1 to +10 V maps to −10% to −100% rated voltage.            |
| 15 / 4   | analog voltage monitor / return | ±10 V = ±rated output voltage; max 5 mA.                    |
| 3 / 4    | analog current monitor / return | ±10 V = ±rated output current; max 5 mA.                    |

External protection-limit inputs update at up to 100 ms and have approximately 1 Hz recommended bandwidth for
varying inputs. They require a source able to sink up to 0.15 mA at the low end.

## 10. Trigger Port reference

|  Pin | Signal                 | Driver-relevant behavior                                       |
| ---: | ---------------------- | -------------------------------------------------------------- |
|    1 | logic ground           | reference                                                      |
|    2 | remote ON/OFF          | behavior configured by `OUTP:CONT`                             |
|    4 | external trigger input | active low; min 100 µs for triggering; also used by LIST waits |

The Trigger Port’s pin mapping should be treated as hardware configuration, not a normal Python-driver concern,
except when exposing external triggering and remote output enable APIs.

## 11. Status, errors, and synchronization

### Error queue

After configuration sequences, query errors until zero:

```text
SYST:ERR?
```

It returns `<code>,<message>` and dequeues one error. Continue until `0,"No error"`.

Useful related queries:

```text
SYST:ERR:CODE?
SYST:ERR:CODE:ALL?
*ESR?
*STB?
```

### Key driver errors

|        Code | Meaning               | Typical driver action                           |
| ----------: | --------------------- | ----------------------------------------------- |
|      `-100` | command error         | command construction bug; raise immediately     |
|      `-120` | numeric data error    | validate/format values                          |
|      `-203` | command protected     | calibration/security access not enabled         |
|      `-221` | settings conflict     | invalid LIST/state combination                  |
|      `-222` | data out of range     | reject requested voltage/current/parameter      |
|      `-223` | too much data         | reduce LIST points/segments                     |
|      `-226` | lists not same length | repair LIST dwell/value construction            |
|      `-240` | hardware error        | halt operation and surface fault                |
| `-311/-314` | memory error/lost     | do not trust saved settings                     |
|      `-340` | calibration failed    | calibration workflow fault                      |
|      `-350` | queue overflow        | error history incomplete; clear and fail safely |
|      `-363` | input buffer overrun  | reduce command length/rate                      |
| `-400/-420` | query errors          | ensure every query is read exactly once         |

### Status registers

Use these for more advanced monitoring:

```text
STAT:OPER:COND?    # real-time operating condition
STAT:OPER?         # latched operation events; read clears
STAT:QUES:COND?    # real-time questionable condition
STAT:QUES?         # latched questionable events; read clears
STAT:OPER:ENAB <mask>
STAT:QUES:ENAB <mask>
```

Important operation condition bits:

- bit 5 (`32`): waiting for trigger
- bit 8 (`256`): constant-voltage state
- bit 10 (`1024`): constant-current state
- bit 14 (`16384`): list running

Important questionable-condition bits:

- bit 3 (`8`): thermal error
- bit 6 (`64`): slave error
- bit 12 (`4096`): voltage-protection event
- bit 13 (`8192`): current-protection event
- bit 14 (`16384`): sinking / absorbing energy

### Synchronization rule

Flash-writing operations can take significant time. For these commands, send `;*OPC?` in the **same** SCPI message
and wait for the response before sending another command:

- `*SAV`
- `MEM:UPD ...`
- `CAL:COPY`
- `CAL:SAVE`
- `SYST:PASS:NEW`
- `SYST:SEC:IMM`

Example:

```text
MEM:UPD LIM;*OPC?
```

For serial operation, XON/XOFF must be enabled for reliable flash updates according to the manual.

## 12. Save, recall, and persistence

| Command        | Meaning                                                             |
| -------------- | ------------------------------------------------------------------- |
| `*SAV <1..99>` | Save runtime operating setup.                                       |
| `*RCL <1..99>` | Recall and immediately apply setup. Treat as potentially hazardous. |
| `MEM:UPD INT`  | Persist GPIB address and `SYST:SET` interface/reset configuration.  |
| `MEM:UPD SER`  | Persist serial baud/pace/echo configuration.                        |
| `MEM:UPD LIM`  | Persist software and maximum protection bounds.                     |
| `MEM:UPD OUTP` | Persist output state and mode.                                      |

`*RCL` can restore output ON, mode, setpoints, protection settings, and reference types. Do not call it with a
connected load unless the setup is known safe. Locations 1–15 may be selected as power-up configurations using
hardware switches.

## 13. Reset and privileged functions

`*RST` resets operational state. Its output effect depends on `SYST:SET` reset configuration and the selected load
type. Do not use reset as an emergency stop.

Keep the following behind explicit privileged methods requiring caller acknowledgement:

- all `CAL:...` calibration commands
- `SYST:PASS:...` password controls
- `SYST:SEC:IMM` factory-default/security action
- `MEM:UPD ...` persistence operations
- `SYST:COMM:GPIB:ADDR ...` and serial communication reconfiguration
- `SYST:SET ...` changes to reset/DCL behavior

## 14. Driver implementation requirements

1. **Serialize I/O.** One command/query transaction at a time per supply. Never interleave query reads.
2. **Always drain responses.** Every query must be read exactly once, including `*OPC?`.
3. **Use signed floats.** The supply is bipolar in both voltage and current.
4. **Discover identity.** Query `*IDN?` at connection and use configured limits or parsed model ratings.
5. **Validate locally.** Reject NaN/infinite values and values beyond configured software limits before sending.
6. **Distinguish programmed versus measured values.** Implement separate APIs for `VOLT?`/`CURR?` and
   `MEAS:VOLT?`/`MEAS:CURR?`.
7. **Keep output state explicit.** Do not turn output on implicitly during `connect()` or normal initialization.
8. **Require load type selection.** Make `ACTIVE`, `RESISTIVE`, or `BATTERY` a deliberate configuration decision.
9. **Avoid mode switching under load.** Configure the mode and complementary protection first; then modify only the
   active setpoint in normal operation.
10. **Read errors after stateful batches.** Raise a structured exception including queued SCPI errors.
11. **Use bounded command lengths.** Especially for LIST uploads and RS-232.
12. **Provide a safe shutdown API.** It should select behavior suitable for the configured load, command output off,
    and verify the requested state without claiming electrical isolation.

## 15. Suggested Python abstractions

```text
BopGl
├── connect(), close(), identify()
├── set_remote(enabled=True)
├── output_on(), output_off(), output_enabled()
├── set_load_mode(active|resistive|battery)
├── set_voltage(volts), set_current(amps)
├── set_mode(voltage|current)
├── set_voltage_limits(pos, neg), set_current_limits(pos, neg)
├── set_current_protection(pos, neg), set_voltage_protection(pos, neg)
├── measure_voltage(), measure_current()
├── get_programmed_voltage(), get_programmed_current()
├── configure_trigger(...), trigger()
├── list_clear(), list_upload(...), list_run(), list_stop(...)
├── get_status(), drain_errors()
├── save(slot), recall(slot), persist(...)
└── privileged.calibrate(...), privileged.factory_reset(...)
```

Implementation details:

- Serialize all SCPI traffic with a mutex: this instrument does not support safely interleaved request/response streams.
- Format finite floats with a bounded precision, for example `f"{value:.8g}"`, then enforce configured software
  limits in Python before transmission.
- Implement command batching only for non-query commands, or provide a transaction method that knows exactly how many
  query responses to read.
- For RS-232, make parser/flow-control handling part of the transport layer rather than the high-level driver.
- Provide an opt-in `safe_initialize()` that validates identity and configuration but does not alter output or load
  mode by default.
