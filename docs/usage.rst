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

All measurement plugins inherit from
:class:`~stoner_measurement.plugins.base_plugin.BasePlugin`.  Choose the
appropriate subclass for your plugin type and register it via the
``stoner_measurement.plugins`` entry-point group in your package's
``pyproject.toml``:

.. code-block:: toml

    [project.entry-points."stoner_measurement.plugins"]
    my_instrument = "my_package.my_plugin:MyPlugin"

Plugin types
~~~~~~~~~~~~

**Measurement trace plugin** — subclass
:class:`~stoner_measurement.plugins.trace.TracePlugin`:

* Required: :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name`
  and :meth:`~stoner_measurement.plugins.trace.TracePlugin.execute` — a
  generator that yields ``(x, y)`` tuples for each measured point.
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

Minimal example
~~~~~~~~~~~~~~~

The following shows the minimum required implementation for a trace plugin:

.. code-block:: python

    from stoner_measurement.plugins.trace import TracePlugin

    class ThermometerPlugin(TracePlugin):
        @property
        def name(self):
            return "Thermometer"

        def execute(self, parameters):
            for reading in self._hardware.read(parameters.get("samples", 10)):
                yield reading.time, reading.temperature

Optional UI integration
~~~~~~~~~~~~~~~~~~~~~~~

Plugins can hook into the main window UI by overriding any of the following
methods.

``config_tabs(parent=None) → list[tuple[str, QWidget]]``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Returns a list of ``(tab_title, widget)`` pairs.  Each pair becomes one tab
in the right-hand **configuration panel**.

The default implementation wraps ``config_widget()`` in a single-element
list using ``name`` as the tab title.  Override ``config_tabs()`` directly
when a plugin needs **more than one tab** or a custom tab title.

.. code-block:: python

    def config_tabs(self, parent=None):
        settings = self.config_widget(parent=parent)
        about    = QLabel("My plugin v1.0", parent)
        return [
            ("MyPlugin \u2013 Settings", settings),
            ("MyPlugin \u2013 About",    about),
        ]

``config_widget(parent=None) → QWidget``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Returns a single ``QWidget``.  Used by the default ``config_tabs()``
implementation — override this when a single configuration tab is
sufficient.

``monitor_widget(parent=None) → QWidget | None``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Returns an optional live-status widget shown in the **left dock panel**
*Monitoring* section whilst the plugin is registered.  Return ``None`` (the
default) if no monitoring widget is needed.

.. code-block:: python

    def monitor_widget(self, parent=None):
        self._status_label = QLabel("Idle", parent)
        return self._status_label

All :class:`~stoner_measurement.plugins.trace.TracePlugin` and
:class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
subclasses can also optionally provide custom configuration tabs by
overriding:

* :meth:`~stoner_measurement.plugins.trace.TracePlugin._plugin_config_tabs` —
  return a :class:`~PyQt6.QtWidgets.QWidget` that appears as the *Settings*
  configuration tab.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin._about_html` — return
  an HTML string that appears as an *About* configuration tab.
