# Python implementation status

Implemented in `stoner_measurement` on 13 August 2026.

## Delivered layers

- `instruments.xray_diffractometer.XrayDiffractometer`: abstract driver
  contract shared by physical and simulated controllers.
- `instruments.xray.protocol`: exact recovered opcodes, fixed 12-byte codec,
  typed status and snapshot values, and strict length/BCD errors.
- `instruments.xray.LegacyXrayDiffractometer`: locked byte-stream driver with
  snapshot recovery, limits, host stepping, backlash, cancellation, coupled
  theta/2-theta motion, count stop guarantees, zeroing and limit/motor
  operations.
- `instruments.transport.FtdiD2xxTransport`: native FTDI D2XX open/read/write,
  timeout and purge support for the user-facing **Wharfdale** instrument.
- `instruments.xray.SimulatedXrayDiffractometer`: sibling implementation with
  all three motion sets, real configured motion timing with intermediate
  snapshots, and a deterministic synthetic diffraction pattern.
- `xray_control.XrayControllerEngine`: singleton polling engine with
  configurable 0--10 Hz polling, application status-bar lifecycle integration,
  cancellable background moves/counts and persisted site configuration.
- `ui.xray_panel.XrayControlPanel`: Wharfdale/simulated instrument selection,
  connection-state device display, live snapshot/count and motion status,
  safe motion enablement, controller operations, hide action, and a vector
  geometry synoptic.
- Main application Engines menu, toolbar, status indicator, feature setting,
  shutdown lifecycle and Sphinx documentation integration.
- X-ray state-scan, set-angle and count-read plugins with automatic reconnect,
  shared three-mode axis selection and feature-based visibility.
- The X-ray scan defaults to the multi-stage stepped generator. Each point
  marked for measurement moves first and then counts using a per-point runtime
  expression; the shared engine/panel count time is restored in final cleanup.
  The standalone read command performs an active count using that shared time.

## Confirmed geometry

Viewed from above, the X-ray source is on the left, the sample/theta stage is
central, and the detector is on the right. Straight-through defines theta and
2-theta as zero. In reflection geometry, increasing coupled motion turns both
theta and the 2-theta detector arm clockwise. The controller enforces
`2theta = 2 * theta + offset`; one positive theta step (`0x93`) is paired with
one positive detector step (`0x83`).

## Safety boundary

The recovered limits and backlash values ship with `motion.enabled: false`.
The operator must explicitly confirm safe motion in the panel. No physical
direction, limit-switch, disable-opcode, counter-clear or FTDI-mode claim is
treated as bench-validated merely because the simulator and unit tests pass.
Negative single-axis and coupled moves apply each axis' configured backlash
automatically and finish with a positive/clockwise approach; the simulator
publishes the corresponding overshoot and return snapshots.

## Automated evidence

Focused tests cover the codec, opcode mapping, retries, soft limits, count stop
guarantees, abstract/concrete driver discovery, simulator peaks, all three
engine motion sets, simulated connection, and synoptic rendering. Hardware
acceptance remains gated by the bench sequence in
`03_python_implementation_brief.md`.
