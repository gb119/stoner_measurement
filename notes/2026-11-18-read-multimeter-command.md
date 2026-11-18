# Read Multimeter command

Added `read_multimeter` / `ReadMultimeterCommand`, exported from the command
package and listed under **Keithleys → Read Multimeter**. It supports the
2000 and 2700 for one fresh scalar reading per execution, with the same owned
connection lifecycle as Read Electrometer. Configuration and result state are
separate: settings persist, connections and acquired values do not. Failed
reads clear both the reading and setting readbacks.

Functions are DC/AC voltage/current, two-/four-wire resistance, frequency,
period and temperature. Temperature is explicitly set to kelvin, retaining the
instrument's sensor configuration. Settings cover range/autorange, NPLC,
averaging enable/count/type, AC bandwidth, gate time, trigger delay and timeout.
Inactive settings are neither evaluated nor sent to hardware. Numeric range,
integration and timing fields support configuration-time runtime expressions.

The command publishes the selected measurement and applicable numeric setting
readbacks. In particular, Range is queried after the reading so it reflects
autorange. Boolean outputs use 0/1, and Filter Type uses 0 for repeating or 1
for moving. Timeout is the local transport setting. The catalogue follows the
function and AC bandwidth. Missing/inapplicable readbacks are not fabricated
from requested settings.

## Driver evidence and boundaries

- [2000 user manual, Rev. J](https://download.tek.com/manual/2000-900_J-Aug2010_User.pdf):
  SCPI sense/format/trigger subsystems describe function-qualified ranges,
  NPLC, averaging, AC bandwidth, numeric reading elements and single-sample
  acquisition. The legacy generic sense-prefix helper now retains `:AC`
  instead of accidentally configuring the corresponding DC subsystem.
- [2700 user manual, Rev. K](https://download.tek.com/manual/2700-900-01K_Feb_2016.pdf):
  sections 3–4 describe DMM operation and function-specific settings. AC NPLC
  is used only at 300 Hz lower bandwidth; frequency/period use aperture rather
  than integration/filter/range commands. Chapter 4 gives the supported filter
  types and count, and section 3 describes temperature units.

The 2700 is treated only as a multimeter. The driver sends no reset, route,
relay, scan-list or channel-list commands. Use ordinary DMM mode with the
desired input terminals selected beforehand. Switching support is deferred.
Single-reading setup aborts prior acquisition, disables continuous initiation
and buffer storage, selects one immediate trigger and one sample, and reads
numeric ASCII data. The current function is checked before acquiring, and
empty/multiple/malformed readings are rejected.

## Validation

85 focused tests passed on Python 3.14.7/PyQt5, covering all nine functions on
both models, settings readbacks/units, expressions and inactive controls,
persistence, generated sequences, reconnect, partial failure and the existing
electrometer command. Targeted Ruff and the focused docstring audit passed.
The configuration page was rendered offscreen and inspected. Editable package
installation was refreshed without changing dependencies. Physical meter
operation and other Qt bindings remain unverified.
