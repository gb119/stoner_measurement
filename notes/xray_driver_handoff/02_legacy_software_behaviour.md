# Legacy application behaviour

## Structure

The active `xray.vbp` uses `frm_ThetaControl.frm` for motion/counting, `frm_ScanControler.frm` for scan orchestration, `mod_IO_Communication.bas` for hardware I/O, and `mod_Setup.bas` for configuration. `IO_Communication.bas` is an older near-duplicate. `temp.frm` is an earlier prototype that preserves status-byte decoding omitted from production. The added `mod_SIO.bas` belongs to a different sputter-system application and is transport-migration evidence, not an active X-ray module.

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

The supplied `Xray_Setup.ini` sets `N=100` for theta and `N=50` for 2-theta. At 400 and 200 steps/degree respectively, both represent `0.25 deg` of take-up. These are integer step counts, not angular values stored in the INI.

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

`0xB0`/`0xC0` mutate the 2-theta/theta reference; they are not ordinary homing. Travel limits are loaded from `Xray_Setup.ini` and enforced in the UI, not the controller. The supplied installation profile is:

| Setting | Value |
|---|---:|
| Theta minimum / maximum | `-90 / +90 deg` |
| 2-theta minimum / maximum | `-30 / +90 deg` |
| Theta backlash | `100 steps = 0.25 deg` |
| 2-theta backlash | `50 steps = 0.25 deg` |

Require explicit driver soft limits and preserve these as an initial site profile, subject to confirmation on the present mechanics; the six-digit BCD range is not mechanically safe. `0xA0` resets the limit latch, whose precise status semantics remain unknown.

## Configuration and mutable state

`mod_Setup.bas` requires both INI files at startup. It loads the plot executable path, base data directory, four motion limits, two backlash step counts, and displayed version. The supplied base data directory is `C:\Data\`; after login the application appends the username and creates that per-user directory if needed. The EasyPlot path is legacy integration and is not part of the instrument driver.

`Xray_system.ini` is partly mutable application state rather than hardware configuration. It contains the displayed version, last offset-scan date, a run number, zero-valued counter display offsets, an inter-process `XrayCheck` return field, and a username-to-display-name table. In the active `xray.vbp`, the version, scan date, user lookup, and `XrayCheck` field have live call sites. The counter-offset fields belong to the older `Setup.bas`/`frmMain.frm` source pair rather than the active `mod_Setup.bas`/`frm_Main.frm` project, so they should not be assumed to affect the analysed executable.

For the port, separate configuration into: transport settings; mechanics/safety limits; backlash policy; and application concerns such as user data paths. Do not copy the plaintext legacy user mapping or the `XrayCheck` file-based authentication exchange into the hardware driver.

## Defects not to reproduce

- A 0.1 s receive timeout still falls through and reads data.
- UART status is sampled before waiting and then checked stale.
- `End` kills the process on a status error.
- VB `Single` loses precision for high counts.
- `Timer` needs midnight workarounds; use `time.monotonic()`.
- Some loop counters are 16-bit and can overflow.
- Debug mode advances positions from commands and can conceal missed steps.
- There is no checksum, lock, retry, or resynchronisation policy.
