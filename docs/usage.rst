Usage
=====

Starting the application
------------------------

After installation, launch the application from the command line:

.. code-block:: bash

    stoner-measurement

Or from Python:

.. code-block:: python

    from stoner_measurement.main import main
    main()

Application layout
------------------

The main window is split into three panels:

* **Left panel (25 %)** — Instrument / plugin list and sequence builder.
  Drag instruments into the sequence list to build a measurement sequence.
* **Central panel (50 %)** — Live PyQtGraph plotting area.  Data points
  produced by each sequence step are plotted here in real time.
* **Right panel (25 %)** — Tabbed configuration area.  Each loaded plugin
  contributes a tab with its own configuration controls.

Building and running a sequence
--------------------------------

1. Select an instrument in the **left panel** and click *Add Step*.
2. Repeat for each step you need.
3. Configure each step via the corresponding tab in the **right panel**.
4. Click *Run* to start the sequence.

Writing a plugin
----------------

Subclass :class:`~stoner_measurement.plugins.trace.TracePlugin` (for
measurement traces) and register it via the ``stoner_measurement.plugins``
entry-point group in your package's ``pyproject.toml``:

.. code-block:: toml

    [project.entry-points."stoner_measurement.plugins"]
    my_instrument = "my_package.my_plugin:MyPlugin"

Implement at minimum:

* :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name` — unique
  string identifier.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin.execute` — generator
  that yields ``(x, y)`` data tuples for each measured scan point.

The sequence engine calls :meth:`~stoner_measurement.plugins.trace.TracePlugin.measure`
once per step, which collects the complete multipoint trace and returns it as a
list of ``(channel, x, y)`` tuples.

Optionally override:

* :meth:`~stoner_measurement.plugins.trace.TracePlugin._plugin_config_tabs` —
  return a :class:`~PyQt6.QtWidgets.QWidget` that appears as the *Settings*
  configuration tab.
