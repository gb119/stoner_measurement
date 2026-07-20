# PSR1A and PSR4A RS232 Driver Programming Guide for LLM Coding Agents

<!-- markdownlint-disable MD013 -->

This document is intended to be pasted into an LLM prompt as technical context for generating a driver for the MKS `PSR1A` and `PSR4A` power supply / readout / setpoint controller family. It is based on `PSR1A/PSR4A Power Supply and Pressure/Flow Readout User Manual`, MKS part number `20068380-001`, revision `B`, especially Appendix A, `RS-232 Serial Communications`.

The PSR family is a controller/readout platform for analog MKS mass flow controllers, mass flow meters, and some pressure controllers such as the `640B`. The `PSR1A` is single-channel. The `PSR4A` is four-channel and adds multi-channel concepts such as port sub-addressing and blend workflows.

Generated code should treat these instruments as stateful process controllers, not simple sensors.

---

## 1. High-level model

A good driver should separate:

1. serial transport
2. PSR message framing and checksum handling
3. parameter read/write operations
4. typed channel APIs for flow or pressure control

The instrument model is port-oriented:

- each channel has an input side (`PV`, process value)
- each channel has an output side (`SP`, setpoint)
- commands target a port number, not just a channel number

For the `PSR4A`, the manual describes pairs of ports per channel:

- channel input port
- channel output port

For most practical driver work:

- input port `01` means channel 1 PV
- output port `02` means channel 1 SP

The same pattern likely extends for later channels on the `PSR4A`, but generated code should not hardcode unverified mappings for channels `2` to `4` unless confirmed on hardware or in additional protocol examples.

---

## 2. Serial settings

The manual explicitly defines the RS232 settings as:

- `9600` baud
- `8` data bits
- `no parity`
- `1` stop bit
- `no` flow control

Recommended Python configuration:

```python
import serial

ser = serial.Serial(
    port="COM1",
    baudrate=9600,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=1.0,
    write_timeout=1.0,
    xonxoff=False,
    rtscts=False,
    dsrdtr=False,
)
```

This is different from the PR4000B-S, which uses a different serial framing scheme and configurable parity with `7` data bits.

---

## 3. Electrical serial connector

The manual gives the rear-panel RS232 pinout on a 9-pin D connector:

- pin `2` = `RXD`
- pin `3` = `TXD`
- pin `5` = `GND`

Generated code does not need to model this directly, but hardware setup notes should preserve it.

---

## 4. Preconditions before serial control

The manual says the front-panel setting `SP Source` must be switched to `Serial` if the user wants setpoints to come from RS232. When `SP Source` is set to `Serial`, keypad setpoint edits are prohibited.

Driver implications:

- document clearly that serial setpoint control may require a front-panel configuration step
- do not assume serial writes will be honored if `SP Source` is still `Keypad`
- if the instrument rejects writes, include this as one of the first troubleshooting checks

---

## 5. Message framing overview

The manual describes a half-duplex master/slave protocol. The host initiates all communication.

Important framing points:

- messages are ASCII
- command words are single alphabetic characters and are case-insensitive
- spaces are not allowed inside the actual message
- commands are terminated by carriage return, `CR`
- many responses end with `CR` and `LF`
- some replies include an ASCII hexadecimal checksum

The manual also mentions:

- block pre-limiter
- packet pre-limiter
- information frame
- checksum
- packet delimiter
- block delimiter

For ordinary point-to-point use, the practical command syntax is simpler than that wording suggests.

---

## 6. Core host-send syntax

The manual gives these essential command forms.

### 6.1 Non-networked, sub-addressed command

```text
AZ.pp<argument><CR>
```

### 6.2 Networked, sub-addressed command

```text
AZaaaaa.pp<argument><CR>
```

Where:

- `AZ` is the message pre-limiter
- `aaaaa` is the unit network address
- `.pp` is the port sub-address
- `<argument>` is the command payload
- `<CR>` is carriage return

The manual says that for single-point computer-to-PSR communication, the unit address is not necessary.

That means for a normal local RS232 connection you should prefer the non-networked form.

---

## 7. General command families

The PSR protocol has two distinct styles of commands:

1. utility commands such as `M`, `H`, `S`, `A`, `N`, and `K`
2. parameter commands using `P<index>=<value>`

This is a parameter-store protocol, not a SCPI tree and not a single-character state machine like the PR4000B-S.

---

## 8. Utility commands

### 8.1 Synchronize

Terminates any command in progress and resets the command state machine.

```text
<ESC>AZ<CR>
```

Response:

- none

This is useful as a recovery operation after garbled traffic.

### 8.2 Menu

Requests a textual menu listing available commands and identity information.

Non-networked:

```text
AZM<CR>
```

Networked:

```text
AZaaaaaM<CR>
```

Use this for exploratory diagnostics, not as the core data API.

### 8.3 Identity

The manual states there is an identity command that returns manufacturer/model/address information, but the extracted text does not preserve the exact host-send example on the identity page. A generated driver should therefore:

- expose an `identity()` method
- implement it only after validating the exact identity command on hardware or from the full page image
- use the returned identity string to discover the factory network address if needed

Do not guess the exact identity command letter in production code without verification.

### 8.4 Serial pacing and packet acknowledgement

The manual defines:

- `H` to pause outgoing character sending
- `S` to resume sending
- `A` as positive acknowledge
- `N` as negative acknowledge / resend request

These matter mainly when transferring large packetized responses with protocol-level error control enabled.

For an initial driver, support them as optional low-level methods but do not require them for basic parameter read/write.

---

## 9. Measured-channel value command

The manual defines a measured-channel values command:

Non-networked:

```text
AZ.ppK<CR>
```

Networked:

```text
AZaaaaa.ppK<CR>
```

This command sends one channel input port's values.

The manual says the response is compatible with existing published protocol formats, but the extracted text does not include the full response example. Therefore:

- implement this as a raw query first
- capture and log real replies from hardware
- parse only after confirming the exact field layout

This command is the best candidate for reading actual measured PV data.

---

## 10. Parameter read/write model

The PSR uses indexed parameters on a target port.

The manual explicitly gives the write form:

Non-networked:

```text
AZ.ppPzz=<new value><CR>
```

Networked:

```text
AZaaaaa.ppPzz=<new value><CR>
```

And the write response pattern:

```text
AZ,aaaaa.pp,4,Pzz,<new value>,<checksum><CR><LF>
```

Important implications:

- writes are echoed back in a structured response
- the response includes unit address, port, response type, parameter index, value, and checksum
- a parser should not assume only a naked numeric reply

The manual also shows menu/display pages for reading parameter sets, but the exact single-parameter query form is not cleanly preserved in the extracted text. Since the note on serial access says parameters can be queried and set individually, a driver should plan for both:

- `set_parameter(port, index, value)`
- `get_parameter(port, index)`

But the exact read syntax should be validated on hardware before committing to it.

---

## 11. Known parameter indices from the manual

The manual gives enough examples to anchor a first implementation for channel-1 MFC operation.

### 11.1 Input/PV-side examples

- PV signal type: index `00`
- decimal format: index `03`
- units: index `04`
- PV full scale: index `09`
- time base: index `10`
- gas correction factor: index `27`

### 11.2 Output/SP-side examples

- SP signal type: index `00`
- SP rate: index `01`
- SP function: index `02`
- SP full scale: index `09`
- SP valve override (`SP VOR`): index `29`

These are the strongest concrete items to build around.

---

## 12. Encoded value mappings

### 12.1 PV signal type

The manual shows these PV signal type codes:

```text
0 = Off
7 = 0-20mA
8 = 4-20mA
9 = 0-10V
: = 2-10V
; = 0-5V
< = 1-5V
```

For MKS MFC operation the manual says `0-5V` is required, represented by `;`.

This is unusual: the input-side signal type uses printable ASCII codes, not plain decimal numbers only.

Driver implications:

- preserve signal type values as strings, not only integers
- do not coerce `;` or `<` into numeric types
- define a typed enum-like mapping for readability

### 12.2 SP signal type

The SP output side uses ordinary numeric codes:

```text
0 = Off
1 = 0-20mA
2 = 4-20mA
3 = 0-10V
4 = 2-10V
5 = 0-5V
6 = 1-5V
```

For MKS analog MFCs the manual says `5` (`0-5V`) is required.

### 12.3 SP function

The manual shows:

```text
1 = Rate
2 = Batch
3 = Blend
```

Use `Rate` for ordinary closed-loop control.

### 12.4 SP valve override

The manual shows:

```text
0 = Normal
1 = Closed
2 = Open
```

However, it explicitly says open/close valve override is not compatible with the electrical design of the supported MKS 15-pin analog MFCs, so only `Normal` should be used in normal drivers.

### 12.5 Units

The manual provides unit codes including:

```text
18 = scc
19 = sl
20 = bar
21 = mbar
22 = psi
23 = kPa
24 = Torr
25 = atm
26 = Volt
27 = mA
28 = oC
34 = %
```

The full table includes additional volume and density-style units. Preserve unknown or rarely used unit codes without failing.

### 12.6 Time base

The manual shows:

```text
0 = none
1 = sec
2 = min
3 = hrs
4 = day
```

For sccm-style flow, the common setup is:

- units `18` = `scc`
- time base `2` = `min`

---

## 13. Numeric encoding conventions

The manual repeatedly shows numeric values encoded as scaled decimal strings with no embedded spaces.

Examples:

- PV full scale `100 sccm` is sent as `100000`
- SP full scale `100 sccm` is shown as `10000` in one example, which is inconsistent with the PV full-scale example
- SP rate `1000 sccm` is sent as `100000`
- gas factor `1.4` is sent as `1400`

This suggests:

- values are fixed-point, not free-form floats
- the decimal position depends on the configured display decimal setting
- the manual contains at least one formatting inconsistency in examples

Generated code should therefore:

- centralize value scaling logic
- treat displayed engineering units separately from transport integer strings
- validate the scaling model on hardware before trusting all example magnitudes

Recommended internal approach:

```python
def encode_scaled(value: float, places: int) -> str:
    return str(int(round(value * (10 ** places))))

def decode_scaled(raw: str, places: int) -> float:
    return int(raw) / (10 ** places)
```

Then bind `places` to the active decimal configuration for that port.

---

## 14. Recommended first-use configuration for analog MFC control

For a standard MKS analog MFC on channel 1, the manual indicates this approximate setup:

### 14.1 PV/input side

- port `01`
- signal type `;` (`0-5V`)
- units `18` (`scc`) or other desired unit family
- time base `02` (`min`) for sccm/slm-style display
- decimal as needed for range
- full scale matching the MFC label

### 14.2 SP/output side

- port `02`
- signal type `5` (`0-5V`)
- full scale matching PV full scale
- function `1` (`Rate`)
- valve override `0` (`Normal`)
- rate = desired setpoint

For pressure control with a `640B`, the manual says:

- PV signal type `0-5V`
- SP signal type `0-5V`
- PV and SP full scale must match the controller label
- units often `Torr` or `kPa`
- SP function `Rate`
- SP VOR `Normal`

---

## 15. Checksums and response parsing

The manual states that packet validity uses a two-character ASCII hexadecimal checksum based on a negated sum over the information frame.

Practical guidance:

- implement checksum verification for structured responses
- allow checksum verification to be disabled during bring-up, if necessary
- log raw frames whenever checksum validation fails

Because the exact boundaries of the information frame are described textually rather than shown with many full examples, generated code should isolate this in one helper and make it easy to adjust.

---

## 16. Channel and port abstractions

Do not expose only raw port numbers to end users. Build a channel abstraction.

Suggested mapping model:

```python
@dataclass(frozen=True)
class PSRPortMap:
    pv_port: str
    sp_port: str
```

For the `PSR1A`:

- channel 1 PV = `01`
- channel 1 SP = `02`

For the `PSR4A`, implement channel mapping as configuration data rather than assumptions baked into logic.

---

## 17. Suggested Python API

```python
class PSRController:
    def open(self) -> None: ...
    def close(self) -> None: ...

    def synchronize(self) -> None: ...
    def menu(self) -> str: ...
    def identity(self) -> str: ...

    def read_measured_channel_values(self, channel: int = 1) -> str: ...

    def set_parameter(self, port: str, index: int, value: str) -> None: ...
    def get_parameter(self, port: str, index: int) -> str: ...

    def configure_mfc_channel(
        self,
        channel: int,
        full_scale: float,
        units_code: int = 18,
        time_base_code: int = 2,
        pv_signal_type: str = ";",
        sp_signal_type: int = 5,
    ) -> None: ...

    def set_setpoint(self, channel: int, value: float) -> None: ...
    def read_actual_value(self, channel: int) -> float: ...
    def read_setpoint(self, channel: int) -> float: ...
```

Important note:

- `read_actual_value()` is conceptually supported by the protocol, but the exact measured-value response parser should be treated as hardware-verified work, not pure manual transcription

---

## 18. Safety and behavior constraints

Generated code should:

- never assume `SP Source` is already `Serial`
- avoid writing signal type or full-scale parameters unless explicitly requested
- default SP function to read-only inspection, not mutation
- keep `SP VOR` at `Normal`
- not attempt unsupported valve open/close overrides on MKS analog MFCs
- treat batch and blend as advanced features
- not assume every firmware build supports every global-setting write

The manual also notes:

- alarms are not supported in PSR1A/PSR4A firmware
- the network address is factory preset and not customer programmable

---

## 19. Differences from PR4000B-S

The PSR family differs from the PR4000B-S in several critical ways:

- PSR uses `8N1`; PR4000B-S uses `7` data bits with parity configuration
- PSR messages start with `AZ`; PR4000B-S uses single-character commands with `CR`
- PSR is parameter-indexed by port and channel; PR4000B-S is command-indexed by single characters
- PSR responses can include comma-separated structured records and checksums; PR4000B-S replies are simpler and often just value plus `CR`
- PSR controls analog MFC/MFM and pressure-controller interfaces; PR4000B-S is its own direct controller/readout with different status semantics

Do not try to implement both using the same wire protocol code.

---

## 20. Hardware validation checklist

Before trusting a driver:

1. Confirm `SP Source` is set to `Serial`.
2. Confirm local serial settings are `9600 8N1`.
3. Send `AZM<CR>` and capture the raw response.
4. Verify the actual identity command on hardware.
5. Verify channel-to-port mapping for PSR4A channels `2` to `4`.
6. Confirm write echo responses and checksum calculation.
7. Confirm the scaling of `SP Rate`, `PV Fs`, and `SP Fs` against front-panel values.
8. Confirm how single-parameter reads are requested, since the write form is explicit in the manual but the extracted read examples are incomplete.

If hardware behavior differs from the examples, trust the hardware and document the difference.

---

## 21. Strong recommendations for an LLM agent implementing the driver

- Build a low-level `send_raw()` and `query_raw()` layer first.
- Preserve and log raw ASCII frames during early development.
- Implement parameter writes before parameter reads, because the write syntax is more explicit in the manual.
- Treat checksum logic as isolated, testable code.
- Represent PV and SP configuration as typed dataclasses.
- Make channel-to-port mapping explicit and injectable.
- Keep batch and blend out of the first stable API unless the user explicitly needs them.

Most importantly, recognize that this is a structured port/parameter protocol. It is closer to a small fieldbus-style ASCII application protocol than to SCPI or to the PR4000B-S command set.

---

## 22. Source note

This guide was derived from [notes/source_manuals/PSR1A-PSR4A-20068380-MAN.pdf](/C:/stoner_measurement/notes/source_manuals/PSR1A-PSR4A-20068380-MAN.pdf), especially:

- rear-panel serial and connector information
- Appendix A, `RS-232 Serial Communications`
- the MFC and 640 pressure-control setup examples
