# MDX 500 control through the custom Serial I/O box

## Purpose and scope

This document reverse engineers the control path implemented by
[`mod_SIO.bas`](sources/mod_SIO.bas) and relates it to the Advanced Energy MDX
500 User port described in
[`mdx.500.magnetrondrive.pdf`](sources/mdx.500.magnetrondrive.pdf). It is
structured as an implementation specification for an LLM or developer creating
a Python driver.

The key architectural fact is that the Visual Basic code does **not** speak a
native MDX 500 serial command protocol. The PC sends one-byte commands to a
custom USB Serial I/O (SIO) box. The box converts those commands into analog
setpoints and digital contact closures for as many as eight MDX supplies. The
MDX itself is controlled through its optional rear-panel 25-pin analog/digital
User port.

This document distinguishes:

- **Observed** behaviour: directly present in the Visual Basic module or MDX
  manual.
- **Strong inference**: implied by both sources, but dependent on custom-box
  wiring or firmware that is not available.
- **Unknown** behaviour: cannot be recovered from the supplied sources and
  must be measured or obtained from other source/firmware files.

## Source references

- Visual Basic module: `notes/sources/mod_SIO.bas`, especially lines 86-188
  and 439-696.
- MDX manual, printed pages 1-13 to 1-14: functions and electrical ratings
  (PDF pages 39-40).
- MDX manual, printed pages 2-8 to 2-9: User-port pinout
  (PDF pages 64-65).
- MDX manual, printed pages 2-11 and 2-17 to 2-19: status and interface
  overview (PDF pages 67 and 73-75).
- MDX manual, printed pages 3-13 to 3-20: signal definitions and wiring
  (PDF pages 92-99).
- MDX manual, printed pages 4-3 to 4-7: regulation, setpoint, and remote
  operation (PDF pages 124-128).

## System architecture

```text
Application source number (1..10)
        |
        | gSourceMdxNumber[source]
        v
Physical MDX number (1..8)
        |
        +---- shared 12-bit setpoint value -----------------------+
        |                                                         |
        | lower/middle/upper nibble commands                      |
        v                                                         v
PC -- USB byte writes --> custom SIO box --> DAC bank/channel --> MDX pin 23
                              |                    analog level    LEVEL IN.A
                              |
                              +--> 4-bit on/off bank 1 --> MDX 1..4 remote inputs
                              +--> 4-bit on/off bank 2 --> MDX 5..8 remote inputs
                              +--> status acquisition (format unknown)
```

The USB call used for every live command is:

```vb
WriteUSBDeviceBufferSIO(gIVORUSBSIODeviceNo, DataByte, 1)
```

The third argument is always `1`, so every operation shown is a one-byte write.
There is no framing, terminator, checksum, acknowledgement, retry, or USB read
in the supplied module.

The older `dlportio.dll` parallel-port implementation is vestigial. Calls that
used I/O addresses 784-789 are commented out, and `WriteDataToPort(address,
DataByte)` ignores `address` and forwards only `DataByte` to the USB device.
Consequently, the apparent port address must not be included in a new Python
wire protocol.

## MDX 500 rear User-port signals relevant to this controller

The MDX User port is a female DB-25 connector. A bar over a manual signal name
means active low. The table uses `*_N` below to make that polarity explicit.

| Pin | Suggested Python name | Direction | Meaning | Relevance to VB system |
|---:|---|---|---|---|
| 1 | `current_monitor` | Analog out | 0-full-scale voltage represents 0-1 A | Not explicitly consumed in supplied module |
| 2 | `power_monitor` | Analog out | 0-full-scale voltage represents 0-500 W | Not explicitly consumed |
| 3 | `voltage_monitor` | Analog out | 0-full-scale voltage represents 0-1200 V | Not explicitly consumed |
| 4 | `water_interlock_n` | Digital in | Must be pulled low to satisfy water interlock | Custom wiring unknown |
| 5 | `vacuum_interlock_n` | Digital in | Must be pulled low to satisfy vacuum interlock | Custom wiring unknown |
| 6 | `main_interlock_n` | Digital/current-loop in | Enables the main contactor | Custom wiring unknown |
| 7 | `remote_off_n` | Digital in | Open/high forces output off; low permits output | Probably part of each on/off channel |
| 8 | `remote_on_n` | Digital in | Low turns output on when remote-on is enabled | Probably part of each on/off channel |
| 9, 20, 21, 25 | `ground` | - | Chassis/signal ground | Analog and digital reference |
| 10 | `reference` | Analog out | Accurate 5 V or 10 V reference, factory option | Could be the DAC reference; wiring unknown |
| 12 | `level_monitor` | Analog out | Programmed setpoint as 0-full-scale voltage | Not explicitly consumed |
| 13 | `setpoint_ok_n` | Digital out | Goes low when requested setpoint is attained | Likely source of `shp_SetPoint`, not proven |
| 14 | `aux_15v` | Power out | 15 V, up to 100 mA | Possible custom-board input supply; unknown |
| 16 | `power_regulation_n` | Digital in | Regulation-mode selection | No matching VB command |
| 17 | `current_regulation_n` | Digital in | Regulation-mode selection | No matching VB command |
| 22 | `output_on_n` | Digital out | Low while output is on; high while off | Could feed status, not shown |
| 23 | `level_setpoint` | Analog in | 0-full-scale voltage requests 0-maximum selected output | Almost certainly driven by custom DAC |

The factory option determines whether analog full scale is 5 V or 10 V. The
manual specifies the following full-scale monitor values: 1 A on pin 1, 500 W
on pin 2, and 1200 V on pin 3. Pin 23 represents the maximum value of the
selected regulation mode at full-scale voltage.

The MDX has three remotely selected regulation modes:

| Mode | Pin 17 `current_regulation_n` | Pin 16 `power_regulation_n` |
|---|---|---|
| Voltage | low | low |
| Power | high | low |
| Current | low | high |

The VB module contains no operation for pins 16 or 17. The installation must
therefore fix the regulation mode in hardware, or configure it outside this
module. The `Current` API naming and its 0-1000 scale strongly suggest current
regulation on a low-tap, 1 A MDX, but this must be verified at the machine.

Remote control also requires the MDX rear-panel switches to be configured:

- `LOCAL, ON` up transfers on-control to User-port pin 8. Off-control remains
  available from the User port regardless.
- `LOCAL, SETPT` up transfers regulation-mode and setpoint control to the User
  port.
- Interlocks must be satisfied before output can turn on.

## Custom SIO one-byte command map

The high nibble selects an operation. The low nibble carries a DAC nibble,
channel/control bits, or a four-channel bitmap.

| Byte range | Meaning in VB | Payload |
|---|---|---|
| `0x00..0x0F` | Load DAC data bits 3..0 | Low four bits of 12-bit code |
| `0x10..0x1F` | Load DAC data bits 7..4 | Middle four bits |
| `0x20..0x2F` | Load DAC data bits 11..8 | High four bits |
| `0x30..0x3F` | Select/latch DAC output bank for MDX 1..4 | Low bits contain channel and latch/chip-select state |
| `0x40..0x4F` | Select/latch DAC output bank for MDX 5..8 | Low bits contain channel and latch/chip-select state |
| `0x50..0x5F` | Set MDX 1..4 on/off state | Bit 0 = MDX 1 through bit 3 = MDX 4 |
| `0x60..0x6F` | Set MDX 5..8 on/off state | Bit 0 = MDX 5 through bit 3 = MDX 8 |
| `0x70` | Reset both DACs to zero | No payload |
| `0x80..0x8F` | Motor 1 control | Unrelated to MDX driver |
| `0x90..0x9F` | Motor 2 control | Unrelated to MDX driver |
| `0xB0` | Reset latches | No payload |
| `0xF0` | Request/read hardware status | Response transport and format absent |

`0x3F` and `0x4F` are described by the VB comments as disabling DAC output 1
and DAC output 2 respectively. These values overlap the DAC-bank command
ranges, and the board schematic/firmware is unavailable. Treat their exact
electrical action as unknown rather than generalising the comment into a DAC
protocol rule.

### Timing

- There is a 10 ms pause after every DAC data-nibble byte and every transition
  in a channel-latch sequence.
- There is a 100 ms pause after an MDX-bank on/off byte.
- Initialisation inserts 100 ms between reset/disable operations.
- The low-level USB byte write itself has no shown readiness wait or response
  check.

A compatible driver should preserve these delays initially. They may be made
configurable only after testing shows the board can accept shorter intervals.

## Setpoint conversion and routing

### Logical-to-physical mapping

Application `Source` values 1 through 10 are mapped through the external array
`gSourceMdxNumber`. The resulting physical MDX number must be 1 through 8:

- MDX 1..4 use DAC bank command `0x30` and on/off bank `0x50`.
- MDX 5..8 use DAC bank command `0x40` and on/off bank `0x60`.
- Within either bank, the channel index is zero-based (`0..3`).

The source mapping is configuration data, not part of the byte protocol. A
Python API should represent it explicitly, for example as
`Mapping[int, int]`, validate both sides, and keep source identifiers separate
from physical MDX identifiers.

### Value conversion

The VB conversion is conceptually:

```text
dac_code ~= Current * 4095 / 1000
```

It then sends the code least-significant nibble first:

```text
write(0x00 | ((dac_code >> 0) & 0x0F)); wait 10 ms
write(0x10 | ((dac_code >> 4) & 0x0F)); wait 10 ms
write(0x20 | ((dac_code >> 8) & 0x0F)); wait 10 ms
```

The variable is named `Current`, and 1000 corresponds to the manual's 1 A
low-tap maximum if the application unit is milliamps. That unit is a strong
inference, not an explicit declaration. The VB uses bitwise operations on a
`Single`, so VB6 numeric coercion determines how fractional codes are rounded.
A Python driver should choose and document an explicit policy, preferably
round-to-nearest after validating `0 <= current_ma <= 1000`.

The VB code does not validate or clamp the value before converting it into a
12-bit code. A new driver must reject negative, non-finite, and above-full-scale
values rather than reproducing overflow or wraparound behaviour.

### Latching the shared code into one output

After loading the three shared nibbles, the VB pulses control bits for the
selected bank and channel.

For MDX 1..4:

```text
channel = mdx_number - 1
write(0x3C | channel); wait 10 ms  # LDAC high, CS high
write(0x30 | channel); wait 10 ms  # LDAC low,  CS low
write(0x3C | channel); wait 10 ms  # LDAC high, CS high
```

For MDX 5..8:

```text
channel = mdx_number - 5
write(0x4C | channel); wait 10 ms
write(0x40 | channel); wait 10 ms
write(0x4C | channel); wait 10 ms
```

The shared nibble-loading registers mean a complete load-and-latch sequence
must be atomic with respect to other setpoint writes. A multithreaded or async
Python driver needs one lock covering all six bytes and waits. Locking only
individual USB writes could route a mixed 12-bit value to the wrong MDX.

### Special `Hammer` correction

For `gSystemName = "Hammer"` and logical source 1, the VB replaces `Current`
with `Int(Current * 0.5)` before conversion. The nearby comments inconsistently
refer to source 3, a supply that outputs twice the requested current, and a
2 kV-versus-1 kV configuration. Preserve this only as an explicit,
machine-specific calibration transform; do not embed it in a generic MDX 500
class.

## Output on/off control

The software maintains two four-element boolean shadow registers:

```text
mdx_1_to_4_mask = sum(enabled[i] << i for i in range(4))
mdx_5_to_8_mask = sum(enabled[i] << i for i in range(4))
```

It sends the entire bank whenever any member changes:

```text
write(0x50 | mdx_1_to_4_mask); wait 100 ms
write(0x60 | mdx_5_to_8_mask); wait 100 ms
```

An enabled software bit is therefore **not** a pulse. It is persistent desired
state, and the driver must preserve all other bits when changing one channel.
On process start, software state must not be assumed to match physical board
state.

The MDX manual supports either three-wire start/stop contacts or a two-wire
control in which pins 7 and 8 are tied together and a single contact to ground
means on. Because the custom board exposes one persistent bit per MDX, the most
likely wiring is one relay/open-collector per supply implementing the manual's
two-wire control. This wiring is not shown in the supplied sources. Do not rely
on the assumption until continuity or voltage measurements confirm which MDX
pins each channel switches.

### Single-supply ignition sequence

The VB `IgniteMagnetron(source, current)` operation is:

1. Apply the optional machine-specific calibration.
2. Resolve logical source to physical MDX.
3. Convert and latch the analog setpoint.
4. Set that MDX's bit in the appropriate shadow register.
5. Send the entire bank bitmap.
6. Optionally wait a configured ignition time and verify status.

The important safety ordering is **setpoint first, output enable second**.

### Single-supply shutdown sequence

`TurnOffMagnetron(source)` is:

1. Optionally perform the existing UI-specific status check.
2. Clear that MDX's bit in the appropriate shadow register.
3. Send the entire bank bitmap.
4. Set that MDX's analog setpoint to zero.
5. Wait 100 ms.

The important safety ordering is **output disable first, zero setpoint
second**. A Python driver should also attempt zeroing in a `finally`/best-effort
cleanup path, without allowing a failed zero command to hide a failed disable.

### Multi-supply operations

The VB multi-ignite routine sets every non-zero analog setpoint first, updates
the in-memory bitmaps, and then sends one command for each bank. Multi-off
clears all requested bits first and then writes each bank once. A Python API
should generalise this as a batch mapping rather than reproduce the hard-coded
six-argument Visual Basic signature.

## Initialisation

`InitialiseRemoteBoard()` performs:

```text
write(0x70); wait 100 ms  # reset both DACs to zero
write(0x3F); wait 100 ms  # VB comment: disable DAC 1 output
write(0x4F); wait 100 ms  # VB comment: disable DAC 2 output
```

The separate PC-interface initialiser calls UART/FIFO/loopback helpers, but all
their hardware writes are commented out. They are no-ops in the supplied USB
version.

`Reset_Latches()` sends `0xB0` through `WriteDataToPort` and then directly calls
the USB write with `0xB0` again. Since `WriteDataToPort` already forwards to USB,
the current function sends the byte twice. A new driver should not copy this
accidental duplication without hardware testing.

Initialisation does not explicitly clear the two software on/off arrays or send
`0x50`/`0x60` with zero masks. A safer Python initialisation policy would be:

1. Establish exclusive access to the device.
2. Send known-off masks `0x50` and `0x60` if hardware testing confirms these
   opcodes are safe immediately after connection.
3. Reset DACs to zero with `0x70`.
4. Apply any required `0x3F`/`0x4F` board-specific disable sequence.
5. Initialise software shadows to the confirmed physical state.

Do not change that sequence on production hardware until an electrical test is
performed with the MDX outputs safely isolated.

## Status and verification

The supplied module is incomplete for input/status handling:

- `ReadHardwareStatus()` sends `0xF0` but does not read or parse a response.
- `CheckStatusOfSIO()` exits immediately, before its old parallel-port read.
- `VerifySourceIsOn()` waits, triggers a form-level hardware-status update, and
  checks `frm_HardwareStatus.shp_SetPoint(MdxNumber).FillColor` for red.
- The implementation of `frm_HardwareStatus.cmd_Update_Click` and the USB read
  function are not supplied.

The manual's active-low pin 13 (`setpoint_ok_n`) is the most plausible signal
behind the UI's per-supply `shp_SetPoint` indicator. Pin 22 (`output_on_n`) is
also a plausible input to the SIO status logic. Neither mapping is proven.

Therefore a first Python driver should expose status as unsupported rather than
invent a response format. Add it only after finding the USB wrapper/firmware or
recording request/response traffic for `0xF0`.

## Recommended Python driver decomposition

Separate the implementation into two layers because the MDX and SIO protocols
are different abstractions:

```python
class SerialIOTransport:
    """Write exact one-byte commands to one custom SIO USB device."""

    def write_byte(self, value: int) -> None: ...
    def read_status(self) -> bytes: ...  # initially unsupported


class MDX500BankController:
    """Control up to eight MDX 500 units through one custom SIO box."""

    def initialise(self) -> None: ...
    def set_current_ma(self, mdx: int, current_ma: float) -> None: ...
    def enable(self, mdx: int) -> None: ...
    def disable(self, mdx: int, *, zero_setpoint: bool = True) -> None: ...
    def ignite(self, mdx: int, current_ma: float) -> None: ...
    def ignite_many(self, setpoints_ma: Mapping[int, float]) -> None: ...
    def disable_many(self, mdx_numbers: Iterable[int]) -> None: ...
```

Add a separate application adapter for logical-source mapping and
machine-specific calibration. Avoid naming the low-level USB class `MDX500`,
because its byte protocol belongs to the custom SIO box and also controls
motors.

Recommended internal state and safeguards:

- One re-entrant lock for the complete SIO command stream.
- Two private four-bit on/off shadow masks.
- Explicit connected/initialised state.
- Strict validation of byte, MDX number, source number, and setpoint.
- Configurable 5 V/10 V analog full scale and engineering full scale, recorded
  as installation metadata even if the SIO byte calculation remains normalised.
- An emergency `disable_all()` that writes both zero masks before attempting to
  zero individual setpoints.
- No automatic re-enable after reconnect or exception.
- Dependency-injected sleep and fake transport for deterministic tests.

## Protocol-oriented test vectors

Assuming round-to-nearest conversion and no special calibration:

| Request | DAC code | Expected byte sequence before waits |
|---|---:|---|
| MDX 1, 0 mA | `0x000` | `00 10 20 3C 30 3C` |
| MDX 1, 1000 mA | `0xFFF` | `0F 1F 2F 3C 30 3C` |
| MDX 4, 1000 mA | `0xFFF` | `0F 1F 2F 3F 33 3F` |
| MDX 5, 0 mA | `0x000` | `00 10 20 4C 40 4C` |
| MDX 8, 1000 mA | `0xFFF` | `0F 1F 2F 4F 43 4F` |

Bitmap examples:

| Desired enabled supplies | Expected command(s) |
|---|---|
| None in bank 1 | `50` |
| MDX 1 only | `51` |
| MDX 1 and 4 | `59` |
| All MDX 1..4 | `5F` |
| MDX 5 only | `61` |
| MDX 5 and 8 | `69` |
| All MDX 5..8 | `6F` |

Tests should also prove that concurrent setpoint calls cannot interleave, that
changing one enable bit preserves the other three, that disable precedes
zeroing, and that transport exceptions leave the software in a conservative
unknown/off state rather than claiming success.

## Unresolved questions before production use

1. What USB device/library implements `WriteUSBDeviceBufferSIO`, and what are
   its VID/PID, endpoint type, timeout, and write semantics?
2. Is the transport actually a virtual COM port, HID device, vendor bulk USB
   interface, or an API around another driver? The VB function name alone does
   not prove serial-port framing.
3. Does one USB write contain exactly one byte on the wire, or does the wrapper
   add a report/header?
4. What DAC and output-stage circuit are in the SIO box, and is its analog full
   scale 5 V or 10 V?
5. Does each on/off channel implement the MDX manual's two-wire connection of
   pins 7 and 8, or another circuit?
6. Which interlocks are wired through the SIO box, and which are hardwired at
   each MDX?
7. Are pins 16 and 17 hardwired for current regulation? Confirm their measured
   levels and rear-panel `LOCAL, SETPT` position.
8. Is `Current` truly milliamps, and are all units low-tap 0-1 A models? Resolve
   the contradictory `Hammer` comment before applying calibration.
9. What response follows `0xF0`, and how are MDX pin 13/pin 22 states mapped?
10. What do `0x3F`, `0x4F`, and double-sent `0xB0` do in the custom firmware?
11. Is there a safe way to query current bitmap/DAC state after reconnect, or
    must every connection begin with a forced-off reset?

## Safe bench-validation sequence

The MDX 500 can produce hazardous voltage and power. Validation should be done
by qualified personnel with the output isolated from the sputtering process and
with real interlocks retained.

1. Identify the USB device and capture writes from the existing VB application.
2. Confirm the single-byte sequences above without an MDX connected.
3. Measure SIO analog outputs while commanding 0%, 25%, 50%, 75%, and 100%; do
   not assume 5 V or 10 V full scale.
4. Continuity-test each digital channel to determine its DB-25 pin wiring and
   active polarity.
5. Connect one disabled MDX, verify rear-panel remote switches and hardwired
   regulation mode, and test setpoint monitoring before allowing output.
6. Test on/off at a zero setpoint, then at a deliberately low current.
7. Open each genuine interlock and confirm the MDX shuts down independently of
   Python or the SIO box.
8. Characterise `0xF0` status traffic and only then implement verification.

Do not use the manual's "cheater plug" wiring in a new controller: it defeats
the interlock chain and is explicitly warned against by the manufacturer.
