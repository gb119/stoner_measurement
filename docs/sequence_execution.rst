Sequence execution reference
=============================

This page is for users arranging and debugging measurement sequences. Begin
with :doc:`usage` for adding steps and :doc:`data_workflows` for acquisition,
fitting and saving. See :doc:`sequence_commands` for individual step settings
and :doc:`third_party_plugins` for lifecycle and generation contracts.

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

Use :doc:`Reconfigure </_generated/sequence_commands/plugin-reconfigure>` to
apply different settings to the same instrument at different points in the
sequence::

    Reconfigure (select measurement_a)
    measurement_a
    Reconfigure (select measurement_b)
    measurement_b

Leave startup suppression enabled on both commands. Put another Reconfigure
before returning to ``measurement_a`` so its settings are applied again.
In a conditional sequence, make sure every path that uses an instance reaches
its setup step first.

Shared controller sessions remain owned by their controller services. A
Reconfigure selection is not a mechanism for another instance to close a
borrowed service's sessions. See the relevant controller reference for rig
connection settings.

Collecting and saving inside loops
-----------------------------------

At the end of a scan or sweep point, collection runs before deferred actions.
This still happens when Break If or Continue If skips the rest of the point.
Place :doc:`Skip Collection </_generated/sequence_commands/plugin-skip_collection>`
before either step if the current point should be excluded. An **If** around
:doc:`Save </_generated/sequence_commands/plugin-save>` controls when accumulated
rows are written. See :doc:`data_workflows` for a worked example.

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
