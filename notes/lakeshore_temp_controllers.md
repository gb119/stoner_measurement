# Lake Shore temperature-controller command boundaries

## Model 340 audit, 11 November 2026

Evidence: [Lake Shore Model 340 User's Manual](https://www.lakeshore.com/docs/default-source/product-downloads/340_manual.pdf),
particularly sections 6, 9.1.3 and the command reference on printed pages 9-23 to 9-43.
The Model 335 and 336 driver implementations were left unchanged. The previous comparison
sheet in this file incorrectly claimed that the 340 lacked ZONE commands and shared
later-model input/output layouts; it must not be used as a programming reference.

| Area | Model 340 behaviour | Manual reference |
| --- | --- | --- |
| Sensor assignment | CSET uses A/B labels, not numeric input indices | 9-31 |
| Loop enable | CSET enable flag is distinct from the CMODE algorithm | 9-29, 9-31 |
| Control algorithms | CMODE 1 manual PID, 2 zone, 3 open loop; 4–6 are autotune | 9-29 |
| Heater output | HTR? has no loop argument | 9-33 |
| Loop 2 output | AOUT? 2 reads actual analog-output percentage | 9-26 |
| Heater range | RANGE and RANGE? have no loop argument and belong only to Loop 1 | 9-40, 9-41 |
| Manual output | MOUT addresses a loop and supports signed percentages | 9-38, 9-39 |
| Zones | Ten rows, six fields: upper temperature, P, I, D, manual output, heater range | 9-43 |
| Input type | INTYPE has type, sensor units, coefficient, excitation, range | 9-34, 9-35 |
| Input enable/compensation | Separate INSET fields; compensation can also be paused | 9-34 |
| Error reporting | ESR error bits 2–5 identify query, device, execution and command errors | 9-3, 9-23 |

The 340 overrides are isolated to Lakeshore340. No 335 OUTMODE, INTYPE, ZONE or status
implementation was rewritten. Native 340 actions check ESR under the shared lock when
automatic error checking is enabled; actions are never replayed on rejection. Unused
power-on and operation-complete bits do not trigger command failures.

Off disables the loop through CSET instead of falling back to closed-loop CMODE 1.
Sensor selection preserves setpoint units, loop enable and power-up flags. Kelvin API
setpoints convert Celsius values; sensor-unit setpoints are rejected because a generic
conversion to kelvin would require a sensor-specific response curve.

Loop 2 is not a second ranged heater. Its Analog Output 2 must already be configured
for Loop 2 control on the instrument (section 7.1.3). The driver does not change analog
routing or bipolar limits on connection. Its range editor is hidden, and Apply/Make Safe
skip the unavailable range command. Heater ranges are labelled by index because their
power depends on the configured current limit and heater resistance (section 6.12).

Ramp rates use 0–100 K/min. The 340 PID values retain native semantics: proportional
gain, integral reset, and derivative time in seconds (section 6.6). Apply configures ramp
parameters before writing a new target, so the target uses the selected rate. This ordering
is opted into by this driver; the tested 335 Apply path is preserved.

## Native input setup

The 340 advertises a dedicated input editor through the lakeshore340 input-settings schema.
The shared 335/336 editor retains its existing fields. Both primary and secondary sessions
select their own editor, and the page scrolls when both tables need more space.
Programmatic input setup uses the exported Lakeshore340InputSettings dataclass. It adds
sensor_units, coefficient, excitation, input_enabled and compensation_mode fields.
Generic autorange and temperature-unit INTYPE fields are rejected instead of being sent
in the wrong positions. Ordinary InputChannelSettings can still specify shared curve,
filter, sensor-type and compensation fields.

Only explicitly supplied native fields are sent. Blank optional arguments preserve the
instrument's settings. In particular, changing just the sensor type must not resend all
INTYPE fields: the manual states that explicit units/coefficient/excitation/range overrides
select the Special sensor type. Compensation pause mode is retained as an integer.

The native editor records a successful hardware read for each channel and sends field
differences only. Choosing a preset disables manual overrides until Special is selected,
so writing a preset cannot accidentally resend its old implied parameters. Each changed
channel is read back after writing to refresh instrument-selected defaults. Failed writes
or readbacks invalidate that channel's baseline and require an explicit Read All; no action
is automatically replayed. Nothing on this page subscribes to poll-driven state updates.

Optional 340 expansion inputs beyond standard A/B remain outside this driver's catalogue;
they must not be inferred from the 335/336 or enabled by a fabricated channel name.

## Verification

Polling follow-up: the Model 340 protocol now configures the GPIB error mask as
0x10 and disables MAV polling. Manual section 9.1.3.1 (printed page 9-2) defines
bit 2 as Settle and bit 4 as instrument Error; bit 4 is not Message Available.
The transport's default 0x04 error mask incorrectly rejected normal settled
readings before consuming the KRDG response. Regression checks exercise actual
GpibTransport reads with normal status flags and preserve rejection of 0x10.
The polling log now includes the exception type and message in its main entry,
so the log viewer can display the cause without opening traceback details.
Confirm continuous polling on the physical 340 after restarting and reconnecting;
fake-resource checks cannot establish bench behaviour.

Tests cover native commands, CSET flag preservation, off versus open-loop modes,
Celsius conversion, sensor-unit rejection, status bits, six-field zone tables, native
input setup, event-register errors and real Apply clicks for both loops. The combined
instrument/controller/panel suite passed 478 tests on offscreen PyQt5, including the
existing 335 regression tests. Hardware validation remains outstanding.

Bench checks: compare Read with the front panel; select A/B and set a known target;
confirm a new target ramps at the selected rate; verify Loop 1 range and output;
verify Loop 2 uses analog output 2; exercise manual output and Off; read/write one
known zone; verify explicit native input changes without overwriting unrelated settings.
