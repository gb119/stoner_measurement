# Legacy application behaviour

## Structure

The active `xray.vbp` uses `frm_ThetaControl.frm` for motion/counting, `frm_ScanControler.frm` for scan orchestration, and `mod_IO_Communication.bas` for hardware I/O. `IO_Communication.bas` is an older near-duplicate. `temp.frm` is an earlier prototype that preserves status-byte decoding omitted from production.

## Motion is host-generated stepping

There is no move-to-angle command. The host sends one opcode per step:

- theta: `0.0025°` (`400` steps/degree);
- 2-theta: `0.005°` (`200` steps/degree).

Absolute motion reads current position, computes a step count, then loops over the relevant opcode. Python must do the same unless new FTDI firmware provides a documented higher-level function.

The delays are:

```text
theta delay_ms   = 60 / (400 * speed) * 1000
2theta delay_ms  = 60 / (200 * speed) * 1000
minimum          = 10 ms
```

The likely unit is degrees/minute: a speed of 1 moves either axis at 1 degree/minute. The floor caps theta at 15°/min and 2-theta at 30°/min. Commands have no acknowledgement; the program sleeps after each.

For negative moves, optional backlash correction sends `N` extra anticlockwise steps then `N` clockwise steps, ending with a positive approach. Make this configurable mechanics policy, separate from byte encoding.

Abort is cooperative: stop issuing steps. The active UI never uses the motor-disable opcodes, so sending disable on cancellation requires hardware validation.

## Counting

Counting is host timed:

1. send `0xD0` start;
2. wait;
3. send `0xE0` stop;
4. send `0xF0` and read the snapshot.

No duration is sent to hardware. Use a monotonic clock and guarantee stop in a `finally` block. Scans plot `counts / count_time`. Bench-test whether start clears the prior count; the source never explicitly clears it.

## Snapshots and scans

`0xF0` returns theta, 2-theta, and count atomically. The UI treats the positions as authoritative before and after moves. Preserve this as an immutable typed snapshot including both raw status bytes and raw frame.

Theta and 2-theta scans are point-by-point compositions of move, count, and plot. No device-side sweep, trajectory, trigger list, or buffered dataset is recovered. Scanning belongs above the driver.

## Zeroing and limits

`0xB0`/`0xC0` mutate the 2-theta/theta reference; they are not ordinary homing. Travel limits are loaded from `Xray_SETUP.INI` and enforced in the UI, not the controller. Require explicit driver soft limits; the six-digit BCD range is not mechanically safe. `0xA0` resets the limit latch, whose precise status semantics remain unknown.

## Defects not to reproduce

- A 0.1 s receive timeout still falls through and reads data.
- UART status is sampled before waiting and then checked stale.
- `End` kills the process on a status error.
- VB `Single` loses precision for high counts.
- `Timer` needs midnight workarounds; use `time.monotonic()`.
- Some loop counters are 16-bit and can overflow.
- Debug mode advances positions from commands and can conceal missed steps.
- There is no checksum, lock, retry, or resynchronisation policy.

