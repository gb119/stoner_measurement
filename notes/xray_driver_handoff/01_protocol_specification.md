# Reconstructed wire protocol

## 1. Boundary between PC card and instrument

The original software accesses four consecutive PC I/O ports:

| Address |     Hex | Legacy use                                                           | FTDI-driver treatment                                                   |
| ------: | ------: | -------------------------------------------------------------------- | ----------------------------------------------------------------------- |
|     784 | `0x310` | UART reset when written; UART/FIFO status when read                  | Local old-card operation; do not transmit                               |
|     785 | `0x311` | Command/data transmit register when written; received byte when read | Probable instrument byte stream                                         |
|     786 | `0x312` | FIFO reset                                                           | Local old-card operation; map to host input-buffer flush only if needed |
|     787 | `0x313` | Disable card loopback                                                | Local old-card operation; omit                                          |

This separation is critical. The source's named “UART reset” is `write(0x310, 0)`, whereas all instrument operations
are `write(0x311, opcode)`. `InitialiseInterfaceCard()` resets the old UART and FIFO and disables loopback; it is not
an instrument reset sequence.

Confidence: **high** for the register roles in the legacy card. The related-system `mod_SIO.bas` gives
**high-confidence evidence for the migration pattern** “old data-register value becomes one USB byte”, but only
**medium-high confidence for this X-ray installation's exact FTDI path**, because the X-ray adapter, helper
implementation, and intermediate electronics are unavailable.

## 2. Command frame

Every observed instrument command is exactly one binary octet. There is no observed address, length, checksum,
acknowledgement, ASCII representation, CR, or LF.

| Operation                      | Decimal |    Hex | Binary      | Evidence confidence |
| ------------------------------ | ------: | -----: | ----------- | ------------------- |
| Disable 2-theta motor          |     128 | `0x80` | `1000_0000` | High                |
| Step 2-theta anticlockwise     |     130 | `0x82` | `1000_0010` | High                |
| Step 2-theta clockwise         |     131 | `0x83` | `1000_0011` | High                |
| Disable theta motor            |     144 | `0x90` | `1001_0000` | High                |
| Step theta anticlockwise       |     146 | `0x92` | `1001_0010` | High                |
| Step theta clockwise           |     147 | `0x93` | `1001_0011` | High                |
| Clear/reset limit latch        |     160 | `0xA0` | `1010_0000` | High                |
| Zero 2-theta display/reference |     176 | `0xB0` | `1011_0000` | High                |
| Zero theta display/reference   |     192 | `0xC0` | `1100_0000` | High                |
| Start scalar count             |     208 | `0xD0` | `1101_0000` | High                |
| Stop scalar count              |     224 | `0xE0` | `1110_0000` | High                |
| Request data transmission      |     240 | `0xF0` | `1111_0000` | High                |

“High” means the function name, comment, call sites, and literal byte agree. The physical direction labelled
clockwise/anticlockwise should still be verified because wiring or viewpoint can reverse the laboratory meaning.

### Inferred construction

The high nibble is a command/device selector:

- `0x8_`: 2-theta motor
- `0x9_`: theta motor
- `0xA_`: limit latch
- `0xB_`: zero 2-theta
- `0xC_`: zero theta
- `0xD_`: scalar start
- `0xE_`: scalar stop
- `0xF_`: read snapshot

For both motors, the observed low nibble is:

- `0x0`: disable
- `0x2`: one anticlockwise step
- `0x3`: one clockwise step

The symmetry suggests low bit 0 is direction and low bit 1 is a step/enable strobe. That bit-level interpretation is
**medium-confidence inference**, not directly documented. Do not synthesize unobserved values (`0x81`, `0x84`-`0x8F`,
etc.). Use only the complete known bytes.

## 3. Read transaction

The legacy sequence is:

1. reset the old UART;
2. clear its FIFO;
3. disable card loopback;
4. transmit `0xF0`;
5. wait 10 ms;
6. for each of 12 bytes, poll the card status until bit 0 becomes 1, then read a byte;
7. wait 10 ms between byte reads;
8. decode the fixed frame.

For FTDI, steps 1-3 should normally become `reset_input_buffer()` (and possibly output-buffer reset) before the query,
not transmitted bytes. The 10 ms pre-read and inter-byte delays describe the old implementation rather than proven
protocol requirements. Start conservatively, then remove unnecessary sleeps after capture-based testing.

The old UART status check requires `(status & 0x1F) == 3`, but this status is from the ISA UART/card and is not part of
the 12-byte response. It must not be expected from the FTDI stream.

The related `mod_SIO.bas` independently sends decimal `240` through `WriteUSBDeviceBufferSIO(device_no, 240, 1)` in
`ReadHardwareStatus()`. That corroborates a one-byte `0xF0` USB request. The module contains no corresponding USB read
call, so it does not establish response framing, receive timing, or whether the X-ray and sputter-system remote boards
return the same data.

## 4. Fixed 12-byte response

The frame is positional and has no delimiter or checksum:

| Byte (1-based) | Meaning                              | Encoding                                      |
| -------------: | ------------------------------------ | --------------------------------------------- |
|              1 | motor direction/enable flags         | bit field                                     |
|              2 | limit/data-ready/overflow-like flags | bit field                                     |
|            3-6 | scalar count                         | 8 packed-decimal digits                       |
|            7-9 | 2-theta raw position                 | 6 packed-decimal digits, signed by wraparound |
|          10-12 | theta raw position                   | 6 packed-decimal digits, signed by wraparound |

### Bytes 1 and 2: recovered status meanings

The production decoder ignores these bytes, but `temp.frm` preserves an earlier decoder:

```text
byte 1 low nibble:  bit 0 DIR0, bit 1 EN0
byte 1 high nibble: bit 0 DIR1, bit 1 EN1
byte 2 low nibble:  bit 0 LI1, bit 1 LA1, bit 2 DRDY, bit 3 INF
```

The exact association of motor 0/1 with theta/2-theta and the expansions of `LI1`, `LA1`, and `INF` are not documented.
Likely interpretations include direction, enable, limit switch/latch, data ready, and FIFO/overflow status. Expose the
raw bytes and named provisional bits; do not make safety decisions from the provisional names until bench-verified.

### Packed-decimal decoding

For each byte `b`:

```python
low = b & 0x0F
high = (b >> 4) & 0x0F
```

Both nibbles must be decimal digits 0-9 for bytes 3-12. The least-significant digit appears first:

```python
def decode_le_bcd(field: bytes) -> int:
    value = 0
    multiplier = 1
    for byte in field:
        low, high = byte & 0x0F, byte >> 4
        if low > 9 or high > 9:
            raise ProtocolError("invalid packed-decimal digit")
        value += low * multiplier + high * multiplier * 10
        multiplier *= 100
    return value
```

Example: bytes `46 37` hex decode as decimal digits `6,4,7,3`, hence integer `3746`. This is little-endian by decimal
digit-pair, not ordinary binary little-endian.

### Counts

```text
counts = decode_le_bcd(frame[2:6])
```

Range is nominally `0..99,999,999`. The VB program uses `Single`, which can lose integer precision at high counts;
Python should use `int`.

### Signed angular positions

```python
def decode_wrapped_six_digits(field: bytes) -> int:
    raw = decode_le_bcd(field)
    return raw - 1_000_000 if raw >= 500_000 else raw

two_theta_degrees = decode_wrapped_six_digits(frame[6:9]) / 200.0
theta_degrees = decode_wrapped_six_digits(frame[9:12]) / 400.0
```

The source uses `> 499999.5`, equivalent to integer `>= 500000`. Values `500000..999999` encode negative raw positions
`-500000..-1` by modulo-one-million wraparound. Therefore:

- 2-theta resolution: `1/200 = 0.005°`; nominal representable range `-2500.000°..2499.995°`.
- theta resolution: `1/400 = 0.0025°`; nominal representable range `-1250.000°..1249.9975°`.

Configured software travel limits are much narrower and must remain a separate safety layer.

## 5. Framing and error handling requirements

The Python implementation should reject:

- a timeout before 12 bytes arrive;
- a short or long response for a single `0xF0` transaction;
- any nibble above 9 in bytes 3-12;
- implausible positions outside configured machine travel limits (reported separately from malformed BCD);
- concurrent query/motion traffic.

Because there is no checksum or sync byte, a lost or inserted byte can produce a valid-looking but shifted BCD frame.
On any framing/BCD failure: flush the input buffer, wait for quiescence, retry one complete `0xF0` transaction at most,
and then fail closed. Position plausibility and continuity checks are strongly recommended.

## 6. Corroborating FTDI migration evidence

The added `mod_SIO.bas` is explicitly for the “Ivor” sputter system, not the X-ray application, so its device opcodes
must not be imported into the X-ray driver. Its transport changes are nevertheless directly relevant:

- `WriteDataToPort(address, DataByte)` no longer uses `address`; it calls `WriteUSBDeviceBufferSIO(gIVORUSBSIODeviceNo,
  Val(DataByte), 1)`.
- Motor command construction still produces the original byte values and sends each as a one-byte USB buffer.
- The old UART reset, FIFO reset, and loopback routines retain their names but have their ISA writes commented out,
  making them effective no-ops.
- `ReadHardwareStatus()` sends `0xF0` in exactly the same one-byte form.
- A global integer device number selects the USB device, suggesting a native/helper API rather than proving a
  COM-port/VCP interface.

This is strong evidence that the intended adapter is a transparent command-byte replacement at the application
boundary. It does **not** identify `WriteUSBDeviceBufferSIO`'s ABI, FTDI mode, serial settings, electrical interface,
buffering, latency, or read semantics; its declaration and implementation are absent.

There is also a migration artefact in `Reset_Latches()`: it calls `WriteDataToPort(..., 176)` and then calls
`WriteUSBDeviceBufferSIO(..., 176, 1)` directly, even though `WriteDataToPort` already forwards to USB. This appears to
transmit the byte twice. Do not reproduce that duplication, and do not transfer the sputter-system value `0xB0` into
the X-ray opcode table, where `0xB0` means zero 2-theta.

## 7. Unknown serial settings

The repository provides no USB helper implementation, baud rate, parity, stop-bit, flow-control, RTS/DTR,
latency-timer, or voltage-level configuration. The `MSCOMM32.OCX` reference is unused by the X-ray application. The
owner identifies the related adapter as FTDI-based, but `mod_SIO.bas` alone does not distinguish VCP, D2XX, bit-bang,
or a custom wrapper/firmware path. Do not present `9600 8N1` as recovered fact; it is merely the target framework's
default. Determine settings from, in preferred order:

1. the missing declaration/implementation of `WriteUSBDeviceBufferSIO` and its open/read/configuration companions;
2. FTDI EEPROM/configuration and any existing working application;
3. documentation or schematics for the replacement converter and old interface card;
4. oscilloscope/logic-analyser capture of a known command such as `0xF0`;
5. cautious parameter sweep with motors disabled, accepting only settings that repeatedly yield valid 12-byte BCD
   frames.
