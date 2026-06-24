Round dial widget
=================

The application now includes a reusable round dial display widget for angular
or scalar readback. It is intended as a **display** rather than an interactive
knob control.

Available classes
-----------------

The dial components are available from either of these import paths:

.. code-block:: python

   from stoner_measurement.ui import RoundDialWidget, RoundDialDemoWidget, RoundDialPanel

or:

.. code-block:: python

   from stoner_measurement.ui.widgets import (
       RoundDialWidget,
       RoundDialDemoWidget,
       RoundDialPanel,
   )

The main classes are:

* :class:`stoner_measurement.ui.widgets.round_dial.RoundDialWidget` —
  a single scalable dial display
* :class:`stoner_measurement.ui.widgets.round_dial_demo.RoundDialDemoWidget` —
  a small demonstration panel with common presets
* :class:`stoner_measurement.ui.widgets.round_dial_panel.RoundDialPanel` —
  a convenience container for embedding one or more dials in other panels

Angle convention
----------------

The dial uses a top-referenced clockwise angular convention:

* ``0`` degrees = vertically upwards
* ``90`` degrees = right
* ``180`` degrees = down
* ``270`` degrees = left

This makes it suitable for motor position, compass direction, stage angle,
sample rotation, and similar readouts.

Basic example
-------------

.. code-block:: python

   from qtpy.QtWidgets import QVBoxLayout, QWidget
   from stoner_measurement.ui import RoundDialWidget

   panel = QWidget()
   layout = QVBoxLayout(panel)

   dial = RoundDialWidget()
   dial.setTitle("Motor Position")
   dial.setRange(0.0, 360.0)
   dial.setScaleAngles(0.0, 360.0)
   dial.setTickSteps(30.0, 4, 30.0)
   dial.setUnitsText("°")
   dial.setWrap(True)
   dial.setValue(15.0)

   layout.addWidget(dial)

Partial-arc example
-------------------

.. code-block:: python

   dial = RoundDialWidget()
   dial.setTitle("Position")
   dial.setRange(0.0, 100.0)
   dial.setScaleAngles(-225.0, 45.0)
   dial.setTickSteps(10.0, 4, 10.0)
   dial.setUnitsText("%")
   dial.setValue(62.0)

Built-in presets
----------------

The widget provides a few convenience presets:

.. code-block:: python

   dial.setAngleValueMode()         # 0..360°, full circle
   dial.setCompassMode()            # compass-style direction display
   dial.setBidirectionalAngleMode() # -180..180°
    dial.setClockMode()              # 12-hour clock-face display

Theme support
-------------

The dial automatically follows the application's dark/light theme by deriving
its default colours from :mod:`stoner_measurement.ui.theme`.

If you set custom colours explicitly, those overrides remain in place across
theme changes until you call:

.. code-block:: python

   dial.resetThemeColors()

Standalone demo
---------------

A small standalone demo window is available from the console script:

.. code-block:: text

   stoner-measurement-round-dial-demo

This opens a themed demo window showing several useful dial presets.

Clock mode
----------

Clock mode configures the dial as a 12-hour face with ``12`` vertically at the
top and labels ``1`` through ``11`` arranged clockwise around the dial.

The central value readout is formatted as ``HH:MM`` using the integer part as
the hour and the fractional part converted to minutes. For example:

* ``3.5`` displays as ``03:30``
* ``11.75`` displays as ``11:45``

Embedding multiple dials
------------------------

Use :class:`stoner_measurement.ui.widgets.round_dial_panel.RoundDialPanel`
when you want a quick container for several readback dials:

.. code-block:: python

   from stoner_measurement.ui import RoundDialPanel

   panel = RoundDialPanel()
   motor = panel.add_dial(
       "Motor Position",
       minimum=0.0,
       maximum=360.0,
       minimum_angle=0.0,
       maximum_angle=360.0,
       major_tick_step=30.0,
       minor_ticks_per_major=4,
       label_step=30.0,
       units="°",
   )
   motor.setWrap(True)
   motor.setValue(12.5)
