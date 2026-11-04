# User-guide screenshots

Captured from the running application on Windows in the `stoner_measurement`
Conda environment, using Python 3.14.7 and PyQt5 5.15.11. All illustrations
use dark mode, as requested. They show actual controls and generated data;
image processing only crops the captures.

## Reproducing the example

Run `conda run -n stoner_measurement python notes/capture_user_guide.py`.
The launcher redirects user configuration and INI settings to
`.pytest-runtime/user-guide-capture/`, builds the hardware-free Details →
Run Sequentially → Dummy/Plot Trace sequence, and writes
`docs/examples/simulated_iv.json`. It leaves the normal user configuration
untouched and does not connect any real instruments.

The example supplies User, Sample and Project so Details validation succeeds.
Run with F5, then use the configuration tabs, context menu, Generate Code,
and plot marker controls to reproduce the illustrated states.

## Assets

Final PNGs are in `docs/_static/screenshots/`:

- `workspace.png`: completed sequence, plot and Scan configuration.
- `measurement-details.png`: required Details fields.
- `trace-scan.png`: waveform controls and preview.
- `trace-settings.png`: Dummy model parameters.
- `plot-trace.png`: simple XY trace selection and formatting.
- `run-selection.png`: selected container and Shift+F5 context-menu action.
- `generated-script.png`: generated actions and finally/disconnect block.
- `plot-marker.png`: expanded plot, formatting table and marker label.

Captures were taken with the Windows Computer Use plugin. Intermediate full
captures remain under `.pytest-runtime/user-guide-capture/screenshots/` and
are not documentation assets. Each published figure has alternative text
and a caption in `docs/usage.rst`.

## Extended data workflow

Run the launcher with `--workflow` for `docs/examples/scan_fit_save.json`.
This is a portable version of the user's custom rightmost Test Button
workflow: a Counter replaces the hardware field scan, and a Dummy trace feeds
window filtering and RSJ fitting. It retains trace/point plotting and adds
explicit complete-trace, incremental-table and final-table Save steps.
The launcher adds an equivalent predefined-sequence toolbar button in the
isolated session. All files go under the scratch default data directory.

Eight more figures illustrate `docs/data_workflows.rst`:
`data-workflow.png`, `scan-data.png`, `filter-window.png`, `fit-function.png`,
`fit-parameters.png`, `plot-points.png`, `save-traces.png`, and
`save-incremental.png`.

Verified six 201-row complete-trace files and a six-row final scan table.
The Save child initially writes five collected rows because automatic
collection follows child execution. An independent run of the downloadable
JSON with a final `save_live()` call inside the generated outer try block,
before its finally cleanup, produced all six rows in the same incremental
file. Calling it from the console after cleanup fails lifecycle readiness;
the guide explicitly puts the final call before cleanup.

## Verification

- Ran the complete example and its selected measurement branch in the visible
  application; both completed with an I-V trace and Idle status.
- Independently loaded the downloadable JSON, checked its required Details
  fields, generated Python and compiled it for syntax validation.
- Built Sphinx HTML into `.pytest-runtime/user-guide-html/`. Existing API
  documentation warnings remain; the updated usage page and its image/download
  references have no warnings after correcting the new heading underline.
- Inspected the rendered walkthrough in the browser. All eight figures load,
  have alternative text and captions, and fit the article column. Figure links
  open the original PNGs for closer inspection.
- Ruff check/format and `git diff --check` passed for the launcher and edits.
