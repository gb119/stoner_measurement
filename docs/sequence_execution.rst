Sequence execution reference
=============================

This page is for users arranging and debugging measurement sequences. Begin
with :doc:`usage` for adding/configuring steps and :doc:`data_workflows` for
acquisition, fitting and saving. Plugin implementers should instead follow
:doc:`third_party_plugins` for lifecycle and generation contracts.

The execution model
--------------------

The application generates Python from the sequence tree. It reconstructs or
reuses step instances, performs startup setup for lifecycle-managed steps,
runs actions in tree order, and executes cleanup when the action block exits.
Container steps define when their children run: a scan or sweep repeats them,
and a condition runs them only when its condition permits.

Expressions refer to instance names in a shared namespace. Configure an
upstream acquisition or fit before a downstream step that needs its result.
An output shown in a selector is not necessarily a completed reading.
**Generate Code** and the **Script Editor** show the actual ordering; editing
the Python script does not rewrite the sequence tree.

One-off checks and execution controls
-------------------------------------

**Run** (:kbd:`F5`) runs the sequence on Measurement and the active Python
script on Script Editor. **Pause** (:kbd:`F7`) pauses/resumes execution and
**Stop** (:kbd:`F6`) requests cancellation. A blocking instrument operation
may take until its configured timeout to return.

**Run Selection…** (:kbd:`Shift+F5`) generates a temporary script from selected
roots in sequence order. A selected container includes its whole subtree;
children whose ancestor is selected are not added twice. A child selected
alone does not acquire its unselected parent's setup or loop context. See
:ref:`running-selected-steps` for the screenshot and temporary-script handling.

.. _sequence-reconfiguration:

Reconnecting and applying settings at a chosen step
---------------------------------------------------

Use **Reconfigure** when selected instances need their connection/configuration
applied at a particular point rather than only at sequence startup. Its flat
checklist identifies sequence instances, not plugin types. Each execution
reconnects the selected instances and applies their settings in sequence order.

**Suppress connect and configure at startup** defaults to on. Keep it enabled
when those instances must wait for this command before becoming ready. Turn it
off when normal startup setup should still occur and the command should apply
settings again later. A target's deferred state is derived from enabled
Reconfigure selections; it has no independent editor or saved flag.

For two configured instances using the same instrument at different points::

    Reconfigure (select measurement_a)
    measurement_a
    Reconfigure (select measurement_b)
    measurement_b

Leave suppression enabled on both commands. Put another Reconfigure before
returning to ``measurement_a`` so its settings are applied again. Reconfigure
inside a loop reconnects and configures on every iteration. Runtime readiness
checks still apply inside branches and loops; arranging a command elsewhere
in the tree does not make an instance ready unless that command executes.
Disabled targets are skipped, and removed/unresolved targets raise an error.

Shared controller sessions remain owned by their controller services. A
Reconfigure selection is not a mechanism for another instance to close a
borrowed service's sessions. See the relevant controller reference for rig
connection settings.

Collecting and saving inside loops
-----------------------------------

State scans/sweeps collect a row after their child actions. A Plot Points child
can plot current scalar results immediately, but a Save child selecting the
collected table sees earlier rows. Place a complete Save after the parent
container for the finished table, or add a final call to the same incremental
Save instance before generated cleanup when editing Python. The complete
worked example and file behavior are in :doc:`data_workflows`.

Sequence files, scripts and result provenance
---------------------------------------------

**New**, **Open**, **Save** and **Save As** apply to the active main tab:
Measurement stores the editable sequence as JSON; Script Editor stores Python.
Saving either document does not write acquired measurement tables. Use a Save
sequence command for those results, as described in :doc:`data_workflows`.

To recover the procedure from an earlier result, choose **File → Import
Sequence from Data…** and select a saved tab-delimited TDI text file or NeXus
HDF5 file containing sequence metadata. The application reconstructs the step
tree and configuration in a new, unsaved sequence document. Review the rig's
connection settings and save the sequence before adapting or running it.
This imports the procedure, rather than loading the file's readings into each
step's runtime outputs. Files lacking the required metadata cannot reconstruct
a sequence; external plugin classes must still be importable.

Inspecting failures
--------------------

Use the status bar, Log Viewer and script console together. Generated-script
errors can identify the responsible step; edited scripts use Python traceback
locations. Inspect expression values and output availability in the console
while idle. Some numerical processing steps deliberately log a failed result
and publish NaNs so a sequence can continue; continuing is not evidence of a
successful fit. See :doc:`console_api` for inspection and refresh commands.
