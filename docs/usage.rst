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

Hardware trace-plugin lifecycle
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Hardware-backed trace plugins should follow a consistent runtime lifecycle:

1. ``connect()`` opens the instrument sessions and verifies identity, but does
   not enable persistent outputs or start a sweep.
2. ``configure()`` pushes the complete acquisition configuration to the
   hardware. If the instrument has a persistent source or output, this step
   should leave it enabled so the plugin is ready to measure immediately.
3. ``measure()`` or ``execute()`` acquires a fresh trace using the existing
   configured state. Successful measurements should not disable the output or
   tear down configuration needed for the next measurement.
4. ``disconnect()`` returns the hardware to a safe idle state, including
   disabling any persistent outputs before closing the connections.

This is the expected model for trace plugins such as the Keithley 6221/2182A,
Keithley 2400, and Keithley 6221/SR830 integrations. It keeps repeated
measurements fast, makes output ownership predictable, and ensures shutdown
logic lives in one place.

Trace data structure
~~~~~~~~~~~~~~~~~~~~

All tabular measurement results use
:class:`~stoner_measurement.core.TraceData`.  This includes objects
returned by :meth:`~stoner_measurement.plugins.trace.TracePlugin.measure` and
data accumulated by state scan/sweep plugins when ``collect_data`` is enabled.
Each object is backed by a :class:`pandas.DataFrame`: the independent variable
(*x*) is the index, and one or more dependent or auxiliary variables are
columns annotated with role strings from the ``COLUMN_ROLE_*`` constants.

One ``TraceData`` therefore represents one shared-x table.  The mapping
returned by ``measure()`` is only for genuinely separate trace tables, which
may have different x arrays.  Multiple simultaneously acquired outputs on the
same scan belong in columns of one ``TraceData``.

For a state scan or sweep, *x* is the controlled physical state by default. A
selected readback output may instead be assigned the explicit ``x`` role when
the measured value reached is more appropriate than the commanded set-point;
the commanded value is then retained in an auxiliary ``state`` column. The
``iteration`` and ``stage`` bookkeeping values are also retained as auxiliary
columns, alongside the selected scalar outputs. The resulting table is
published directly in the trace catalogue as ``"{instance_name}.data"``, so
plotting, transforms, and saving do not require an intermediate data-to-trace
conversion step. The Save command likewise has one trace selection path for
both instrument traces and collected scan/sweep tables; incremental saving
remains available for repeated saves as a table grows.

The independent variable is an ordinary DataFrame column carrying the
``COLUMN_ROLE_X`` role. The DataFrame index is always a simple integer row
index, so every channel can be enumerated, selected, copied, and saved through
the same column-based path.

.. code-block:: python

    from stoner_measurement.core import (
        TraceData,
        COLUMN_ROLE_X,
        COLUMN_ROLE_Y,
        COLUMN_ROLE_Z,
        COLUMN_ROLE_E,
    )
    import numpy as np
    import pandas as pd

    # Single-column convenience constructor
    td = TraceData.from_xy(
        np.array([0.0, 1.0, 2.0]),
        np.array([0.0, 1.0, 4.0]),
    )

    # Multi-column trace, including its uncertainty column
    df = pd.DataFrame(
        {
            "x": [0.0, 1.0, 2.0],
            "voltage": [0.0, 1.0, 4.0],
            "current": [0.0, 0.5, 2.0],
            "voltage_error": [0.01, 0.01, 0.02],
        }
    )
    td_multi = TraceData(
        df,
        column_roles={
            "x": COLUMN_ROLE_X,
            "voltage": COLUMN_ROLE_Y,
            "current": COLUMN_ROLE_Z,
            "voltage_error": COLUMN_ROLE_E,
        },
        names={"x": "Time", "voltage": "Voltage", "current": "Current"},
        units={"x": "s", "voltage": "V", "current": "A"},
    )

    # Query all columns with a particular role
    y_cols = td_multi.get_columns_by_role(COLUMN_ROLE_Y)

The ``td.x``, ``td.y``, ``td.d``, and ``td.e`` properties provide convenient
views of the first column with the corresponding role.  The DataFrame remains
the canonical representation.

Selecting which column to plot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In the *Plot Trace* command's configuration widget a **Column** dropdown
selects which DataFrame column provides the *y* data for the plot.  When left
on ``(default)`` the first ``COLUMN_ROLE_Y``-role column is used.  Advanced
mode still accepts arbitrary NumPy expressions.

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

The default implementation places ``config_widget()`` on a concise
``Settings`` tab. Tab titles should describe the page's role without
repeating the plugin name, because the selected sequence step already identifies
the plugin. Override ``config_tabs()`` directly when a plugin needs **more
than one tab** or a custom role title.

.. code-block:: python

    def config_tabs(self, parent=None):
        settings = self.config_widget(parent=parent)
        about    = QLabel("My plugin v1.0", parent)
        return [
            ("Settings", settings),
            ("About",    about),
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
