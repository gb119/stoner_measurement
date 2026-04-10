Third-party plugin packages
===========================

Any Python package can contribute new plugins — including new sequence-engine
commands — to the Stoner Measurement application without modifying the
application's source code or configuration files.  The mechanism is the
standard Python *entry-points* system; once a third-party package is installed
in the same Python environment as the application, its plugins are
automatically discovered at start-up.

.. contents:: On this page
   :local:
   :depth: 2

How plugin discovery works
--------------------------

When the application starts it creates a
:class:`~stoner_measurement.core.plugin_manager.PluginManager` and calls its
:meth:`~stoner_measurement.core.plugin_manager.PluginManager.discover` method.
That method calls :func:`importlib.metadata.entry_points` with the group name
``stoner_measurement.plugins`` and instantiates every class that is
registered under that group.

The result is that **any installed package** that declares one or more
entry-points in the ``stoner_measurement.plugins`` group will have its plugin
classes loaded and made available in the application.  No changes to the
application's own ``pyproject.toml``, source code, or configuration files
are required.

Choosing a plugin base class
-----------------------------

All plugins must ultimately subclass
:class:`~stoner_measurement.plugins.base_plugin.BasePlugin`.  In practice you
will subclass one of the six specialised base classes:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Base class
     - Use when …
   * - :class:`~stoner_measurement.plugins.command.CommandPlugin`
     - The step performs a single action (e.g. save data, send a notification,
       trigger an external event) and has no instrument lifecycle.
   * - :class:`~stoner_measurement.plugins.trace.TracePlugin`
     - The step acquires ``(x, y)`` data traces from an instrument.
   * - :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
     - The step drives hardware to a series of set-points (field, temperature,
       motor position, etc.) and may contain nested sub-steps.
   * - :class:`~stoner_measurement.plugins.monitor.MonitorPlugin`
     - The step passively records auxiliary quantities by polling hardware at a
       configurable interval.
   * - :class:`~stoner_measurement.plugins.transform.TransformPlugin`
     - The step performs a pure-computation transform or reduction on already
       collected data without accessing hardware.
   * - :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
     - The step acts as a generic container (branch node) in the sequence tree,
       holding nested sub-steps.

The remainder of this page focuses on
:class:`~stoner_measurement.plugins.command.CommandPlugin` because it is the
most common choice for new sequence-engine commands that do not require a
dedicated hardware instrument.

Writing a CommandPlugin
------------------------

A :class:`~stoner_measurement.plugins.command.CommandPlugin` must implement
two things:

1. The :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name`
   property — a unique human-readable string shown in the sequence builder.
2. The :meth:`~stoner_measurement.plugins.command.CommandPlugin.execute`
   method — the action to perform when the sequence step is reached.

Inside :meth:`execute` you have access to:

* :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.engine_namespace`
  — the full sequence engine namespace (a ``dict``).  It contains all
  registered plugin instances, ``np``/``numpy`` and every name in
  ``numpy.__all__``, as well as the ``_traces`` and ``_values`` data
  catalogs built up by earlier sequence steps.
* :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval` — evaluate
  a Python expression string against the engine namespace using
  :mod:`asteval`.
* :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.log` — a
  :class:`logging.Logger` whose records are forwarded to the application's
  log viewer.

Example: a "Send notification" command
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following example sends a brief notification to a remote HTTP endpoint
(using the standard-library :mod:`urllib`) whenever the step is executed:

.. code-block:: python

    # src/my_measurement_extras/notify.py

    import json
    import urllib.request
    from PyQt6.QtWidgets import QFormLayout, QLineEdit, QWidget

    from stoner_measurement.plugins.command import CommandPlugin


    class NotifyCommand(CommandPlugin):
        """Send a JSON notification to a configurable HTTP endpoint.

        Evaluates ``message_expr`` against the engine namespace and POSTs the
        resulting string as JSON to ``endpoint``.
        """

        def __init__(self, parent=None):
            super().__init__(parent)
            self.endpoint: str = "http://localhost:9000/notify"
            self.message_expr: str = "'Sequence step reached'"

        @property
        def name(self) -> str:
            return "Notify"

        def execute(self) -> None:
            message = self.eval(self.message_expr)
            payload = json.dumps({"message": str(message)}).encode()
            req = urllib.request.Request(
                self.endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=5):
                    self.log.info("Notification sent to %s", self.endpoint)
            except OSError as exc:
                self.log.warning("Notification failed: %s", exc)

        def config_widget(self, parent: QWidget | None = None) -> QWidget:
            widget = QWidget(parent)
            layout = QFormLayout(widget)

            endpoint_edit = QLineEdit(self.endpoint, widget)
            message_edit = QLineEdit(self.message_expr, widget)

            def _apply():
                self.endpoint = endpoint_edit.text().strip()
                self.message_expr = message_edit.text().strip()

            endpoint_edit.editingFinished.connect(_apply)
            message_edit.editingFinished.connect(_apply)

            layout.addRow("Endpoint URL:", endpoint_edit)
            layout.addRow("Message expression:", message_edit)
            widget.setLayout(layout)
            return widget

        def to_json(self):
            d = super().to_json()
            d["endpoint"] = self.endpoint
            d["message_expr"] = self.message_expr
            return d

        def _restore_from_json(self, data):
            self.endpoint = data.get("endpoint", self.endpoint)
            self.message_expr = data.get("message_expr", self.message_expr)

The :meth:`config_widget` override provides a settings tab in the right-hand
configuration panel.  The :meth:`to_json` and :meth:`_restore_from_json`
overrides ensure that the configuration is preserved when a sequence is saved
and reloaded.

Packaging the plugin
---------------------

Place the plugin class inside a normal Python package and declare it as an
entry-point in the package's ``pyproject.toml``.

Minimal package layout
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    my_measurement_extras/
    ├── pyproject.toml
    └── src/
        └── my_measurement_extras/
            ├── __init__.py
            └── notify.py

``pyproject.toml``
~~~~~~~~~~~~~~~~~~~

.. code-block:: toml

    [build-system]
    requires = ["setuptools>=61"]
    build-backend = "setuptools.build_meta"

    [project]
    name = "my-measurement-extras"
    version = "0.1.0"
    requires-python = ">=3.12"
    dependencies = ["stoner_measurement"]

    [tool.setuptools.packages.find]
    where = ["src"]

    [project.entry-points."stoner_measurement.plugins"]
    notify = "my_measurement_extras.notify:NotifyCommand"

The entry-point declaration has the form::

    <entry_point_name> = "<importable.module.path>:<ClassName>"

* ``<entry_point_name>`` is an arbitrary lower-case identifier used
  internally by the plugin manager.  It must be unique across all installed
  packages (choose a name specific enough to avoid collisions).
* The right-hand side is the fully qualified import path to the class,
  separated from the class name by a colon.

You can register **multiple plugins** from the same package by adding one line
per plugin:

.. code-block:: toml

    [project.entry-points."stoner_measurement.plugins"]
    notify    = "my_measurement_extras.notify:NotifyCommand"
    export_hdf5 = "my_measurement_extras.export:HDF5ExportCommand"
    apply_gain  = "my_measurement_extras.transforms:GainTransform"

Installing and verifying
-------------------------

Development install (editable)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

During development, install your package in editable mode so that changes
take effect immediately without reinstalling:

.. code-block:: bash

    cd my_measurement_extras
    pip install -e .

Verifying discovery
~~~~~~~~~~~~~~~~~~~~

You can verify that the application will find your plugin before launching
the full GUI:

.. code-block:: python

    import importlib.metadata

    eps = importlib.metadata.entry_points(group="stoner_measurement.plugins")
    for ep in eps:
        print(ep.name, "→", ep.value)

This should list your new entry-points alongside the built-in ones.
Save the snippet to a file (e.g. ``check_plugins.py``) and run it
as a script if a multi-statement shell command is inconvenient:

.. code-block:: bash

    python check_plugins.py

Once installed, launch the application normally:

.. code-block:: bash

    stoner-measurement

Your plugin will appear in the sequence builder's plugin list and can be
dragged into the sequence tree like any built-in plugin.

Accessing the sequence engine namespace
----------------------------------------

The sequence engine seeds the following names into its namespace before
running a sequence.  Your plugin's :meth:`execute` method (or any method
that uses :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`)
can reference them directly:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Name
     - Description
   * - ``np``, ``numpy``
     - The NumPy module, so sequence scripts and :meth:`eval` calls can use
       functions such as ``np.linspace()``, ``np.sqrt()``, etc.
   * - *All names in* ``numpy.__all__``
     - Every name exported by NumPy (e.g. ``sin``, ``sqrt``, ``linspace``,
       ``array``) is available without a ``np.`` prefix.
   * - ``log``
     - A :class:`logging.Logger` named ``stoner_measurement.sequence``,
       seeded into the namespace so that sequence scripts can call
       ``log.info(…)`` directly.  Inside a plugin method the same logger
       is also available as ``self.log`` for convenience.
       Records are forwarded to the application's log viewer.
   * - ``_traces``
     - Mapping of ``"{instance_name}:{channel}"`` to
       :class:`~stoner_measurement.plugins.TraceData` objects for every trace
       acquired so far in the current sequence run.
   * - ``_values``
     - Mapping of ``"{instance_name}:{quantity}"`` to scalar Python
       expressions (as strings) for every scalar value reported by a plugin.
   * - *plugin instance names*
     - Each registered plugin's
       :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.instance_name`
       is bound to the plugin instance.  For example, a plugin whose
       ``instance_name`` is ``"thermometer"`` can be accessed as
       ``ns["thermometer"]``.

Advanced topics
----------------

Persisting configuration (serialisation)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If your plugin has configuration that should survive a save/reload cycle,
override :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
and :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin._restore_from_json`.
Both methods receive or return a plain Python ``dict`` (JSON-serialisable).
Always call ``super().to_json()`` first and extend the returned dict:

.. code-block:: python

    def to_json(self):
        d = super().to_json()  # includes "type", "class", "instance_name"
        d["my_setting"] = self.my_setting
        return d

    def _restore_from_json(self, data):
        self.my_setting = data.get("my_setting", self.my_setting)

Providing a UI configuration widget
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Override :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_widget`
to return a :class:`~PyQt6.QtWidgets.QWidget` that will appear as a tab in the
right-hand configuration panel.  For multiple tabs, override
:meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_tabs` instead
and return a list of ``(tab_title, widget)`` pairs.

Live monitoring widget
~~~~~~~~~~~~~~~~~~~~~~~

Override :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.monitor_widget`
to return a :class:`~PyQt6.QtWidgets.QWidget` that will be displayed in the
*Monitoring* section of the left dock panel whilst the plugin is registered.
Return ``None`` (the default) if no monitoring widget is needed.

Custom code generation
~~~~~~~~~~~~~~~~~~~~~~~

The sequence engine calls
:meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.generate_action_code`
on each plugin to generate the Python script that is executed by the sequence
engine.  The default :class:`~stoner_measurement.plugins.command.CommandPlugin`
implementation emits a single ``{instance_name}.execute()`` call.  If your
command requires additional boilerplate in the generated script (for example
it needs to loop over a result), override this method:

.. code-block:: python

    def generate_action_code(self, indent, sub_steps, render_sub_step):
        prefix = "    " * indent
        lines = [
            f"{prefix}{self.instance_name}.prepare()",
            f"{prefix}for _item in {self.instance_name}.items():",
            f"{prefix}    {self.instance_name}.process(_item)",
            "",
        ]
        return lines
