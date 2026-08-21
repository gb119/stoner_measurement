# Notes of features/bugs to work on

## Complete

1. Log window - regular expression to filter on for messages - DONE
2. Default sequence could live in conf dir and not require a setting - DONE
3. Better dark mode icons for panels - DONE
4. Tmperayrter control panel should not pick up private driver classes. - DONE
5. For all planels, add a Hide button in bottom right corner. - DONE
on status bbar right hand side.
6. Re work motor controller shortest distance algorithm. DONE
7. For all engines, add engine status (polling, not polling) DONE
8. 6221-2182 IV calculates power (V*I) and resistance (V/I) as output channels in the trace and reports
   averages for voltage, resistance, and power when config panel options are selected. DONE
9. K24x0 trace plugin reports averages for all buffered trace columns, including non-primary channels. DONE
10. Magnet control panel now persists and restores config-tab values (targets, ramp rates, magnet constant, and limits)
    through YAML-backed engine configuration. DONE
11. In KJeithley65221-multilockin trace plugin, selected lockins no longer colour checkbox backgrounds with the
    highlight colour. DONE
12. Plot colour picker dialogs now use the non-native picker path to avoid colouring unrelated dialog elements. DONE
13. Sequence step instance names now avoid Python reserved words and builtins, reusing the existing collision
    detection path so generated code does not emit invalid syntax. DONE
14. Base plugins now support an optional comment field, and the sequence list shows it after the instance/plugin
    label when present. Auto-inserted `If` children for state scan/sweep steps use the comment `meas_flag is set`
    to explain why they were added. DONE
15. Magnet controller panel should show the actual and target rates.
16. Lakeshore 625 - driver reads FLDS?/LIMIT? values from instrument for field-current constant and limits. DONE
17. Lakeshore 625 driver uses OPST? instead of invalid RDGST? and maps the documented operation-status bits. DONE
18. Right clicking on the status indicators for the engines in the status bar should allow the engines to be stopped,
   restarted, disconnected, or reconnected.
19. Magnet control panel and engine - need switch heater to understand transition states - DONE
20. Lakeshroe 625 - check that it can read the field-current constant from the supply and limits. - DONE
21. Keithley 6221-lockins: separate entries to specify multiple channels to read per lockin, - DONE
   remove current calcualtion - DONE
22. Implement temperature stability as a table (Below T, tolerance, toleramce_sensor, time, stability_rate,
    stability_sensor, hold_off_time) - DONE
23. Related, make stability critiera use specific sensors. DONE
24. Engines auto-connect using persisted settings when a plugin requests connected hardware, with the attempt logged.
    DONE - Tested with hardware
25. The log window supports regular-expression filtering for fine-grained message and communications filtering. DONE
26. Plot widget supports programmatic trace renaming without losing data, axes, style, errors, or visibility.
    Plot-points ses this API when a configured series label changes. DONE
27. Monitor and Filter sweep trigger highlights are cleared on the next evaluation when no condition triggers a
    measurement. DONE
28. Files chosen for custom-toolbar buttons in Preferences are installed into the correct user configuration
    directories: icons into `resources` and sequences into `sequences`. Files already elsewhere in the managed
    configuration tree are moved; files selected from outside it are copied. DONE
29. Edit Function Scan can optionally generate a call to the owning scan plugin's `configure()` method immediately
    after applying the edited function-scan settings. DONE
30. Curve Fit evaluates user `p0` functions and initial-parameter traces through a reusable logging context that
    reports warnings at INFO and exceptions at ERROR through the caller-supplied application logger. DONE
31. Curve Fit exposes its current `fit` and optional `p0` functions as callable instance attributes, and exposes the
    latest best-fit parameter values by name when they do not clash with existing plugin attributes. DONE
32. Conditional `Break If` and `Continue If` commands generate guarded loop-control statements. Their default
    instance names are `break_if` and `continue_if`, and generic sequence-position validation prevents them being
    inserted outside a state scan or sweep loop. DONE
33. X Offset Removal now copies the complete selected source trace and replaces only the selected target axis or
    data column with `x - dx`. The target selector uses the trace catalogue's channel names and units, defaults to
    the trace x channel, and includes every stored column, while the source trace remains unchanged. DONE
34. Trace-producing transforms now keep source-trace and target-column controls active in Advanced Mode. Normal mode
    uses the source trace's default x/y inputs; Advanced Mode may source x/y arrays from anywhere while retaining the
    selected trace context. Window and Savitzky-Golay filters copy the complete trace and replace only the selected
    column, while X Offset replaces only its selected target axis or column. DONE
35. Keithley 6221 instruments default to the GPIB resource ``GPIB0::13::INSTR``. DONE

## Done, but needs testing

1. Implement K24x0 trace and scan plugins. - DONE - Needs testing with hardware
2. ITC503 driver temperature conversion table. - DONE NEEDS HARDWARE TESTING
3. Lakeshore 625 command errors are detected through STB/`*ESR?`; hardware, operational, and PSH faults are checked
   through `ERST?`, logged as critical, and abort operation. - DONE - Needs hardware testing
4. Lakeshore 625 uses the supported `RATE`/`RATE?` command in A/s and converts the public current/field ramp-rate
   interfaces to per-minute units. - DONE - Needs hardware testing
5. Oxford IPS120 reads safe-current limits from R21/R22. - DONE - Needs hardware testing
6. Oxford IPS120 persistent-switch heater controls are enabled for stable heater states when the supply is at a safe
   current. - DONE - Needs hardware testing
7. Shared trace-plugin scan configuration pages, including every scan-generator type, pack controls from the top and
    leave surplus vertical space only at the bottom. - DONE - Needs visual testing
8. The 6221-multiple-SR830 sensitivity selector now starts with an explicit Auto option. Auto configuration runs
    `AGAN`, waits for IFC completion, reads back the selected sensitivity, and aborts if `LIAS?` reports overload.
    - DONE - Needs hardware testing
9. Instrument address widgets force dark foreground text on connecting, connected, and error status backgrounds for
    dark-mode contrast. - DONE - Needs visual testing
10. Plot-points automatically updates an unedited plot label when its Y value changes, while preserving manually edited
    labels. - DONE
11. 6221-multiple-SR830 resistance-derived channel averages are exported through the values catalogue. - DONE
12. Save metadata is limited to plugins used by sequence steps and includes the outputs catalogue. - DONE
13. Trace-plugin scan pages include a Transpose option below the channel-statistics option. It exchanges the X and
    primary Y roles in measured traces. - DONE - Needs testing
14. Double-clicking an available plugin inserts it relative to the selected sequence step: at the end when there is no
    selection, inside a selected container, or after a selected leaf at the same nesting level. - DONE - Needs testing

## Partially done, needs more work

1. QtConsole in Dark Mode tooltips - Needs more work
2. Restore docstring discussion of attributes for plugins - Partially DONE
3. Hints on templating of Save Path in Save plugin - may be a dialog box riggered from context menu like the
   LabVIEW code had.

## New Ideas

1. The engines should log reasons for disconnecting as info level, or error level if not the result of user request.
   In the latter case they should atempt to auto-reconnect. If reconnection fails 5 times without a successful
   connection then engine should enter a failed state and require the user to reconnect via the panel. The failed
   state needs to be logged as an error and reflected in the status-bar indicators.
2. Implement the binary data formats for the Keithley 2182A buffer reads to try for faster 6221-2182 loops.

## Bugs

1. Check the SRQ timeout calculations - seems to not quite get it right for longer source delays in the 6221-2182
   trace plugin.
