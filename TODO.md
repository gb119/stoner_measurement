# Notes of features/bugs to work on

1. Log window - regular expression to filter on for messages - DONE
2. Magnet control panel and engine - need switch heater to understand transition states - DONE NEEDS TESTING
3. Lakeshroe 625 - check that it can read the field-current constant from the supply and limits. - DONE NEEDS TESTING
4. Keithley 6221-lockins: separate entries to specify multiple channels to read per lockin, - DONE but needs fixing
   remove current calcualtion - DONE NEEDS TESTING
5. QtConsole in Dark Mode tooltips - Needs more work
/6. Default sequence could live in conf dir and not require a setting - DONE
6. Better dark mode icons for panels - DONE
7. Restore docstring discussion of attributes for plugins - Partially DONE
8. Hints on templating of Save Path in Save plugin - may be a dialog box riggered from context menu like the
   LabVIEW code had.
9. Implement K24x0 trace and scan plugins. - DONE
10. ITC503 driver temperature conversion table. - DONE NEEDS HARDWARE TESTING
11. Tmperayrter control panel should not pick up private driver classes. - DONE
12. Implement temperature stability as a table (Below T, tolerance, toleramce_sensor, time, stability_rate,
    stability_sensor, hold_off_time)
13. Related, make stability critiera use specific sensors.
14. For all engines, add engine status (polling, not polling) on status bbar right hand side.
15. For all planels, add a Hide button in bottom right corner.
16. Re work motor controller shortest distance algorithm.
