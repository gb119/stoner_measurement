Plot displays and controls
===========================

This is the user reference for choosing a measurement display and configuring
polar, XYZ and intensity plots. Start with :doc:`usage` for ordinary XY traces
and markers, and :doc:`data_workflows` for choosing Plot Points or Plot Trace.
Display implementers should use :doc:`plot_display_plugins` instead.

Choosing a display
-------------------

Use **View → Plot display** while the engine and plot queue are idle. Available
choices come from installed display factories. A display change does not
convert coordinates: also choose the matching **Plot form** on the plotting
command. Unsupported saved forms retain their settings visibly so you can
switch back or choose a supported form.

Bundled polar display
---------------------

Choose **View → Plot display → Polar traces**, then select
**Polar (angle, radius)** in Plot Trace or Plot Points. **Angle data** is the
first, independent input; **Radius data** is the second, dependent input.
For angular measurements select motor position as angle and the measured
response as radius. Catalogue selections store their runtime expressions.
Plot Trace replaces a complete pair of arrays; Plot Points appends one pair
of scalars per execution. Use separate plotting steps for multiple responses.
Each step starts with its own persistent series ID: use the same angle source
and a different radius source in each step to overlay datasets. Give each a
distinct title and colour to identify them. Reusing a series ID appends to the
same series for Plot Points or replaces it for Plot Trace.

The polar input scroll area expands with the configuration panel. Controls
remain packed at the top; colour, line/point styles and sizes are below the
angle conventions and become visible as more height is available.

Source angles default to **degrees**, with **radians** selectable. Zero is at
the **top** and positive angles run **clockwise**: 90 degrees is right, 180 is
bottom and 270 is left. These conventions remain adjustable. Origin is
the zero direction measured anticlockwise from the right in the selected source
units (90 degrees by default); the clockwise option reverses increasing angle.
Changing source units converts the origin to preserve its direction. Series sharing one plot
must use the same zero direction and handedness. Signed wrapping labels the
negative half-circle; source values remain unchanged. The display's **Angle
labels** preference changes grid labels independently of source units and is
saved with the selected factory.

**Auto range** follows incoming data. Panning or zooming disables it so that
new samples preserve the chosen view; **Reset view** restores it. Manual ranges
are saved as renderer preferences.

The native circular grid keeps a square aspect ratio. Supported styles are
colour, line style/width and point style/size. Radius uncertainties appear as
radial segments; angle uncertainties appear as arcs. NaNs leave gaps. Lines
follow acquisition order and close only when the first sample is repeated.
Negative radii are reflected through the origin, with their original sign
retained in exported source data and the nearest-sample pointer readout.
Polar does not provide Cartesian extra axes, markers, logarithmic scales or
surface/intensity rendering. Incompatible plotted state uses the existing
**Clear and switch** or **Cancel** dialogue; acquired measurement data remains
available. Saved unsupported command forms retain their bindings visibly.

Bundled XYZ and intensity displays
----------------------------------

**Cartesian XYZ** uses PyQtGraph's native OpenGL view. It accepts Cartesian
three-coordinate lines, points and rectilinear surfaces. Drag to rotate,
Ctrl-drag to pan, and use the wheel to zoom. **Reset view** restores the default
camera. Coordinates are normalized for rendering so different physical units
remain legible; tick labels and exported data retain the original quantities.
OpenGL 2.1 or newer and PyOpenGL are required. PyOpenGL is declared in the
project dependencies, development/CI environments and Conda recipe.

**XY intensity** displays exact acquired X/Y cells with Z bound explicitly as
the value channel. Cell edges lie halfway between neighbouring coordinates,
including nonuniform grids. A single coordinate initially occupies a unit-width
cell until neighbours arrive. Missing cells and non-finite measurements remain
blank. Hover over an acquired cell to read its original coordinates and value.
The standard PyQtGraph menu supplies pan, zoom and image export.

Both displays accept version-one ``SurfaceBinding`` slices/cells and replay
snapshots. The 3D renderer joins only complete neighbouring rectangles; missing
corners leave holes, and acquired points remain visible during partial scans.
No interpolation or implicit conversion between XYZ and intensity bindings is
performed. If a display switch encounters incompatible plot state, choose
**Clear and switch** to open a fresh display, or **Cancel** to keep the current
display and plots. Cancel is the default and Escape action. Clearing resets
plotted series, markers, axes and display settings; acquired measurement data is
retained. The old plots are discarded only after the replacement initialises
successfully. Busy measurements still prevent switching. Compatible idle replay
preserves cells, slice identities, visibility and titles.

Each measurement sequence has its own preferred display. Selecting a display
from **View → Plot display** updates the active sequence and marks it as
changed. When a selected sequence tab requests a different display, a dialog
offers **Use current display for sequence** (updates its saved preference),
**Switch to sequence display**, or **Ignore** (retains both choices). Matching
displays need no dialog. Ignoring the difference applies while editing;
the generated script still selects the sequence's preferred display. Sequence
JSON and copied steps carry the factory ID in ``display_plugin``; older
sequence files without this field use ``cartesian``. Saved measurement data
also carries this choice when importing its sequence.

Generated scripts call ``select_display_plugin('factory_id')`` before plugin
instantiation, connection or configuration. This helper is also available in
the console and through ``SequenceEngine.select_display_plugin``. It selects
the required display on the GUI thread, clearing plotted state when replacing
the display, while retaining acquired data. Selecting the current plugin is a
no-op and preserves plots, axes and display settings. An unavailable or broken display
raises an error and retains the previous display; it does not silently choose
another renderer. ``SequenceEngine.preferred_display_plugin`` holds the active
sequence's choice; inactive sequence tabs retain theirs in their documents.

To reduce the standard Cartesian display to one X/Y axis pair before switching,
right-click the plot and choose **Remove Axis → Remove All Extra Axes**. The
submenu also lets you remove a single extra axis. Traces move to the built-in
bottom/left axes and keep their samples; markers anchored to removed axes are
removed. Alternatively use the **Remove** buttons in **Configure Axes…** and
press **OK**. The built-in bottom/left pair is retained. Removing axes prepares
the axis layout; an XYZ switch also requires clearing any existing XY traces.

Use **Colour scale** to select a bundled palette. Automatic colour limits are
calculated independently for each visible series, with labelled colour bars.
Turn off **Auto colour range** to set shared finite minimum/maximum limits.
Palette, colour limits and camera or XY zoom settings are saved per factory.
Axes support one linear axis per coordinate slot, physical labels, limits and
grids. Coordinate/value uncertainties, markers and nonlinear axes are rejected
explicitly. Intensity does not accept portable curve styles; the host retains
them during compatible idle replay.

Plot Trace and Plot Points configuration pages query the active factory's
capabilities. Selecting XYZ enables XYZ and XYZ + value forms; selecting intensity
enables XY intensity. Existing cached pages update immediately on replacement.
Saved forms which the new display cannot accept remain visibly unsupported
until another form is selected; their expressions are preserved.

Preparing surface slices
-------------------------

For Plot Trace surface forms, provide X/Z arrays and the scalar fixed Y for
one slice. **Surface X grid** sorts X and averages repeated coordinates by
default, including floating-point round-off repeats. First/last-sample choices
retain the corresponding acquired sample; strict mode requires unique X and
the same grid in every slice. Averaging repeated X can merge sweep branches,
including hysteresis, so choose the preparation that matches your experiment.

Later slices are interpolated onto the first slice's X grid. **Outside X
range** can hold the nearest boundary value or leave NaN gaps; internal gaps
remain missing. These choices affect plotted samples only, not acquired trace
tables. Repeated-slice replacement is a separate setting from repeated X
within a slice. Give each measured surface a stable ID and use a new acquisition
ID or explicit clear for a new run.

For script access to display selection and preferences, see :doc:`console_api`.
The coordinate and request records are defined in :doc:`plotting_contracts`.
