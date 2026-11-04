Preferences and local resources
================================

This reference is for users and rig administrators customising an installation.
It separates application preferences and local resources from the measurement
sequences and data files described in :doc:`usage` and :doc:`data_workflows`.

Preferences
-------------

Open **Edit → Preferences…**. **General** contains the default data directory,
measurement-rig label, theme, and application/editor/console font sizes.
**Features** controls which rig subsystems are exposed. **Toolbar** controls
toolbar size and predefined-sequence buttons. **Plugin List** controls the
catalogue organisation. A hidden feature is not the same as uninstalling its
Python package or instrument driver.

Relative Save paths are resolved against the default data directory. Selecting
a directory does not automatically save results: place a Save command in the
sequence. Changing the theme or font changes presentation, not acquired data.

Where settings live
---------------------

The application uses YAML for local configuration/resources and Qt settings
for UI state such as window geometry and per-display preferences. Sequence JSON
stores the steps and their configuration; saved measurement files also include
sequence metadata for reconstruction. These files serve different purposes.

Use the runtime path resolver to locate the installation's YAML/resource root:

.. code-block:: bash

   python -c "from stoner_measurement.resources import user_config_root; print(user_config_root())"

Run that command in the application environment. On Windows the root is normally
under ``%LOCALAPPDATA%/stoner_measurement``; use the returned path rather than
assuming an operating-system-independent directory.

.. list-table:: Local files and directories
   :header-rows: 1
   :widths: 40 60

   * - Resource
     - Purpose
   * - ``application.yaml``
     - Application preferences and enabled features.
   * - ``toolbar.yaml``
     - Custom predefined-sequence toolbar buttons.
   * - ``plugin_catalogue.yaml``
     - Plugin-list organisation.
   * - ``plugins/``
     - Plugin-type configuration defaults and machine-local settings.
   * - ``sequences/sequence_template.json``
     - Initial content of a new measurement sequence.
   * - ``sequences/<name>.json``
     - Predefined sequences loaded by toolbar buttons.
   * - ``resources/<name>.png``
     - Icons used by those buttons.
   * - Controller YAML files
     - Connection and rig settings for the corresponding shared services.

Bundled defaults live in ``stoner_measurement.conf``. Resource resolution checks
local files before bundled resources. A local toolbar file replaces the bundled
toolbar configuration; other configuration loaders can merge defaults and local
values. Do not assume every YAML resource has the same merge semantics.

Templates and predefined sequences
-----------------------------------

The new-sequence template has the fixed name ``sequence_template.json``.
Supply a local version in ``sequences/`` to customise new sequences without
editing the installed package. Existing saved sequences retain their own steps.

For a predefined toolbar sequence, save its JSON under ``sequences/`` and
configure a button through Preferences or a local ``toolbar.yaml``:

.. code-block:: yaml

   buttons:
     - separator: true
     - name: "Example measurement"
       image: "example.png"
       sequence: "example.json"
       tooltip: "Load the configured example sequence"

Place the icon in ``resources/example.png``. The button loads the sequence;
it does not immediately run it. Check its configuration and use Run normally.
The illustration workflow in :doc:`data_workflows` can be configured this way.
Restart after manual resource edits so startup-built controls are refreshed.

Moving settings between rigs
------------------------------

Transfer sequence JSON for reusable measurement procedures, and review the
destination rig's local connection settings independently. Loading a sequence
does not make its device addresses, limits or controller capabilities suitable
for another instrument. Keep public plugin class paths importable when moving
sequences between environments. Controller-specific settings and compatibility
are covered in :doc:`rig_controls`, :doc:`temperature_controllers` and
:doc:`xray_diffractometer`.
