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
