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

Choose the appropriate base class for your plugin type and register it via
the ``stoner_measurement.plugins`` entry-point group in your package's
``pyproject.toml``:

.. code-block:: toml

    [project.entry-points."stoner_measurement.plugins"]
    my_instrument = "my_package.my_plugin:MyPlugin"

**Measurement trace plugin** — subclass
:class:`~stoner_measurement.plugins.trace.TracePlugin`:

* Required: :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name`
  and :meth:`~stoner_measurement.plugins.trace.TracePlugin.execute` (a
  generator that yields ``(x, y)`` tuples for each measured point).
* Optionally override :meth:`~stoner_measurement.plugins.trace.TracePlugin.connect`,
  :meth:`~stoner_measurement.plugins.trace.TracePlugin.configure`, and
  :meth:`~stoner_measurement.plugins.trace.TracePlugin.disconnect` to manage
  hardware connections.

**State-control plugin** — subclass
:class:`~stoner_measurement.plugins.state_control.StateControlPlugin`:

* Required: :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name`,
  :attr:`~stoner_measurement.plugins.state_control.StateControlPlugin.state_name`,
  :attr:`~stoner_measurement.plugins.state_control.StateControlPlugin.units`,
  :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.set_state`,
  :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.get_state`,
  and :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.is_at_target`.
* The sequence engine drives this plugin over a scan defined by
  :attr:`~stoner_measurement.plugins.state_control.StateControlPlugin.scan_generator`.
  Other steps can be nested beneath it in the sequence tree.

**Monitor plugin** — subclass
:class:`~stoner_measurement.plugins.monitor.MonitorPlugin`:

* Required: :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name`,
  :attr:`~stoner_measurement.plugins.monitor.MonitorPlugin.quantity_names`,
  :attr:`~stoner_measurement.plugins.monitor.MonitorPlugin.units`, and
  :meth:`~stoner_measurement.plugins.monitor.MonitorPlugin.read`.

**Transform plugin** — subclass
:class:`~stoner_measurement.plugins.transform.TransformPlugin`:

* Required: :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name`,
  :attr:`~stoner_measurement.plugins.transform.TransformPlugin.required_inputs`,
  :attr:`~stoner_measurement.plugins.transform.TransformPlugin.output_names`,
  and :meth:`~stoner_measurement.plugins.transform.TransformPlugin.transform`.

All :class:`~stoner_measurement.plugins.trace.TracePlugin` and
:class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
subclasses can optionally provide custom configuration tabs by overriding:

* :meth:`~stoner_measurement.plugins.trace.TracePlugin._plugin_config_tabs` —
  return a :class:`~PyQt6.QtWidgets.QWidget` that appears as the *Settings*
  configuration tab.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin._about_html` — return
  an HTML string that appears as an *About* configuration tab.
