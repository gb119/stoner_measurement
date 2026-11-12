# ITC503 per-sensor software temperature scales

The operator confirmed that the NI-DAQmx tables contain nominal and corrected
temperatures in kelvin, and requested selectable direction and YAML persistence.

## API evidence

- NI's [system API](https://nidaqmx-python.readthedocs.io/en/latest/system.html)
  exposes MAX-persisted scales through `System.local().scales.scale_names`.
- NI's [scale API](https://nidaqmx-python.readthedocs.io/en/latest/scale.html)
  exposes `Scale(name).scale_type`, `table_pre_scaled_vals` and
  `table_scaled_vals`. The two arrays contain corresponding values. Import reads
  these properties only; it neither creates a task nor writes a MAX scale.

## Behaviour and persistence

The ITC503 Input Settings editor uses independent scale and direction selectors
for A/B/C. Each controller slot saves an `itc503_calibration` mapping in
`temperature_controller.yaml`. Channel values are null for no conversion or a
snapshot with `scale_name`, `direction`, `pre_scaled_values` and `scaled_values`.
Directions are `nominal_to_corrected` and `corrected_to_nominal`; the original NI
columns are retained in the snapshot. Missing channels retain the legacy shared
lookup from `instruments/oxford_itc503.yaml`.

Imported tables use linear interpolation in both directions, with the legacy
identity fallback outside the table range and existing millikelvin rounding.
The legacy shared YAML table retains its original interpolation behaviour.
Tables must be finite, non-negative and strictly increasing after sorting the
pre-scaled column, so the inverse is well defined. Units are interpreted as
kelvin in both columns, as confirmed by the operator; no unit conversion is inferred.

Readings use the specified channel. Loop setpoints and zone boundaries use the
hardware H status sensor, under the shared instrument lock. When all channel
maps are identical, no extra H status read is needed. Raw zero zone temperatures
are checked before conversion and still terminate table reads.

Application validates every selection before changing any channel. A failed YAML
save restores active selections. Successful changes invalidate cached readings,
stability history and setpoint targets, refresh loop editors, and clear cached
zone temperatures. Applying a scale does not send a new hardware setpoint.
Saved snapshots work offline; explicit reload replaces them from NI-DAQmx.

## Verification

The driver, NI extraction, input editor, lazy panel reads, Model 340 input editor,
secondary service, temperature contracts and legacy temperature test modules
passed together: 292 tests on offscreen PyQt5/Python 3.14 through Miniforge Conda.
Ruff passed for all changed Python files. The new editor was also rendered
offscreen to check control visibility and labels. Markdownlint is unavailable
in the project environment. An additional nitpicky Sphinx build (`-n -W`)
reported 854 unresolved references across the API documentation; CI does not
enable nitpicky mode. Rebuilding with the CI warning policy (`-E -W --keep-going`,
without `-n`) succeeded without warnings. `git diff --check` passed.

Actual NI MAX scale extraction and ITC503 hardware readback remain unverified.
On the instrument computer, select a known table in each direction, compare a
reading at a table node and midpoint, check the displayed setpoint against the
active heater sensor, and reconnect with NI discovery unavailable to confirm the
saved snapshot is retained. No hardware-connected tests were run here.
