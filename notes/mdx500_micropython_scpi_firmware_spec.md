# MDX 500 multi-channel MicroPython SCPI firmware specification

## Purpose

This document is an implementation brief for an LLM coding agent. Build
MicroPython firmware for a PCB-mounted Raspberry Pi Pico controlling up to eight
isolated Advanced Energy MDX 500 channel cards through the modular backplane in
[`mdx500_pico_interface_circuit.md`](mdx500_pico_interface_circuit.md).

The firmware must:

- set each MDX to constant-power, constant-voltage, or constant-current mode;
- program and retain independent setpoints for up to eight channels;
- acquire power, voltage, current, level, `OUTPUT_ON`, and `SETPOINT_OK`;
- supervise power and voltage at 10 Hz per running channel;
- ignite several armed channels from one latched hardware update with less than
  100 ms command skew;
- monitor igniting channels more quickly, nominally 100 Hz;
- detect failed ignition and sustained loss of regulation;
- shut down safely and report faults through SCPI;
- use the existing
  [`stonerlab/MicroPython_SCPI`](https://github.com/stonerlab/MicroPython_SCPI)
  parser and status/error framework rather than writing another parser.

The MDX performs its own internal regulation. The Pico is a setpoint generator
and supervisor, **not** a fast outer feedback controller.

## Source baseline and required preliminary work

This specification was prepared against `MicroPython_SCPI` main commit
`6d45b87bc95d7ee22f6261d7238267ac067119ac` (2023-11-05), package version
`0.2.0`. Pin or vendor that revision before implementation and record any later
revision deliberately adopted.

The package already supplies:

- `SCPI`, `Command`, and `BuildCommands`;
- short/long command forms and optional nodes;
- fixed parameter converters including `Float`, `Int`, and `Boolean`;
- asynchronous/background command dispatch;
- IEEE-488.2 commands such as `*IDN?`, `*CLS`, `*RST`, `*OPC?`, and `*WAI`;
- operation/questionable registers and `SYSTem:ERRor[:NEXT]?`.

Before writing the MDX application, resolve the P0 and P1 findings in
[`micropython_scpi_framework_improvements.md`](micropython_scpi_framework_improvements.md),
or vendor explicitly documented, regression-tested workarounds. In particular,
do not depend on automatic coroutine detection, numeric command suffixes,
`Int` bounds, `Enum`, background exception reporting, or the baseline error
queue without applying the fixes described there.

Keep framework fixes suitable for an upstream contribution and keep
MDX-specific code in separate modules. This application specification continues
to use an explicit 0-7 channel parameter, even if generic numeric-suffix support
is later added.

## Hardware model assumed by the firmware

### Controller/backplane

- Pico mounted directly on the controller PCB.
- Shared, buffered SPI SCLK and MOSI to eight slots.
- Two active-low 3-to-8 decoders select one slot's ADC or DAC.
- One 8-to-1 multiplexer selects the addressed slot's ADuM MISO output.
- Three cascaded 74HC595 registers hold 24 relay commands.
- Two cascaded 74HC165 registers capture 16 status inputs.
- A hardware watchdog/output-permit removes every `REMOTE_ON` relay drive if
  firmware stops servicing it.

### Per-channel card

- ADuM4151 isolated SPI interface.
- AD5754R DAC channel A supplies MDX pin 23.
- ADS8688 reads pins 1, 2, 3, and 12.
- Three G3VM-61G1 contacts control remote-on, power-regulation, and
  current-regulation active-low inputs.
- Two optocouplers read active-low `SETPOINT_OK` and `OUTPUT_ON`.
- Field electronics are powered from the corresponding MDX pin 14 and retain a
  ground domain separate from every other MDX.

### Fixed relay bitmap

```python
REMOTE_ON = 0
MODE_P = 1
MODE_I = 2

def relay_bit(channel, function):
    return 3 * channel + function
```

The status shift-register bitmap is:

```python
SETPOINT_OK = 0
OUTPUT_ON = 1

def status_bit(channel, function):
    return 2 * channel + function
```

The hardware schematic is authoritative if final PCB routing changes either
mapping. Put the actual mapping in one firmware constants module and test it.

## Required project structure

Use a shallow, MicroPython-friendly module layout. Avoid elaborate inheritance
and CPython-only dependencies.

```text
main.py
boot.py                         # only if genuinely needed
lib/instr/...                   # pinned/fixed MicroPython_SCPI
mdx500/
    __init__.py
    constants.py                # pins, bit maps, ADC/DAC commands and limits
    errors.py                   # device-specific SCPI errors and fault codes
    models.py                   # ChannelState, configuration and calibration
    backplane.py                # slot select, MISO mux and SPI arbitration
    ad5754r.py                  # minimal DAC driver
    ads8688.py                  # minimal ADC driver
    relay_latch.py              # 74HC595 complete-shadow updates
    status_latch.py             # 74HC165 atomic acquisition
    channel.py                  # one logical MDX channel
    controller.py               # eight-channel orchestration
    monitor.py                  # polling, filtering and fault supervision
    ignition.py                 # single/group state machine
    persistence.py              # explicit config/calibration load/save
    scpi_instrument.py          # SCPI subclass and commands
tests/
    fakes.py                    # fake pins, SPI, clock and converters
    test_*.py                   # CPython tests of all non-hardware logic
```

Do not place policy in the low-level chip drivers. They should exchange raw
register values and raise typed communication/configuration errors.

The final PCB GPIO allocation is intentionally not invented here. Put every
pin number, SPI instance, polarity, and timing constant in `constants.py`, then
replace the placeholders from the reviewed KiCad netlist before hardware tests.

The base `Instrument.run()` owns the event loop by calling `read_commands()`.
Override `MDXInstrument.read_commands()` to start the long-lived monitor and
watchdog coroutines, then `await super().read_commands()` inside `try/finally`.
The `finally` block requests safe shutdown and cancels application tasks. Do not
start a second `asyncio.run()` or a second event loop from a command handler.

## Core data model

Represent each channel with persistent configuration and live state. Use plain
classes/dicts compatible with MicroPython; dataclasses are not required.

```python
class ChannelState:
    index: int                   # 0..7
    present: bool
    mode: str                    # "power", "voltage", "current"
    requested_value: float
    requested_power_w: float
    enabled_command: bool
    state: str                   # OFF, PREPARED, ARMED, IGNITING, RUNNING, FAULT
    measured_power_w: float
    measured_voltage_v: float
    measured_current_a: float
    measured_level: float
    output_on: bool
    setpoint_ok: bool
    fault_code: str
    fault_detail: str
    trigger_ms: int
    ignition_ms: int
    last_poll_ms: int
```

Per-channel configuration must include:

- analog full scale: 5.0 V or 10.0 V;
- MDX power full scale: normally 500 W;
- voltage full scale: normally 1200 V;
- current full scale for the installed tap;
- power absolute and relative tolerances;
- plausible voltage window, initially installation-configurable rather than
  hard-coded around 200-250 V;
- ignition timeout, default 5.0 s;
- number of consecutive good ignition samples, default 5;
- running fault persistence, default 1.0 s;
- optional strike power and post-ignition run power;
- calibrated gain and offset for DAC setpoint, power monitor, voltage monitor,
  current monitor, and level monitor.

Never restore an enabled state from persistent storage after reboot.

## Low-level driver requirements

### Backplane arbitration

All ADC/DAC transactions use one `asyncio.Lock`. A complete transaction is:

1. Disable both chip-select decoders.
2. Set `SLOT_A[2:0]` and thereby select the same MISO mux input.
3. Wait the measured address/mux settling interval.
4. Enable exactly the ADC or DAC decoder.
5. Perform the complete SPI frame.
6. Disable the decoder in `finally`.

Never change the slot address while either decoder is enabled. A bus exception
must leave both decoders disabled.

### AD5754R driver

Implement only the required features:

- initialise internal reference and straight-binary unipolar operation;
- set channel-A range to +5 V or +10 V from configuration;
- clear all outputs to zero;
- power channel A up and B-D down;
- write/read back channel-A code where supported;
- enable thermal shutdown and appropriate overcurrent behaviour;
- reject codes outside `0..65535`.

For power mode before calibration:

```python
code = round(65535 * requested_power_w / power_full_scale_w)
```

Apply calibrated slope/offset in engineering units, clamp only after validating
the request, and never wrap an out-of-range value.

### ADS8688 driver

- use the internal 4.096 V reference;
- configure AIN0-AIN3 for unipolar 0-10.24 V;
- leave unused inputs disabled or ignored;
- provide single-channel reads and a compact scan of the used inputs;
- detect impossible/repeated/stuck responses where practical;
- return raw codes to the channel/calibration layer.

Nominal conversions are:

```python
input_v = raw_code * 10.24 / 65535
power_w = input_v * 500.0 / analog_full_scale_v
voltage_v = input_v * 1200.0 / analog_full_scale_v
current_a = input_v * current_full_scale_a / analog_full_scale_v
```

Apply per-channel monitor calibration after nominal conversion. Power and
voltage are the primary continuously polled values. Current and level may be
polled at a lower background rate or on demand after initial commissioning.

### Relay latch

Maintain one authoritative 24-bit shadow value. The public API must support:

```python
set_mode(channel, mode)          # updates MODE_P/MODE_I, requires REMOTE_ON off
set_remote(channel, enabled)
set_remote_group(mask, enabled)  # one shadow update and one latch edge
disable_all()                    # highest-priority operation
```

On construction and reset:

1. Keep 74HC595 output enable inactive.
2. Shift a zero/off image.
3. Latch it.
4. Enable outputs only after hardware and watchdog checks pass.

The actual relay polarity belongs in `constants.py`; tests must prove that the
power-up bitmap opens every contact.

### Status latch

Pulse the 74HC165 parallel-load input, shift all 16 bits, invert active-low
signals once in this layer, and timestamp the coherent snapshot. Debounce in
the monitor layer, not in interrupt handlers.

## State machines

### Single-channel operation

```text
OFF -> PREPARED -> IGNITING -> RUNNING
                    |             |
                    +-----------> FAULT
RUNNING -> STOPPING -> OFF
```

Preparation while output is off:

1. Check channel presence and absence of a latched fault.
2. Open `REMOTE_ON`.
3. Select regulation-mode contacts.
4. Write zero, then the requested DAC setpoint.
5. Read level/status where available.
6. Enter `PREPARED`.

Triggering closes `REMOTE_ON`, records `time.ticks_ms()`, and enters
`IGNITING`. Use `time.ticks_diff()` for every deadline so timer wrap is safe.

Ignition succeeds only after the configured number of consecutive samples for
which:

```python
allowed_error_w = max(abs_tolerance_w, requested_power_w * relative_tolerance)
power_ok = abs(measured_power_w - requested_power_w) <= allowed_error_w
status_ok = output_on and setpoint_ok
voltage_ok = voltage_min_v <= measured_voltage_v <= voltage_max_v
```

Permit installation configuration to make `setpoint_ok` or the voltage window
diagnostic-only during commissioning, but never ignore `OUTPUT_ON`.

If no good stable window occurs before the nominal 5 s deadline, open
`REMOTE_ON` first, clear the DAC second, latch `IGNITION_TIMEOUT`, and report
the final power/voltage/status values.

### Running supervision

At 10 Hz per running channel:

- read power and voltage;
- refresh digital status;
- update filtered/display values without hiding raw values;
- require a persistent failure, nominally 1 s, before tripping for an ordinary
  regulation excursion;
- trip immediately for loss of controller health, explicit abort, impossible
  ADC communication, or configured hard over-power/over-voltage limits.

Use a short median or bounded moving average for displayed/tolerance power. Do
not use a long filter that delays protection. Do not continually adjust the DAC
to force the monitor reading to the target.

### Atomic group ignition

The group is represented by an 8-bit mask. Group states are:

```text
IDLE -> PREPARING -> ARMED -> TRIGGERED -> IGNITING -> RUNNING
                                              |          |
                                              +--------> GROUP_FAULT
```

`arm(mask)` prepares every member but leaves all remote contacts open. It must
be all-or-nothing: if one preparation fails, disable every member and do not
enter `ARMED`.

`trigger()` must be short and deterministic:

1. Verify the group remains armed and hardware output permit is healthy.
2. Construct the complete relay bitmap with every group `REMOTE_ON` bit set.
3. Shift it without altering outputs.
4. Record one group trigger timestamp.
5. Pulse the common latch once.
6. Start the group ignition supervisor and return.

During group ignition, poll power/voltage at about 100 Hz per selected channel
where feasible. Record each channel's first stable timestamp. After all members
are stable, return to 10 Hz per channel.

Default group failure policy is composition-safe and atomic: if any member
fails to ignite or faults before the group becomes stable, open `REMOTE_ON` for
every group member in one latch update, then zero their DACs. Preserve each
member's measurements and identify the originating channel/fault.

Do not claim that the plasmas ignite simultaneously merely because the relay
commands are simultaneous. If shutters are controlled elsewhere, expose a
callback/event when the group becomes stable so deposition timing can start
from a common shutter-open action.

## Poll scheduling and responsiveness

Use one long-lived monitor coroutine and one hardware-bus lock. Do not create a
new perpetual task per command.

Suggested schedule:

- `IGNITING`: power and voltage at 100 Hz for members of the active group;
- `RUNNING`: power and voltage plus digital status at 10 Hz per channel;
- current and level: 1 Hz by default, plus explicit query refresh if requested;
- `OFF`: presence/health poll at 1 Hz or slower;
- watchdog service: independent high-priority coroutine, serviced only when
  monitor and command tasks have demonstrated health.

Even eight channels at 10 Hz are a light SPI load. Keep each lock hold to one
short hardware transaction and yield between channels. Emergency/group-disable
must take priority over ordinary polls; implement an abort flag checked before
starting each new poll and immediately after acquiring the bus lock.

## SCPI command surface

The reviewed parser supports fixed parameter counts, so channel is an explicit
first parameter and groups use an 8-bit mask. Commands print one response line
only for queries.

### Channel configuration and output

| Command | Parameters / response | Behaviour |
|---|---|---|
| `SOURce:FUNCtion` | `<channel>,POWer|VOLTage|CURRent` | Set mode only while output is off. Use a custom validated mode converter. |
| `SOURce:FUNCtion?` | `<channel>` -> mode | Query configured mode. |
| `SOURce:POWer` | `<channel>,<watts>` | Validate 0..configured power full scale and program desired value; do not enable. |
| `SOURce:POWer?` | `<channel>` -> watts | Query requested power. |
| `SOURce:VOLTage` | `<channel>,<volts>` | Optional voltage-mode setpoint. |
| `SOURce:CURRent` | `<channel>,<amps>` | Optional current-mode setpoint. |
| `OUTPut` | `<channel>,ON|OFF` | ON starts supervised single-channel ignition; OFF disables first and zeros second. |
| `OUTPut?` | `<channel>` -> `0|1` | Query commanded enable, not measured status. |
| `ABORt` | `<channel>` | Immediate channel shutdown and operation cancellation. |

Decorators should resemble:

```python
@Command(
    command="SOURce:POWer",
    parameters=(Channel(), PowerWatts()),
)
def source_power(self, channel, watts):
    self.controller.set_requested_power(channel, watts)
```

Long-running ON/arm operations require explicit `async_call` metadata. Keep
simple queries synchronous and very short.

### Measurements and state

| Command | Response |
|---|---|
| `MEASure:POWer? <channel>` | calibrated watts |
| `MEASure:VOLTage? <channel>` | calibrated volts |
| `MEASure:CURRent? <channel>` | calibrated amperes |
| `MEASure:LEVel? <channel>` | calibrated selected-mode level |
| `MEASure:ALL? <channel>` | `power_w,voltage_v,current_a,level,age_ms` |
| `STATus:CHANnel? <channel>` | `state,output_on,setpoint_ok,fault_code` |
| `SYSTem:CHANnel:PRESent? <channel>` | `0|1` |

Queries return the latest coherent monitor snapshot. Add an explicit
`MEASure:FRESh?` only if a blocking fresh conversion is genuinely required;
ordinary queries must not disturb the 10/100 Hz scheduler.

### Ignition configuration

| Command | Purpose |
|---|---|
| `SOURce:IGNition:TIMEout <channel>,<seconds>` | default 5.0 s |
| `SOURce:IGNition:TOLerance:ABSolute <channel>,<watts>` | low-power absolute tolerance |
| `SOURce:IGNition:TOLerance:RELative <channel>,<fraction>` | relative tolerance, e.g. 0.10 |
| `SOURce:IGNition:GOOD <channel>,<samples>` | consecutive samples required |
| `SOURce:VOLTage:LIMit:LOWer <channel>,<volts>` | plausible lower voltage |
| `SOURce:VOLTage:LIMit:UPPer <channel>,<volts>` | plausible/hard upper voltage |

Implement matching queries for every persisted setting.

### Group operation

| Command | Behaviour |
|---|---|
| `GROUp:MASK <0..255>` | Select group members while group is idle. |
| `GROUp:MASK?` | Return current mask. |
| `GROUp:ARM` | Prepare every group member; complete only when all are armed or the operation fails. |
| `GROUp:TRIGger` | Apply one relay-latch edge and start background ignition supervision. |
| `GROUp:ABORt` | Disable all group members atomically. |
| `GROUp:STATe?` | `IDLE|PREPARING|ARMED|IGNITING|RUNNING|FAULT`. |
| `GROUp:RESult?` | Return mask, stable mask, fault mask, and trigger timestamp. |

The setpoints are configured per channel before `GROUp:ARM`; the group command
must not accept a variable-length list because the current parser requires a
fixed parameter tuple.

### Fault and reset commands

| Command | Behaviour |
|---|---|
| `SYSTem:FAULt? <channel>` | Return code, detail, timestamp, final power and voltage. |
| `SYSTem:FAULt:CLEar <channel>` | Clear only while output is off and hardware status is safe. |
| `SYSTem:FAULt:CLEar:ALL` | Clear all eligible channel faults. |
| `*RST` | Override base method: atomically disable all, zero DACs best-effort, cancel application operations, reset state/config to safe defaults, retain calibration. |
| `*TST?` | Return nonzero if any required hardware self-test fails. Fix the base command spelling if necessary. |

## SCPI status and error integration

Use the base status registers consistently. Proposed `STATus:OPERation`
condition bits:

| Bit | Meaning |
|---:|---|
| 0 | any channel preparing/armed |
| 1 | any channel igniting |
| 2 | any channel running |
| 3 | group operation active |
| 4 | calibration/configuration operation active |

Proposed `STATus:QUEStionable` condition bits:

| Bits | Meaning |
|---:|---|
| 0-7 | corresponding channel has a latched fault |
| 8 | SPI/ADC/DAC communication fault |
| 9 | watchdog/output-permit unavailable |
| 10 | configuration or calibration invalid |
| 11 | required channel card absent |

Create device-specific `SCPIError` subclasses using the -300 range, for
example:

- `-310,"Channel ignition timeout"`
- `-311,"Power outside tolerance"`
- `-312,"Voltage outside configured range"`
- `-313,"MDX output dropped"`
- `-320,"Channel card communication failure"`
- `-321,"Output permit unavailable"`
- `-330,"Group arm failed"`
- `-331,"Group member fault"`

The error queue should contain concise errors; detailed per-channel diagnostic
data remains available through `SYST:FAULT?`.

## Boot, shutdown, and exception invariants

### Boot

1. Hardware pulls keep relay outputs disabled and output permit off.
2. Initialise logging/emergency exception buffer where supported.
3. Initialise decoder enables inactive and load the MISO address safely.
4. Initialise 74HC595 with all contacts open before enabling its outputs.
5. Read 74HC165 status and detect populated channels.
6. Initialise each present ADC and DAC; clear every DAC to zero.
7. Load and validate configuration/calibration, but never restore output-on.
8. Start monitor/watchdog tasks.
9. Assert output permit only after all global health checks pass.
10. Enter the SCPI command loop.

### Shutdown/fault invariant

For every channel or group shutdown:

1. Open `REMOTE_ON` first, preferably with one atomic group latch.
2. Confirm or best-effort observe output off.
3. Write DAC zero second.
4. Preserve the original fault if zeroing also fails.

Any uncaught exception in a hardware, monitor, ignition, or SCPI command task
must request a safe shutdown. A `finally` path should remove software output
permit; the independent watchdog provides the final default-off layer.

## Persistence and calibration

Store configuration in a versioned JSON or compact text document. Write only
on explicit `SYSTem:CONFigure:SAVE`; do not write flash during 10 Hz polling.
Use a temporary file plus rename where the MicroPython filesystem supports it.

Calibration for each signal is at least:

```python
engineering_value = nominal_value * gain + offset
```

Characterise power-focused installations at 0, 5, 10, 25, 50, 75, and 100 W,
recording requested setpoint, level monitor, power, voltage, and an independent
reference if available. The DAC has ample code resolution at 10-25 W; low-end
accuracy will be dominated by analogue/MDX gain and offset.

## Testing requirements

Develop most logic under CPython using fake hardware and a fake wrap-safe clock.
No test should require an energised MDX.

### Parser/framework tests

- long/short and optional SCPI forms;
- channel/mode/boolean/range conversion;
- FIFO error ordering;
- task exception capture;
- `*RST`, `*CLS`, `*OPC?`, and `*WAI` with application tasks;
- no unsolicited background output.

### Driver/backplane tests

- both decoders inactive during every address change;
- exactly one ADC or DAC select active per transaction;
- MISO mux address matches selected slot;
- decoder disabled in `finally` after SPI exception;
- relay bitmap mapping for all 24 bits;
- one latch pulse for a multi-channel trigger/abort;
- status bitmap mapping and active-low inversion;
- DAC/ADC command encodings against data-sheet vectors.

### State-machine tests

- successful ignition after five consecutive good samples;
- good-sample counter resets after one bad sample;
- five-second timeout using `ticks_diff` across timer wrap;
- failure ordering is remote-off before DAC-zero;
- transient running excursion does not trip before persistence time;
- sustained excursion trips;
- group trigger changes all requested remote bits with one latch;
- one failed member atomically disables the complete group;
- unrelated running channels are preserved when policy says they are outside
  the failed group;
- emergency disable pre-empts polling;
- reset/exception never re-enables a channel.

### Hardware-in-the-loop commissioning

1. Test the controller/backplane with no channel cards and logic analyser probes.
2. Fit one unpowered card and verify slot select, MISO isolation and relay maps.
3. Power the field side from a current-limited laboratory supply, without MDX.
4. Validate DAC and ADC transfer functions with calibrated instruments.
5. Populate several cards; verify no chip-select glitches or MISO contention.
6. Measure command-to-contact skew for an eight-channel group trigger and abort.
7. Force Pico reset/hang/USB loss and verify hardware output permit disappears.
8. Connect one MDX with its output/process isolated and genuine interlocks
   retained; test at zero and deliberately low power.
9. Characterise ignition and running tolerances before enabling automatic fault
   actions on an experiment.

## Definition of done

The firmware is complete only when:

- parser/framework fixes have regression tests;
- all hardware-independent tests pass under CPython;
- the Pico boots with every remote contact open and every DAC at zero;
- eight configured channel objects can be polled at 10 Hz without starving SCPI;
- an armed multi-channel group produces one relay-latch transition with measured
  skew below 100 ms;
- ignition success/failure and atomic group-abort behaviour are demonstrated
  with simulated traces and then safely on hardware;
- all faults appear in status registers, the FIFO error queue, and detailed
  channel queries;
- an uncaught task exception, watchdog timeout, Pico reset, or USB loss removes
  every remote-on command;
- the final pin map, SPI modes, register encodings, calibration format, and SCPI
  command reference are documented alongside the code.
