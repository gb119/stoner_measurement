Trace data and output catalogues
================================

This reference is for script users and plugin authors who need to inspect,
construct or transform measurement results. For choosing data through the UI,
follow :doc:`data_workflows`; for execution hooks, use :doc:`third_party_plugins`.

One table, one row coordinate
-----------------------------

:class:`~stoner_measurement.core.TraceData` stores a shared-row measurement
table backed by a pandas DataFrame. Its DataFrame index is an ordinary integer
row index. The independent coordinate is a **column** carrying the ``x`` role,
not a special pandas index. Use column metadata rather than assuming a
particular header is always the independent variable.

Channels acquired at the same coordinates belong in columns of one TraceData,
including their uncertainties and auxiliary readings. Genuinely separate
coordinate arrays belong in separate tables. A trace plugin returns a mapping
``{trace_name: TraceData}``; a state scan/sweep owns one ``TraceData`` at its
``data`` attribute.

Column roles, names and units
------------------------------

Roles describe how a column is used; names and units describe the physical
quantity. They are separate from the DataFrame's column identifier.

.. list-table:: Public role constants from ``stoner_measurement.core``
   :header-rows: 1
   :widths: 30 70

   * - Constant
     - Meaning
   * - ``COLUMN_ROLE_X``
     - Independent coordinate.
   * - ``COLUMN_ROLE_Y``
     - Dependent measurement channel.
   * - ``COLUMN_ROLE_D``
     - X-coordinate uncertainty (horizontal error bar).
   * - ``COLUMN_ROLE_E``
     - Y-coordinate uncertainty (vertical error bar).
   * - ``COLUMN_ROLE_Z``
     - Secondary/auxiliary data channel; this does not automatically bind a
       3D plot's Z slot.

``td.x``, ``td.y``, ``td.d`` and ``td.e`` provide views of the first column with
that role. Use ``get_columns_by_role`` for every matching column, and ``td.df``
for the underlying table. Preserve roles, names and units when returning a
modified copy; changing array values alone is not a complete data contract.

Constructing a trace
--------------------

.. code-block:: python

   import numpy as np
   import pandas as pd
   from stoner_measurement.core import (
       TraceData, COLUMN_ROLE_X, COLUMN_ROLE_Y, COLUMN_ROLE_E,
   )

   simple = TraceData.from_xy(np.array([0., 1., 2.]), np.array([0., 2., 4.]))
   frame = pd.DataFrame({
       "time": [0., 1., 2.],
       "voltage": [0., 2., 4.],
       "voltage_error": [0.1, 0.1, 0.2],
   })
   trace = TraceData(
       frame,
       column_roles={"time": COLUMN_ROLE_X, "voltage": COLUMN_ROLE_Y,
                     "voltage_error": COLUMN_ROLE_E},
       names={"time": "Time", "voltage": "Voltage", "voltage_error": "Voltage error"},
       units={"time": "s", "voltage": "V", "voltage_error": "V"},
   )
   y_columns = trace.get_columns_by_role(COLUMN_ROLE_Y)

Published identities and expressions
-------------------------------------

The engine's trace and scalar catalogues map selectable identities to runtime
expressions. For example:

.. code-block:: text

   iv_trace:Dummy       -> iv_trace.data['Dummy']   (TraceData)
   curve_fit:Ic        -> curve_fit.data['Ic']     (scalar result)
   scan.data           -> scan.data                (collected TraceData)

The exact scalar expression is supplied by the producer; consumers should
resolve the catalogue entry rather than reconstructing it from the label.
The catalogues reflect instances in the current sequence. Their presence
describes available outputs, not proof that a measurement has already run.

Use ``plugin.eval(selected_expression)`` inside a plugin, or inspect an actual
instance in the application console. Catalogue snapshots are for selectors;
evaluate against live state when consuming results. Publication hooks and
change notifications are described in :doc:`third_party_plugins`.

Collected scan and sweep tables
--------------------------------

The default independent column is the commanded state value. An explicitly
selected ``x`` readback supplies that coordinate instead, with the commanded
value retained in an auxiliary ``state`` column. ``iteration`` and ``stage``
are auxiliary bookkeeping columns. Selected outputs retain their configured
data/uncertainty roles; an included ``-`` role is stored as auxiliary data.

Automatic collection follows the point's child actions. Plotting or saving a
collected table inside those actions sees previously completed rows. For the
UI controls, incremental-save ordering and final-row handling, see
:doc:`data_workflows`.

Acquisition data and display data
----------------------------------

Plotting commands select from these tables; a renderer's series and immutable
plot snapshots are a separate representation. Display switching, projection,
surface re-gridding and palette changes do not rewrite the acquired tables.
Save selects measurement trace tables, not pixels or the visible plot range.
See :doc:`plotting_contracts` for the plot-request representation.
