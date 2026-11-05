# Keithley Pulse Delta trace

## Contract and evidence

Implemented the separate `k6221_pulse_delta` entry point; ordinary DC trace and
point plugins retain their acquisition paths. The new plugin reuses the DC
trace's scan generators and corrected-voltage-to-TraceData construction, with
its own native acquisition, persistence, settings and resource lifecycle.

Evidence: [6220/6221 reference manual, revision C (October 2008)](
https://download.tek.com/manual/622x-901-01%20(C%20-%20Oct%202008)(Ref).pdf),
sections 5-37, 5-40 to 5-43, 5-49 to 5-50, and 6-16 to 6-18.
Custom Pulse Delta is a documented mode, with list delays defining cycle periods.
Read corrected voltages from the source buffer, not raw samples from the meter.
Buffer controls persist across reset, so every acquisition explicitly clears and
reconfigures its buffer and ASCII reading-only format.

The manual requires factory Trigger Link wiring and serial communication to the
2182A. Its native handshake and automatic integration setting do not document
the ordinary plugin's auxiliary-meter contract. Auxiliary support is deliberately
excluded; this is not a claim that electrically listening to a trigger is impossible.

The descriptive delay maximum is 11.966 ms; Table 5-4 prints 11.996 ms. Use the
more conservative descriptive limit. Validate delay shorter than width and leave
firmware-specific integration restrictions to instrument error checking at arm.
The existing generic `configure_pulsed_sweep()` helper is not used by this mode.

## Bench validation still needed

The integrated preview now uses the manual's mains-spaced sequence (section
5-43): the first low starts at zero, high at one mains period, and the second
low at two mains periods. Duty is width divided by configured cycle period;
post-high low time is cycle period minus one mains period minus width.
The 50/60 Hz selection is a persisted preview assumption, not a hardware setting
or measured readback. Initial trigger synchronisation and firmware overhead are
excluded. Short nominal cycles show an explanation instead of invented timing.

Follow-up validation: 230 affected tests passed on Python 3.14.7 / PyQt5
5.15.11, including 21 focused pulse-plugin tests. Ruff lint/format, the
production complexity check, error-level Pylint and the scoped docstring audit
passed. The themed integrated preview was rendered and visually inspected.
No acquisition commands or hardware timing settings changed in this follow-up.

- Use a known resistor and a short non-monotonic list including positive,
  negative and zero current; compare corrected voltages and resistance.
- Check pulse width, settling and mains-spaced cycles on an oscilloscope.
  Confirm requested short cycle periods against the actual hardware behaviour.
- Repeat acquisition without reconfiguration; check counts and no stale values.
- Exercise stop, missing serial/Trigger Link cables, compliance and disconnect.
  Confirm output returns to zero/off and subsequent reconfiguration succeeds.
- Exercise long lists and internal table build time on the installed firmware.

## Automated validation

Focused driver and plugin tests use NullTransport, fake drivers and managed
offscreen Qt pages. No connected hardware was used.

- Full offscreen suite: 4,192 passed, two skipped in 218.96 seconds on
  Python 3.14.7 / PyQt5 5.15.11. This preceded the final explicit output-off
  fallback, fixed-range selection check and bounded buffer-validation cases.
- Final affected driver, new/DC trace, shared trace and plugin-discovery
  regressions: 224 passed in 2.29 seconds after those refinements.
- Ruff lint, production McCabe limit 10, error-level Pylint and the scoped
  plugin-docstring audit passed. Installed entry-point loading was verified
  after refreshing the editable installation without dependencies.
- Rendered and inspected the themed Settings page. The live preview updates
  pulse width, settling region and baseline-measurement labels without
  evaluating expressions in the GUI.
- Sphinx HTML generation completed and the new page has no scoped warnings.
  Existing documentation issues remain elsewhere, including missing
  `core.sequence`/`core.runner` API targets and unresolved `range` references
  in temperature-controller docstrings. This was not a warning-free build.
- No legacy tests were moved or removed. Other Qt bindings and hosted CI were
  not run.

Commands used the project Conda environment with offscreen Qt and Windows fonts:

```powershell
conda run -n stoner_measurement pytest -q --tb=short -p no:cacheprovider `
    --basetemp=.pytest-runtime/pulse-delta-full
conda run -n stoner_measurement pytest `
    tests/unit/instruments/drivers/test_keithley_6221.py `
    tests/unit/instruments/drivers/test_keithley_6221_pulse_delta.py `
    tests/unit/plugins/trace/test_k6221_pulse_delta.py `
    tests/test_k6221_2182a_plugin.py `
    tests/unit/plugins/trace/test_k6221_2182a_measurement_settings.py `
    tests/unit/plugins/trace/test_k6221_2182a_secondary.py `
    tests/unit/plugins/trace/test_trace_plugin.py tests/test_plugin_manager.py `
    -q --tb=short -p no:cacheprovider --basetemp=.pytest-runtime/pulse-delta-final
```

## 2026-11-05: timing validation feedback

- Rechecked reference manual section 5-40 (PDF page 162): pulse width is
  50 us to 12 ms; source delay is 16 us to 11.966 ms. The 25 ms width
  rejection is correct. A 5 ms delay requires a pulse wider than 5 ms.
- Settings now show hardware limits and persistent accessible timing feedback
  above the preview. Numeric preview validation reuses the driver validator.
  Expression previews are labelled unavailable rather than invalid.
- Focused pulse-plugin and pulse-driver tests: 54 passed on offscreen PyQt5.
  No hardware commands or limits changed.
