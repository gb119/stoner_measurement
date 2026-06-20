Console and Script Engine API
=============================

The application embeds a Python console connected to the live sequence engine
namespace. Objects exposed in the console are the same objects used by the UI
and sequence engine, so changes made in the console take effect immediately.

Sequence access
---------------

A live view of the current sequence is available as:

.. code-block:: python

    sequence

The object reflects the current sequence editor contents and is not a snapshot.

Inspecting the sequence
~~~~~~~~~~~~~~~~~~~~~~~

The nested sequence structure:

.. code-block:: python

    sequence.steps

Top-level plugin instances:

.. code-block:: python

    sequence.top_level_plugins

All plugin instances in the sequence tree, including plugins nested inside
state scans and other container plugins:

.. code-block:: python

    sequence.plugins

Examples:

.. code-block:: python

    sequence.plugins[0]
    sequence.plugins[0].name

Refreshing the UI
-----------------

When plugin attributes are modified directly in the console, configuration
widgets may need to be synchronised with the updated values.

Refresh a single plugin:

.. code-block:: python

    plugin.refresh()

Refresh a plugin and all nested child plugins:

.. code-block:: python

    plugin.full_refresh()

Refresh the entire sequence tree:

.. code-block:: python

    sequence.full_refresh()

Scan generators
---------------

Many plugins expose a scan generator through:

.. code-block:: python

    plugin.scan_generator

For convenience, all plugins also provide the alias:

.. code-block:: python

    plugin.scan

Examples:

.. code-block:: python

    plugin.scan.num_points = 201
    plugin.scan.start = 0
    plugin.scan.end = 10

    plugin.refresh()

Because ``scan`` is an alias for ``scan_generator``, all existing APIs and
attributes of the scan generator remain available.

Engine namespace
----------------

Plugins have access to the live sequence engine namespace via:

.. code-block:: python

    plugin.engine_namespace

The namespace contains variables created by sequence scripts, injected plugin
instances, NumPy functions seeded by the engine, and the shared logger.

Examples:

.. code-block:: python

    plugin.engine_namespace["field_max"]
    plugin.log.info("Hello from a plugin")

Examples
--------

Adjust the scan range of the first plugin in the sequence and update the UI:

.. code-block:: python

    sequence.plugins[0].scan.start = 0
    sequence.plugins[0].scan.end = 10
    sequence.plugins[0].refresh()

Refresh every plugin configuration widget in the sequence:

.. code-block:: python

    sequence.full_refresh()