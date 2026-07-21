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

## Done, but needs testing

1. Magnet control panel and engine - need switch heater to understand transition states - DONE NEEDS TESTING
2. Lakeshroe 625 - check that it can read the field-current constant from the supply and limits. - DONE NEEDS TESTING
3. Keithley 6221-lockins: separate entries to specify multiple channels to read per lockin, - DONE but needs fixing
   remove current calcualtion - DONE NEEDS TESTING
4. Implement K24x0 trace and scan plugins. - DONE - Needs testing with hardware
5. ITC503 driver temperature conversion table. - DONE NEEDS HARDWARE TESTING
6. Implement temperature stability as a table (Below T, tolerance, toleramce_sensor, time, stability_rate,
    stability_sensor, hold_off_time) - DONE NEEDS TESTING
7. Related, make stability critiera use specific sensors. DONE NEEDS TESTING

## Partially done, needs more work

1. QtConsole in Dark Mode tooltips - Needs more work
2. Restore docstring discussion of attributes for plugins - Partially DONE
3. Hints on templating of Save Path in Save plugin - may be a dialog box riggered from context menu like the
   LabVIEW code had.

## New Ideas

1. The engines should attempt to auto-connect with persisted settings when a plugin requests something that requires
   a connection. This should be logged as an info warning.
2. The engines should log reasons for disconnecting as info level, or error level if not the result of user request.
   In the latter case they should atempt to auto-reconnect. If reconnection fails 5 times without a successful
   connection then engine should enter a failed state and require the user to reconnect via the panel. The failed
   state needs to be logged as an error.
3. The log window could do with a regexp filter as well that would allow finer-grained filtering of log entries of
   interest, such as comms traffic from a sepcific address or even a specific command. The failed state should be
   reflected in the statys bar indicators.
4. Right clicking on the status indicators for the engines in the status bar should allow the engines to be stopped,
   restarted, disconnected, or reconnected.

## Bugs

2. Lakeshore 625 driver/transport/protocol doesn't seem to check STB for errors or deal with error situations.
3. Lakeshore625 is sending a RATEF and RATEI (and query) commands - but only RATE[?] is supported that works with the ramp rate in A/s. 

