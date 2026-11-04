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

.. figure:: _static/screenshots/workspace.png
   :alt: Dark-mode workspace with available commands and a nested sequence on the left, a simulated I-V plot in the centre, and trace scan settings on the right.
   :width: 100%

   A completed hardware-free measurement. Select a sequence step to display
   its configuration on the right; drag the panel dividers to adjust the layout.

The illustrations below use the application's dark theme. Choose the theme
in **Edit → Preferences…**. The same controls are available in the light theme.

Mouse control and data markers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Click an axis to toggle whether mouse panning and zooming affect it. Active
axes have a highlighted, slightly thicker spine; left and bottom start active.
Each axis can be selected independently, including multiple axes on the same
side. Selected axes retain their own scales and ranges while moving together.
With all axes inactive, mouse gestures leave the plot ranges unchanged.

The pointer readout and automatic data-marker labels show only active axes.
Right-click the plot and choose **Add Data Marker** to pin a marker to the
first active x axis and first active y axis (default axes first, followed by
additional axes in creation order). Marker placement requires at least one
active axis in each direction. Existing markers retain their original data
coordinates and axis pair when selection changes; their automatic labels
update to show the currently active coordinates. Explicit marker labels are
preserved. Removing an axis also removes markers anchored to it.

.. figure:: _static/screenshots/plot-marker.png
   :alt: Simulated current-voltage trace with active blue bottom and left axes, a trace-formatting table, and a circular data marker with its coordinate label.
   :width: 100%

   Right-click a plot position and choose **Add Data Marker** to label it.
   Here the configuration panel is collapsed to give the plot more room.
   The table above the plot controls trace visibility, colour, line style,
   and axis assignment.

Building and running a sequence
--------------------------------

1. Select an instrument in the **left panel** and click *Add Step*.
2. Repeat for each step you need.
3. Configure each step via the corresponding tab in the **right panel**.
4. Click *Run* to start the sequence.

Try a measurement without hardware
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Download :download:`the simulated I-V sequence <examples/simulated_iv.json>`
and open it with **File → Open Sequence…** while on the **Measurement** tab.
It uses the built-in **Dummy** trace plugin, which simulates a Josephson
junction without connecting to an instrument. The ``measurement`` container
runs its two children in order: ``iv_trace`` acquires the data, then
``plot_iv`` displays it.

Select ``details`` and fill in **User**, **Sample**, and **Project** on its
**General** tab. These required fields identify the measurement; an empty
field prevents the sequence from continuing. The example supplies demonstration
values, which you can replace with your own.

.. figure:: _static/screenshots/measurement-details.png
   :alt: Details General tab with User set to Demo user, Sample to Simulated Josephson junction, Project to Getting started, and a short note.
   :width: 420px

   Complete the Details step before running a sequence that includes it.

Select ``iv_trace``. Its **Scan** tab defines the current values to measure.
This example uses a sine waveform with amplitude ``5e-6`` A, 201 points,
and one period. The preview shows the order of the current values, rather
than the measured voltage.

.. figure:: _static/screenshots/trace-scan.png
   :alt: Dummy trace Scan tab showing the Function Scan Generator, a sine waveform, amplitude 5e-6, 201 points, one period, and its waveform preview.
   :width: 480px

   Scan controls and preview for the simulated current sweep.

On the **Settings** tab, set the critical current to ``1e-6`` A and the
normal resistance to ``100`` ohms. The voltage noise and voltage offset
scale are both zero in this example.

.. figure:: _static/screenshots/trace-settings.png
   :alt: Dummy trace Settings tab with critical current 1e-6 A, normal resistance 100 ohms, zero voltage noise and offset scale, and thermal noise temperature 1 K.
   :width: 480px

   Model settings determine the simulated junction's response.

Select ``plot_iv`` and check that **Plot form** is **XY** and **Trace** is
``iv_trace:Dummy``. Leaving **Column** on **(default)** uses the trace's
default dependent columns; advanced expressions are unnecessary for this
example.

.. figure:: _static/screenshots/plot-trace.png
   :alt: Plot Trace configuration selecting XY form, the iv_trace:Dummy trace, the default column, bottom and left axes, and line width 2.
   :width: 460px

   The Plot Trace command displays the data acquired by the preceding step.

Click **Run** or press :kbd:`F5`. After the status returns to **Idle**, the
central plot shows the simulated I-V characteristic, as in the workspace
illustration above. Use **Pause** (:kbd:`F7`) and **Stop** (:kbd:`F6`) for
longer sequences. Save the configured sequence with :kbd:`Ctrl+S` to reuse it.

.. _running-selected-steps:

Running selected steps
~~~~~~~~~~~~~~~~~~~~~~

To check part of a measurement, select one or more steps in the sequence
tree, right-click the selection and choose **Run Selection...**, or press
:kbd:`Shift+F5`. The selected steps run in sequence order as a one-off script.
Selecting a container such as an if, scan or sweep includes its complete
sub-sequence. Children of a
selected ancestor are included only once. Selecting a child on its own runs
that child without its enclosing container or unselected siblings.

The script uses the usual connection, configuration and cleanup behaviour.
Include any setup steps required by the selection. Pause and Stop work as
they do for a full sequence.

On successful completion, the temporary script tab is discarded without
saving. If execution fails or is stopped, the script remains in the Script
Editor for inspection. A temporary script that you edit or save is also kept.
The source sequence and existing script tabs are preserved.

.. figure:: _static/screenshots/run-selection.png
   :alt: The measurement container is selected above its iv_trace and plot_iv children, with Run Selection highlighted in the context menu and Shift+F5 shown alongside it.
   :width: 460px

   Selecting ``measurement`` runs both acquisition and plotting. The Details
   step is outside this selection, so it is not executed by this one-off run.

Inspecting the generated script
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Click **Generate Code** on the toolbar or in the **Sequence** menu, then
open the **Script Editor** tab on the left. Code generation from the
Measurement tab updates the editor in the background. The script contains
the configured steps, including the nested acquisition and plotting actions
and the cleanup that disconnects the trace plugin.

.. figure:: _static/screenshots/generated-script.png
   :alt: Script Editor showing Details values, a nested measurement function that acquires iv_trace and calls plot_iv, and a finally block that disconnects iv_trace.
   :width: 100%

   The action block at the end of the generated example script. The earlier
   part of the script constructs and configures the plugins.

On the Script Editor tab, :kbd:`F5` runs the current script. You can edit
and save it independently of the sequence. The console below the editor
shows execution messages and supports interactive inspection of results.

More complete measurement workflows
------------------------------------

See :doc:`data_workflows` for an illustrated scan/sweep workflow covering
output selection and column roles, filtering, curve fitting, Plot Points,
Plot Trace, complete-trace saving, and incremental saving of a growing table.
It includes a downloadable hardware-free example based on a predefined
toolbar sequence.

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
