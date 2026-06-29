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
8. Lakeshore 625 - driver reads FLDS?/LIMIT? values from instrument for field-current constant and limits. DONE NEEDS HARDWARE TESTING
9. Lakeshore 625 driver uses OPST? instead of invalid RDGST? and maps the documented operation-status bits. DONE NEEDS HARDWARE TESTING

## Partially done, needs more work

1. QtConsole in Dark Mode tooltips - Needs more work
2. Restore docstring discussion of attributes for plugins - Partially DONE
3. Hints on templating of Save Path in Save plugin - may be a dialog box riggered from context menu like the
   LabVIEW code had.


## New IDeas

1. Make sure instance names are not reserved python names or builtins.
2. Add a comment field to base plugin and then have the sequence list show this if not empty after the plugin name
   and instance.

## Bugs

1. Magnet control panel - not persisting all settings from the config tab to yaml file - or else not restoring
   settings when panel opened.
2. Magnet controller panel should show the actual and target rates.
3. Lakeshore 625 driver/transport/protocol doesn't seem to check STB for errors or deal with error situations.
4. In KJeithley65221-multilockin trace plugin, when selected the lockins colour the background of checkbox fields in
   the highlight colour.
5. The colour picker dialog for plotting is colouring some lements with the selected colour (.e.g buttons, title bar
   amongst others.
6. Temperature controller engine should not run poll if the connection has gone bad. If the connection disconnects for
   any reason other than shutdown or user pressing disconnect, this shopuld get logged as an error.
