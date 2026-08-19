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
18.Right clicking on the status indicators for the engines in the status bar should allow the engines to be stopped,
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

## Done, but needs testing

4. Implement K24x0 trace and scan plugins. - DONE - Needs testing with hardware
5. ITC503 driver temperature conversion table. - DONE NEEDS HARDWARE TESTING
6. Lakeshore 625 command errors are detected through STB/`*ESR?`; hardware, operational, and PSH faults are checked
   through `ERST?`, logged as critical, and abort operation. - DONE - Needs hardware testing
7. Lakeshore 625 uses the supported `RATE`/`RATE?` command in A/s and converts the public current/field ramp-rate
   interfaces to per-minute units. - DONE - Needs hardware testing
8. Oxford IPS120 reads safe-current limits from R21/R22. - DONE - Needs hardware testing
9. Oxford IPS120 persistent-switch heater controls are enabled for stable heater states when the supply is at a safe
   current. - DONE - Needs hardware testing
10. Shared trace-plugin scan configuration pages, including every scan-generator type, pack controls from the top and
    leave surplus vertical space only at the bottom. - DONE - Needs visual testing
11. The 6221-multiple-SR830 sensitivity selector now starts with an explicit Auto option. Auto configuration runs
    `AGAN`, waits for IFC completion, reads back the selected sensitivity, and aborts if `LIAS?` reports overload.
    - DONE - Needs hardware testing
12. Instrument address widgets force dark foreground text on connecting, connected, and error status backgrounds for
    dark-mode contrast. - DONE - Needs visual testing
13. Plot-points automatically updates an unedited plot label when its Y value changes, while preserving manually edited
    labels. - DONE
14. 6221-multiple-SR830 resistance-derived channel averages are exported through the values catalogue. - DONE
15. Save metadata is limited to plugins used by sequence steps and includes the outputs catalogue. - DONE

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
3. Implement `break` and `continue` plugin commands (but make them have a condaitional field so that
   they produce code like:
       ```
	   if condition_expression:
	       break/continue
	    ```
	Would also need to have the ability to refuse to add not in a sub-loop (so we need
	a hook that can be called on BasePlugin that is passed the sequence step list it
	is being passed to and can raise some sort of Exception that the UI can display.)

## Bugs

1.	In a Monitor and Filter sweep, the plugin highlights the test that caused the measure flag
    to set True, but this stays highligted until the next measure true is set. If no tests for The
	next measurement pass, the highlights shpuld be cleared.
2. I added a custom toolbar, but the icon field doesn't seem to be working. JSON is:
	```
	buttons:
	- name: R(T)
	  sequence: R(T).json
      image: R(T).png
      tooltip: Config for doing Resistance vs Temperature
	```
	The png file is next to the sequence file and the sequence is loading correctly. If the button is
	supposed to be somehwere else, then when I select the button file in the UI, it should be
	moved to the correct location.
3.	Check the SRQ timeout calcualtions - seems to not quite get it right for longer source delays in 6221-2182 trace plugin
4.  Remove voltage offset seems to be changing things other than just the x column.
5.  Edit Function Scan plugin  should have an option to reconfigure the scan plugin after editing - to generated
    the code `<trace.configure()`.