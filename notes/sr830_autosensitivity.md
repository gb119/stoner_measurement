# SR830 auto-sensitivity behavior

The Keithley 6221 + multiple SR830 trace plugin treats sensitivity as an
explicit per-lock-in mode:

* `Auto` is the first sensitivity choice. During configuration it sends the
  SR830 `AGAN` command, waits for the Instrument Finished Command (IFC) status
  bit, then reads back and stores the selected sensitivity.
* Selecting a numeric range disables automatic sensitivity for that lock-in and
  applies the chosen fixed range directly.
* After all configuration and offset operations, the plugin sends `*CLS` to
  each SR830, waits 100 ms for fresh status, then reads `LIAS?`. Only overload
  flags that reassert after the clear abort configuration. This avoids
  rejecting a measurement because of a transient overload during setup.

The plugin's common **Enable auto-ranging** option remains responsible for
adjusting an auto-enabled lock-in between measurements. The `Auto` dropdown
choice removes the previous ambiguity where a displayed numeric range could
coexist with an enabled per-lock-in auto-sensitivity flag.

## Per-lock-in input and filter settings (2026-09-14)

Filter slope, input coupling, line filtering, and input source are stored on
each `LockInEntry` and edited in its table column. Old saves with common filter
settings migrate those values to every entry; explicit per-entry values win.
Reading instrument settings updates the selected entries independently.

SR830 inputs are A, A-B, current at 1 MΩ, and current at 100 MΩ. The SR7265
also offers inverted B voltage input, and labels its current modes as wide
bandwidth and low noise. The input choice determines the available sensitivity
ranges and whether signal units are volts or amperes. Resistance conversion
adds channels only for voltage inputs. The SR830 driver's existing sensitivity
API uses voltage-table indices; the plugin converts current ranges at that
boundary. Range matching tolerates floating-point conversion rounding.

The SR7265 retains its native status check: it does not support `*CLS`.
Protocol references: [SR830 manual, sections 5-5 and 5-20 to 5-23](https://www.thinksrs.com/downloads/PDFs/Manuals/SR830m.pdf)
and [manufacturer's 7265 manual, sections 6.4.01 and 6.3](https://manualzz.com/doc/25586510/signal-recovery-7265-lock-in-amplifier-instruction-manual).
The 100 ms fresh-status interval is an implementation choice that still needs
bench verification; fake-instrument tests do not establish real overload
reassertion timing.

## Offset and expand timing

The SR830 driver waits for the Instrument Finished Command status after every
`AOFF` auto-offset operation. The multiple-SR830 plugin also waits for command
completion after applying each `OEXP` offset/expand setting.

Before either its configuration-time offset calculation or the user-triggered
`AOFF` path, the plugin waits for the longer of the configured read-delay
multiple and three filter time constants. This delay occurs after the 6221
output is enabled and after signal-affecting SR830 configuration, ensuring the
filter output has settled before an offset is sampled.

## Auto-function completion timeouts (2026-10-01)

`SRS830.auto_gain()`, `auto_phase()` and `auto_reserve()` use a completion
deadline separate from the transport's normal I/O timeout. The default is the
longest of 120 seconds, 30 times the active output-filter time constant and
the transport timeout. The driver queries `OFLT?` before each auto command so
front-panel changes and settings inherited from an earlier session are included.
The query, command and completion poll share the instrument resource lock.

The driver still returns immediately when the Serial Poll Status Byte IFC bit
(bit 1) reports completion; this allowance is a maximum wait, not a fixed delay.
Callers can override it in seconds, for example `lia.auto_gain(timeout=300.0)`.
An override skips the time-constant query. Normal communication failures still
propagate, and the transport timeout is left unchanged. Generic `wait_for_ifc()`
and auto-offset waits retain their existing deadlines.

The [manufacturer's SR830 manual](https://www.thinksrs.com/downloads/PDFs/Manuals/SR830m.pdf),
sections 4-7, 4-19, 5-11 and 5-21, documents potentially slow auto gain/reserve,
the IFC completion bit, and output settling after auto phase. It does not give
a worst-case execution deadline: the 120-second minimum and 30-time-constant
multiple are conservative driver policy, not manufacturer guarantees.
`AGAN` does nothing when the time constant exceeds one second. Auto phase can
also do nothing with unstable phase; command completion does not establish
successful adjustment or settled outputs.

Fake-transport tests cover delayed completion, current-setting readback,
bounded expiry, explicit deadlines and propagation of communication failures.
Bench validation remains outstanding: run gain/reserve at supported gain time
constants up to one second, then phase/reserve with longer constants, and
confirm IFC polling returns at completion without a premature timeout.
