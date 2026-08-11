# SR830 auto-sensitivity behavior

The Keithley 6221 + multiple SR830 trace plugin treats sensitivity as an
explicit per-lock-in mode:

* `Auto` is the first sensitivity choice. During configuration it sends the
  SR830 `AGAN` command, waits for the Instrument Finished Command (IFC) status
  bit, then reads back and stores the selected sensitivity.
* Selecting a numeric range disables automatic sensitivity for that lock-in and
  applies the chosen fixed range directly.
* After all configuration and offset operations, the plugin reads and clears
  each SR830 `LIAS?` register. Input/reserve, filter, or output overload bits
  are logged as errors and abort configuration so a sequence cannot continue
  with invalid measurements.

The plugin's master dynamic auto-sensitivity option remains responsible for
adjusting an auto-enabled lock-in between measurements. The `Auto` dropdown
choice removes the previous ambiguity where a displayed numeric range could
coexist with an enabled per-lock-in auto-sensitivity flag.

## Offset and expand timing

The SR830 driver waits for the Instrument Finished Command status after every
`AOFF` auto-offset operation. The multiple-SR830 plugin also waits for command
completion after applying each `OEXP` offset/expand setting.

Before either its configuration-time offset calculation or the user-triggered
`AOFF` path, the plugin waits for the longer of the configured read-delay
multiple and three filter time constants. This delay occurs after the 6221
output is enabled and after signal-affecting SR830 configuration, ensuring the
filter output has settled before an offset is sampled.
