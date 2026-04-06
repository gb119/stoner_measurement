Plugin modules
==============

.. automodule:: stoner_measurement.plugins.base_plugin
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.trace
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: stoner_measurement.plugins.dummy
   :members:
   :undoc-members:
   :show-inheritance:

Trace plugin lifecycle
----------------------

All :class:`~stoner_measurement.plugins.trace.TracePlugin` subclasses share a
four-step lifecycle called by the sequence engine:

1. **connect()** — open instrument connections and verify instrument identity.
2. **configure()** — push plugin settings to the instrument.
3. **measure(parameters)** — acquire the complete multipoint trace and return
   all ``(channel, x, y)`` data points as a list.  This is a single blocking
   call; the sequence engine calls it once per measurement step to obtain the
   full dataset.
4. **disconnect()** — cleanly release all reserved resources.

The generated sequence code for a trace plugin follows this pattern:

.. code-block:: python

    instrument.connect()
    instrument.configure()
    try:
        data = instrument.measure({})
        for channel, x, y in data:
            print(f"{channel}: x={x:.4g}, y={y:.4g}")
    finally:
        instrument.disconnect()

Implementing a trace plugin
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Subclass :class:`~stoner_measurement.plugins.trace.TracePlugin` and implement:

* :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name` — unique
  string identifier.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin.execute` — generator
  that yields ``(x, y)`` pairs for each measured point.  The active
  :attr:`~stoner_measurement.plugins.trace.TracePlugin.scan_generator` provides
  the x-values and *measure* flags.

Optionally override:

* :meth:`~stoner_measurement.plugins.trace.TracePlugin.connect` — open hardware
  connections.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin.configure` — push
  settings to the instrument.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin.disconnect` — close
  hardware connections.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin._plugin_config_tabs` —
  return a :class:`~PyQt6.QtWidgets.QWidget` for the *Settings* configuration
  tab.
* :meth:`~stoner_measurement.plugins.trace.TracePlugin._about_html` — return an
  HTML string for the *About* tab.
