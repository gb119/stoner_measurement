Developing the application
===========================

This page is for contributors changing the repository. To add an external
sequence plugin without modifying the application, use
:doc:`third_party_plugins`; for a display factory, use :doc:`plot_display_plugins`.
End users can follow :doc:`installation` without the contributor workflow.

Development environment
------------------------

Read ``AGENTS.md`` in the checkout before changing code. Project commands run
through the ``stoner_measurement`` Conda environment; activation need not persist
between shell calls:

.. code-block:: powershell

   conda env create -f environment.yml
   conda run -n stoner_measurement python -m pip install -e . --no-deps
   conda run -n stoner_measurement stoner-measurement

On Windows, prefer ``& $env:CONDA_EXE run -n stoner_measurement ...`` when that
variable is set. Use the Anaconda/Miniforge installation hosting the environment;
the repository instructions exclude the unreliable Miniconda location.

Choosing and running tests
---------------------------

Read ``notes/testing_guidelines.md`` before adding, moving or rewriting tests,
and maintain migration records in ``notes/testing_restructure_plan.md``. Keep
unit tests focused on one module/contract and broader flows under
``tests/integration``. Use fake transports/drivers for automated hardware tests.

.. code-block:: powershell

   $env:QT_QPA_PLATFORM = "offscreen"
   $env:QT_QPA_FONTDIR = "C:\Windows\Fonts"
   conda run -n stoner_measurement python -m pytest tests/unit/plugins/command -q
   conda run -n stoner_measurement python -m pytest -q

Choose the focused tests for the changed contract first. Use
``managed_qt_widget`` for top-level widgets and
``managed_plugin_config_tabs`` for every page returned by ``config_tabs()``.
Keep hidden preview pages alive until deterministic GUI-thread teardown.
Use a workspace ``--basetemp`` if the system temporary directory is inaccessible.

Quality and distribution checks
--------------------------------

.. code-block:: powershell

   conda run -n stoner_measurement python -m ruff check src tests docs
   conda run -n stoner_measurement python -m ruff format --check src tests docs
   conda run -n stoner_measurement python -m pylint src
   conda run -n stoner_measurement python -m build
   conda run -n stoner_measurement python -m twine check dist/*
   conda run -n stoner_measurement check-manifest

Scale checks to the change. Preserve production quality checks; repository
Codacy configuration excludes test-only complexity from the relevant engines.
Local lint is not proof of hosted Codacy or CI success: inspect the immutable
pushed commit's checks before reporting remote clearance.

Documentation and examples
---------------------------

Keep user-facing Sphinx pages in ``docs/`` and developer plans/evidence in
``notes/``. Give each page a defined audience and purpose, link to the canonical
reference instead of copying it, and validate examples against current source.
Use :doc:`plugin_tab_ordering` and the shared widgets when extending plugin UI.

.. code-block:: powershell

   conda run -n stoner_measurement python -m sphinx -b html docs docs/_build/html

Check warnings against changed pages and inspect the generated HTML, downloads
and image links. A successful build can still contain warnings from other API
docstrings. Validate executable examples, including generated actions and
persistence, rather than only syntax-highlighting their source.
