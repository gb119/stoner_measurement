Stoner Measurement
===================

Stoner Measurement builds laboratory procedures from configurable sequence
steps, runs them as Python, and keeps acquired results with their configuration.
Start with a hardware-free example, then add the drivers and control services
needed by your rig.

Choose your path
-----------------

**New users:** read :doc:`installation`, then :doc:`usage`. Follow its simulated
I-V example before connecting hardware. Continue to :doc:`data_workflows` for
a complete scan, filtering, fitting, plotting and saving walkthrough.

**Experienced users:** use the measurement reference for execution order,
expressions, data tables, display choices, local configuration and rig controls.
These pages explain how to operate and compose existing features.

**Developers:** use the extension guides for sequence plugins or display
factories, the data/protocol references for integration contracts, and
:doc:`contributing` for changes to the application repository. Instrument-driver
composition and discovery are introduced in :doc:`api/instruments`.

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   installation
   usage
   data_workflows

.. toctree::
   :maxdepth: 2
   :caption: Measurement reference

   sequence_execution
   console_api
   trace_data
   plot_displays
   configuration
   simulated_instruments
   rig_controls
   keithley_meters

.. toctree::
   :maxdepth: 2
   :caption: Extending and developing

   third_party_plugins
   plot_display_plugins
   plotting_contracts
   plugin_tab_ordering
   round_dial_widget
   contributing
   api/index

Indices and tables
-------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
