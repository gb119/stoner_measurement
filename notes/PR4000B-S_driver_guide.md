# PR4000B-S RS232 Driver Programming Guide for LLM Coding Agents

<!-- markdownlint-disable MD013 -->

This document is intended to be pasted into an LLM prompt as technical context for generating a driver for the MKS `PR4000B-S` single-channel controller. It is based on the `PR 4000B-S Single Channel Controller Instruction Manual`, edition `2013-02`, especially Chapter 7, `External Communication`.

The PR4000B-S is not just a passive pressure transducer. It is a controller/readout unit that can operate pressure transducers, mass flow meters, and mass flow controllers. A driver should therefore model both:

- measurement readback
- controller state such as setpoint, valve on/off, limits, scaling, units, and status bytes

Use conservative defaults. Generated code should avoid changing configuration unless the caller explicitly asks for it.

---

## 1. High-level integration goals

When writing a driver, prefer a layered design:

1. A low-level serial transport that knows the PR4000B-S framing rules.
2. A protocol layer that sends commands and parses replies.
3. A typed device API for safe operations such as:
   - `read_actual_value()`
   - `read_setpoint()`
   - `set_setpoint(value)`
   - `set_valve_enabled(enabled)`
   - `read_status()`
   - `read_range()`
   - `read_measurement_unit()`
4. Optional higher-level helpers for pressure-control or flow-control workflows.

Prefer the ASCII protocol path unless binary support is explicitly needed. The manual says it is advisable to keep strictly to the ASCII formats.

---

## 2. Serial settings and session assumptions

The manual states the RS232 interface uses:

- `7` data bits
- `1` stop bit
- parity is used

The interface is menu-configurable for baud rate and parity. The baud/parity menu shows a default of `9600 Bd` with parity displayed as `----`, and the command set allows parity values:

- `NONE`
- `EVEN`
- `ODD`

Recommended initial Python serial settings:

```python
import serial

ser = serial.Serial(
    port="COM1",
    baudrate=9600,
    bytesize=serial.SEVENBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=1.0,
    write_timeout=1.0,
)
```

Important implementation note:

- make baud rate and parity configurable at construction time
- do not hardcode `8N1`; that is likely wrong for this instrument
- if communication fails, one of the first recovery checks should be `7E1` and `7O1`

---

## 3. Message framing rules

The protocol is a simple command/answer sequence with no buffering.

Key points from the manual:

- requests and answers are transferred as blocks, not individual characters
- a carriage return (`CR`, `0x0D`) is the tail character
- if a command has no defined payload response, the instrument returns just `CR`
- maximum message length is `12` characters
- separators such as spaces and tabs are not allowed

For ASCII mode, think of each request as:

```text
<command><optional-argument><CR>
```

and each reply as:

```text
<reply-payload-or-empty><CR>
```

Driver rules:

- always append `\r` to commands
- read until `\r`
- strip the trailing `\r` before parsing
- treat an empty reply as valid for write-style commands

---

## 4. Two protocol styles: ASCII and special binary

The PR4000B-S supports:

- ASCII commands and replies
- a special binary encoding for some commands and data values

The manual also defines:

- a special `@cmd` byte with flag bits
- a special `@head` packing format used for binary transfer
- IEEE 754 floats for binary floating-point values

For a first driver, implement:

- full ASCII support
- status-byte reads
- optional binary support later, only if needed

Reasons to defer binary mode:

- ASCII is simpler and safer to debug
- many important operations are fully available in ASCII
- the binary format uses unusual packed bytes and is easier to get wrong

---

## 5. Core command families

The command table uses ASCII characters whose hexadecimal value is shown in the manual. In practice, for ASCII mode, send the printable character itself followed by the argument and `CR`.

Examples:

- command `0x40 (@)` means send `@`
- command `0x61 (a)` means send `a`
- command `0x26 (&)` means send `&`

There are three especially important groups:

1. General commands
2. Commands that set process parameters
3. Commands that read process parameters

---

## 6. Minimum useful command subset for a first driver

Implement these first.

### 6.1 Read commands

- `` ` `` / `0x60`: read setpoint, returns `FLOAT`
- `a` / `0x61`: read valve ON/OFF, returns `0` or `1`
- `b` / `0x62`: read range, returns `FLOAT`
- `c` / `0x63`: read measurement unit, returns `BYTE`
- `d` / `0x64`: read gain, returns `FLOAT`
- `e` / `0x65`: read offset, returns `FLOAT`
- `k` / `0x6B`: read maximum limit, returns `FLOAT`
- `l` / `0x6C`: read minimum limit, returns `FLOAT`
- `m` / `0x6D`: read limit mode
- `n` / `0x6E`: read limit memory
- `o` / `0x6F`: read timeout
- `p` / `0x70`: read signal processing mode
- `q` / `0x71`: read display mode

### 6.2 Write commands

- `@` / `0x40`: set setpoint with `FLOAT`
- `A` / `0x41`: set valve ON/OFF with `0` or `1`
- `B` / `0x42`: set range with `FLOAT`
- `C` / `0x43`: set measurement unit with unit index
- `D` / `0x44`: set gain with `FLOAT`
- `E` / `0x45`: set offset with `FLOAT`
- `K` / `0x4B`: set maximum limit with `FLOAT`
- `L` / `0x4C`: set minimum limit with `FLOAT`
- `M` / `0x4D`: set limit mode
- `N` / `0x4E`: set limit memory
- `O` / `0x4F`: set timeout
- `P` / `0x50`: set signal processing mode
- `Q` / `0x51`: set display mode
- `R` / `0x52`: set sensor type
- `S` / `0x53`: set interface parameters

### 6.3 Status and utility commands

- `&` / `0x26`: read status byte 1
- `'` / `0x27`: read status byte 2
- `(` / `0x28`: read status byte 3
- `)` / `0x29`: read status byte 4
- `#` / `0x23`: start signal processing
- `0` / `0x30`: autozero

### 6.4 Commands to treat as advanced or risky

Avoid exposing these as casual high-level methods unless clearly needed:

- `*` / `0x2A`: reset system to default values
- `+` / `0x2B`: reset linearization
- `.` / `0x2E`: reset totalizer
- `/` / `0x2F`: start leak test
- `1` / `0x31`: autofullscale
- `2` / `0x32`: autolinearization
- `"` / `0x22`: direct access to sensors, which stops signal processing

These are better kept behind explicit "expert mode" APIs.

---

## 7. ASCII argument and reply formats

The manual defines these ASCII formats:

- `BYTE`: `000`
- `WORD`: signed five-character decimal string
- `LONG`: floating/integer long form with eleven characters
- `FLOAT`: signed fixed-width float with six characters plus sign

The scan quality of the manual is imperfect in places, so generated code should not assume more precision than the instrument actually returns. Instead:

- parse replies defensively with `int()` or `float()` after trimming whitespace and `CR`
- preserve exact outgoing field widths only when the instrument proves to require them
- centralize formatting helpers so widths can be adjusted in one place

Recommended helper behavior:

```python
def fmt_byte(value: int) -> str:
    return f"{value:03d}"

def fmt_word(value: int) -> str:
    return f"{value:+05d}"

def fmt_float(value: float) -> str:
    return f"{value:+0.5f}"
```

Then validate against real hardware and adjust widths if required by observed behavior.

Because the manual also caps total message length at 12 characters, keep formatting compact and test on hardware before widening any field.

---

## 8. Reading measured value versus reading setpoint

A subtle but important point: the most obvious read command in the command table is `` ` `` (`0x60`), which reads the setpoint, not the measured value.

The measured value is available through the general update commands:

- `!` / `0x21`: update all values
- `$` / `0x24`: update sensor

For a practical first driver:

- use `$` to obtain the actual measured value when you need readback
- use `` ` `` to obtain the currently configured setpoint

Model these as separate API calls. Do not conflate "actual value" and "setpoint".

---

## 9. Status-byte handling

Status handling is essential. The instrument exposes four status bytes.

### 9.1 Status byte 1

Bits indicate:

- general error
- overflow
- setpoint ON and valve open
- parameter modified by user
- relay 1 active
- relay 2 active

The manual says bits `d2`, `d4`, and `d5` are reset when status 1 is read.

### 9.2 Status byte 2

Bits indicate analog-input range faults, including:

- measured input too high or too low
- measured input above `110%`
- measured input below `0`
- external setpoint input too high or too low

This byte is especially useful for diagnosing scaling or wiring problems.

### 9.3 Status byte 3

Bits indicate:

- command execution error
- data transfer error
- totalizer overflow

The manual says bits `d1` and `d2` are reset when status 3 is read.

### 9.4 Status byte 4

Bits reflect digital inputs such as:

- valve ON/OFF
- autozero
- reset integrator
- start leak test

Driver recommendations:

- after every write command, optionally poll status 1 and status 3
- raise a protocol exception if status 3 reports command execution or transfer error
- provide a method that returns a decoded dataclass, not just a raw integer

Example:

```python
from dataclasses import dataclass

@dataclass
class PR4000Status3:
    command_execution_error: bool
    data_transfer_error: bool
    totalizer_overflow: bool
```

---

## 10. Measurement unit mapping

The manual lists these unit indices:

```text
0  = ubar
1  = mbar
2  = bar
3  = mTorr
4  = Torr
5  = kTorr
6  = Pa
7  = kPa
8  = mH2O
9  = cH2O
10 = PSI
11 = N/qm
12 = SCCM/CC
13 = SLM/L
14 = SCM/CM
15 = SCFH/CF
17 = mA
18 = V
19 = %
20 = C
```

The table in the scanned manual skips some numbers, so the driver should:

- represent units by integer code plus friendly name
- not assume the codes are contiguous
- preserve unknown codes rather than failing

A good model is an `IntEnum` plus an `UNKNOWN` fallback path.

---

## 11. Recommended Python API shape

Suggested driver surface:

```python
class PR4000B:
    def open(self) -> None: ...
    def close(self) -> None: ...

    def read_actual_value(self) -> float: ...
    def read_setpoint(self) -> float: ...
    def set_setpoint(self, value: float) -> None: ...

    def is_valve_enabled(self) -> bool: ...
    def set_valve_enabled(self, enabled: bool) -> None: ...

    def read_range(self) -> float: ...
    def set_range(self, value: float) -> None: ...

    def read_measurement_unit(self) -> int: ...
    def set_measurement_unit(self, unit_code: int) -> None: ...

    def read_status1(self) -> int: ...
    def read_status2(self) -> int: ...
    def read_status3(self) -> int: ...
    def read_status4(self) -> int: ...

    def autozero(self) -> None: ...
    def start_signal_processing(self) -> None: ...
```

Then optionally add:

- `read_status_decoded()`
- `configure_serial(baud, parity)`
- `read_gain()` / `set_gain()`
- `read_offset()` / `set_offset()`
- `read_limits()` / `set_limits()`

---

## 12. Safety and behavior constraints for generated code

Generated code should follow these rules:

- do not call reset-to-default commands during initialization
- do not change baud/parity automatically after connection unless explicitly requested
- do not use direct sensor access (`"`) in normal operation
- do not auto-enable valve output on connect
- treat write operations as state-changing and log them clearly
- separate read-only inspection methods from mutating methods

For controller use, a safe sequence is:

1. Open serial connection.
2. Read status bytes.
3. Read current setpoint, range, and unit.
4. Only then perform writes requested by the caller.
5. Re-read status after writes.

---

## 13. Error handling strategy

Define at least three exception types:

```python
class PR4000Error(Exception):
    pass

class PR4000ProtocolError(PR4000Error):
    pass

class PR4000StatusError(PR4000Error):
    pass
```

Raise `PR4000ProtocolError` for:

- serial timeout
- malformed reply
- parse failure
- unexpected empty reply from a read command

Raise `PR4000StatusError` for:

- status byte 3 command execution error
- status byte 3 data transfer error
- status byte 2 analog range faults when the caller requests strict checking

---

## 14. Suggested low-level implementation pattern

Use a single private request method.

```python
def _query_ascii(self, command: str, arg: str = "") -> str:
    payload = f"{command}{arg}\r".encode("ascii")
    self._ser.reset_input_buffer()
    self._ser.write(payload)
    self._ser.flush()
    reply = self._ser.read_until(b"\r")
    if not reply.endswith(b"\r"):
        raise PR4000ProtocolError("Timed out waiting for CR-terminated reply")
    return reply[:-1].decode("ascii", errors="strict")
```

Then layer small typed helpers on top:

```python
def read_setpoint(self) -> float:
    return float(self._query_ascii("`"))

def set_valve_enabled(self, enabled: bool) -> None:
    self._query_ascii("A", "001" if enabled else "000")
```

Do not duplicate framing logic across methods.

---

## 15. Hardware validation checklist

Before trusting the driver, test on the real instrument:

1. Confirm the actual serial settings on the front panel menu.
2. Verify that ASCII commands work with `7N1`, `7E1`, or `7O1` as configured.
3. Read status bytes with no active faults and record baseline values.
4. Read setpoint and actual value repeatedly and confirm stable parsing.
5. Toggle valve ON/OFF and verify both behavior and status updates.
6. Change a small setpoint and verify the new value reads back correctly.
7. Check that status-byte read side effects are understood, since some bits clear on read.

If observed hardware behavior differs from the scanned manual, trust the hardware and document the deviation in code comments and tests.

---

## 16. Strong recommendations for an LLM agent writing the actual driver

- Start with ASCII only.
- Implement a transport abstraction so the protocol can be unit-tested without hardware.
- Add exhaustive docstrings naming the exact command character for each method.
- Store command mappings in one place.
- Decode status bytes into named flags.
- Keep "expert" commands separate from normal control commands.
- Write hardware-integration tests only behind an opt-in marker or environment variable.

Most importantly, do not assume this device behaves like SCPI. It does not. It uses a compact custom ASCII/binary command protocol with CR termination, unusual numeric field formats, and read-to-clear status behavior.

---

## 17. Source note

This guide was derived from the MKS `PR 4000B-S Single Channel Controller Instruction Manual`, edition `2013-02`, especially:

- Chapter 4 for menu and interface context
- Chapter 7 for RS232 parameters, framing, status bytes, and command definitions
- Appendix A for interface/specification notes
