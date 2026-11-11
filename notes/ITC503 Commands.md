# ITC503 command audit

Source: Oxford Instruments *ITC503 Operator's Handbook*, Issue 4, April 2000,
[manufacturer-authored handbook](https://groups.spa.umn.edu/zudovlab/manuals/cryogenics/ITC503.pdf).
Page numbers below are the printed page numbers. This replaces the previous reference,
which incorrectly described C as sensor selection and H as heater range.

## Framing and connection

Sections 8.2–8.4 and 8.6.1 (pp. 35–38): ASCII commands end with CR. Actions reply with
one command letter; reads reply with a letter and data. Rejections start with `?`.
Consume and validate each action acknowledgement before issuing another command.
The shared `BaseInstrument` transaction and `OxfordProtocol` validation do this even
when automatic error polling is disabled, for both ITC503 and IPS120. They do not retry
an action after a missing or invalid acknowledgement. Numeric echo and payload parsing
also live in the shared protocol; only a matching command echo is removed, ignoring case.

Section 10.1 (p. 43): `C0` and `C2` select local control; `C1` and `C3` select remote control.
The driver sends `C3` after successful identity verification, permitting the operator to
return to local control. This changes neither heater nor gas output. `V` reads identity.
`Q0` and `Q2` select response termination and are exceptions without acknowledgements.

## Implemented operational commands

| Operation | Commands or status | Evidence |
| --- | --- | --- |
| Temperatures A/B/C | R1/R2/R3 | p. 44 |
| Setpoint read/write | R0 / T | pp. 44, 47 |
| Heater output read/manual write | R5 / O | pp. 44, 46 |
| Gas position read/manual write | R7 / G | pp. 44, 46 |
| Heater sensor A/B/C | H1/H2/H3; X field H for readback | pp. 45–46 |
| Combined heater/gas automatic control | A0–A3; X field A for readback | p. 45 |
| Proportional band / integral / derivative | P / I / D; R8/R9/R10 | pp. 20, 44–45 |
| Auto-PID table selection | L0 disables; L1 enables | p. 46 |
| Maximum heater voltage | M, in volts; M0 selects dynamic limiting | p. 46 |
| Programmed sweep execution | S0 stops; S1 starts; X field S is progress | pp. 45–46 |
| Auto-PID table read/write | x row, y column, q read, p write | pp. 47–49 |

`A` bit 0 controls heater automatic operation and bit 1 controls gas automatic operation.
Read-modify-write operations preserve the other function under the shared instrument lock.
Bit 2 indicates AutoGFS calibration and is not copied into a command. Invalid X responses
raise an error rather than supplying assumed control states. Hardware may reject gas
commands during calibration; those errors propagate to the caller.

The driver maps automatic heater control with L0 to Closed Loop and with L1 to Zone.
Open Loop selects manual heater control. Off also writes zero manual heater output;
hardware subsequently reports Open Loop because there is no separate off status flag.
Monitor is not advertised as an ITC503 mode. OFF retains gas mode.

Section 4.7 (p. 20): P is a temperature band in kelvin; I and D are times in minutes,
with documented upper limits of 140 and 273 minutes. These are not SI seconds.
Manual PID updates issue L0 before P/I/D so the table cannot overwrite the requested terms.
O accepts 0–99.9 percent; G is sent at 0.1 percent resolution with the same valve limit.
Non-finite and out-of-range output settings are rejected before transmission.
The instrument enforces fitted heater voltage and temperature limits.

## Generic API boundaries

ITC503 has no discrete heater power ranges. H is exclusively sensor selection, not a
heater enable or power-range command. `has_heater_range=False` hides that editor and
prevents Apply and Make Safe from issuing it. Explicit range calls raise NotImplementedError.

The continuous ramp API cannot represent a stored, multi-step ITC503 sweep. `has_ramp=False`
hides that editor; rate getters/setters and generic ramp enable reject the operation.
Use the explicit `start_sweep()` and `stop_sweep()` methods for an existing hardware programme.
The driver does not rewrite or erase sweep tables. A running sweep overrides T commands
(p. 47), so stop it explicitly before requesting a fixed setpoint.

The Auto-PID table has 32 rows (p. 48), not the 16 rows of the sweep table. Columns 1–4
are upper temperature, P, I and D. Each complete row operation holds the shared lock.
Ramp, heater range and heater output fields in the generic ZoneEntry have no ITC503
Auto-PID equivalent and are not written. Existing temperature calibration applies to T,
R0, temperature registers and table upper temperatures. This audit preserves that calibration.

Apply selects the input before writing the target, then configures supported settings
before selecting the final mode. Zone mode skips individual PID writes. Make Safe skips
unsupported heater ranges and uses the driver Off operation to zero heater output.

## Verification and bench checks

Regression coverage includes exact action acknowledgements, rejected and malformed responses,
all heater/gas bit combinations, calibration-state bits, live sensor readback, output limits,
32-row table bounds and real primary Apply button clicks through the engine and driver.

On an ITC503 with the normal lab load and limits, verify: connection selects remote/unlocked;
Read matches the front panel; applying a sensor and target selects the intended sensor and
setpoint; gas-mode changes preserve heater mode and vice versa; manual output and Off reach
the heater; gas Apply changes the valve; repeated Apply/Read leaves no stale replies.
Check Auto-PID selection with a populated table. Confirm programmed sweep start/stop separately.
No physical hardware was used for the automated checks.
