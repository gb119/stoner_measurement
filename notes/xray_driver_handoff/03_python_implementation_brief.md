# Python implementation brief for `stoner_measurement`

Target checked at commit `d90b3ba835dbac011ddc840cec1187b827715a00` (13 August 2026).

## Architecture

Implement a dedicated binary `BaseInstrument` driver with a shared controller object and theta/2-theta axis facades.
Keep these layers separate:

1. opcode enum and pure 12-byte codec;
2. fixed-length raw transport transaction;
3. axis mechanics, limits, timing, cancellation, backlash;
4. higher-level scan orchestration.

The existing `SerialTransport` supports arbitrary byte writes and `read(12)`. Configure no terminator and a 12-byte
maximum. Do not force the result through a protocol API that returns `str`; call `transport.write(bytes([opcode]))` and
`transport.read(12)` under one shared lock. The related-system `mod_SIO.bas` strongly supports this exact one-byte
write shape, but does not prove that the deployed X-ray adapter is exposed as a VCP serial port.

Suggested modules:

```text
src/stoner_measurement/instruments/xray/{__init__,protocol,legacy_diffractometer}.py
tests/unit/instruments/drivers/test_legacy_xray_{protocol,diffractometer}.py
```

## Types and API

Define an `IntEnum` containing exactly the 12 known opcodes, an immutable `ControllerStatus`, and an immutable
`XraySnapshot(theta_deg, two_theta_deg, counts, status, raw_frame)`. Retain unverified status names as provisional and
always expose raw bytes.

Recommended controller methods:

```text
read_snapshot()
step_theta(direction, steps=1, interval_s=...)
step_two_theta(direction, steps=1, interval_s=...)
move_theta(angle_deg, speed_deg_per_min, ...)
move_two_theta(angle_deg, speed_deg_per_min, ...)
start_count(); stop_count(); count(duration_s)
zero_theta(); zero_two_theta(); reset_limit_latch()
disable_theta(); disable_two_theta()
```

Distinguish timeout, wrong length, invalid BCD, travel-limit, and position-discontinuity errors using
repository-standard base exceptions where possible.

## Transaction and recovery

`read_snapshot()` must acquire the lock, write only `b"\xF0"`, read exactly 12 bytes, validate/decode, apply
plausibility checks, and return the snapshot. On length/BCD failure, flush at the recovery boundary and retry at most
once, then fail closed. Do not flush indiscriminately before every request.

There is no checksum, delimiter, transaction ID, or sync marker. Never interleave motion/count commands with a snapshot
response. Add continuity checks so a shifted but digit-valid frame cannot silently become a plausible measurement.

## Motion

Use 400 steps/degree for theta and 200 for 2-theta. Prefer integer step units or `Decimal` over accumulated float.
Explicitly reject or transparently round unreachable targets.

Algorithm: read position; validate soft limits; compute signed step count; send one opcode per step; wait `max(0.010,
60/(steps_per_degree*speed_deg_per_min))`; check cancellation between steps; apply configured backlash policy; reread;
verify target within one step plus tolerance. Detect missed or wrong-direction steps.

Retain the 10 ms minimum initially. Faster FTDI transmission does not imply faster mechanics are safe.

## Counting

Under the shared lock, send start, perform a cancellable monotonic wait, guarantee stop in `finally`, then read a
snapshot. On interruption, calculate any rate using actual elapsed time. Decide whether cancellation raises with a
partial snapshot or returns an explicitly interrupted result.

## Serial configuration

Expose port, baud rate, data bits, stop bits, parity, flow control, timeouts, and optional pre-read delay as
configuration until measured. The target transport's 9600-8N1 defaults are not recovered instrument facts. Extend it
with `write_timeout`, `dsrdtr`, or inter-byte timeout only if bench evidence requires them.

Prefer FTDI VCP/pyserial if bench inspection shows that interface. The related migration instead exposes
`WriteUSBDeviceBufferSIO(device_no, value, 1)`, which could be a D2XX/native wrapper or application-specific DLL;
obtain that helper before choosing the backend. Keep the protocol/controller above a small binary transport interface
so VCP and native-FTDI implementations can be swapped without changing mechanics or scan code.

Do not emulate legacy writes to ISA control addresses. In the related migration, UART reset, FIFO reset, and loopback
setup became no-ops; only data bytes were forwarded. Map recovery to transport-local purge/reset operations when
supported.

## Recovered installation configuration

Represent the supplied `Xray_Setup.ini` values in a validated site configuration, separate from protocol constants:

```text
theta.soft_limits_deg = (-90.0, 90.0)
two_theta.soft_limits_deg = (-30.0, 90.0)
theta.backlash_steps = 100          # 0.25 deg
two_theta.backlash_steps = 50       # 0.25 deg
```

These are recovered deployment defaults, not universal device capabilities. Require an explicit configuration/profile
and confirmation before enabling motion. Keep transport settings in the instrument connection configuration, mechanics
settings in the controller/axis configuration, and data paths/user identity outside the driver.

## Required unit tests

Pure codec tests:

- all opcode values and one-byte/no-terminator serialization;
- `46 37` hex decodes to `3746`;
- all field boundaries and status bytes excluded from BCD checks;
- raw angular values 0, 499999, 500000, and 999999;
- theta raw unit = `0.0025°`, 2-theta = `0.005°`;
- invalid low/high nibbles and frames of 0/11/13 bytes raise.

Reference frames:

```text
00 00 56 34 12 00 00 02 00 00 04 00
=> counts 123456; 2-theta 1.0°; theta 1.0°

00 00 01 00 00 00 00 98 99 00 96 99
=> counts 1; 2-theta -1.0°; theta -1.0°
```

Fake-transport tests:

- snapshot writes `F0` then requests 12 bytes;
- exact opcode and repetition for every step;
- target conversion for both axes/directions;
- limit rejection sends nothing;
- cancellation stops further steps;
- stop-count occurs on success, exception, and cancellation;
- locking prevents interleaving;
- one recovery retry then failure;
- post-move missed-step detection and backlash sequence.
- supplied site-profile limits reject theta outside `-90..90` and 2-theta outside `-30..90` without I/O;
- supplied backlash values produce exactly 100 theta or 50 2-theta corrective steps in the configured direction;
- reset/recovery never serializes ISA addresses `0x310`, `0x312`, or `0x313` as opcodes.

Follow the target `AGENTS.md`: read `notes/testing_guidelines.md` before tests and run via `conda run -n
stoner_measurement`.

## Bench gates

1. Locate the declaration, DLL, and open/read/configuration companions for `WriteUSBDeviceBufferSIO`; record the FTDI
   part, VID/PID, EEPROM, firmware/driver mode, wiring and electrical levels.
2. With motion/X-rays inhibited, capture `0xF0`; identify settings and prove repeatable 12-byte valid-BCD replies.
3. Repeat 100+ reads and measure latency/partial-read behaviour.
4. Map status bits by changing one safe state at a time.
5. Verify counter start/stop/reset/latch using known intervals/pulses.
6. Issue one motor step at low rate; verify axis, sign and exact raw increment.
7. Verify disable and limit-latch behaviour safely.
8. Test small closed-loop moves, cancellation, backlash and missed-step detection.
9. Integrate scans only after primitives pass.

Before motion, confirm that the supplied `-90..90 deg` theta, `-30..90 deg` 2-theta, and `0.25 deg` backlash profile
still matches the current instrument.

Log timestamped raw TX/RX, settings and physical observations; turn confirmed captures into fixtures.

## Definition of done

- binary commands have no text encoding/terminator;
- malformed/partial frames fail closed;
- serial settings, directions, resolutions and status semantics are measured/documented;
- locking, soft limits, cancellation and post-move verification exist;
- stop-count is guaranteed;
- driver registration/export follows repository conventions;
- relevant tests, Ruff and type checks pass in the prescribed environment.
