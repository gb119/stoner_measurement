Installation
=============

This page gets a new user to a working application environment. For repository
development tools and verification commands, see :doc:`contributing`.

Requirements and Qt choice
----------------------------

The Python package declares Python **3.12 or newer**. Supplied Conda environment
files and the Conda recipe can impose a narrower/newer constraint; use the
constraint in the file you choose. The default ``environment.yml`` currently
requires Python 3.13 or newer.

The application imports Qt through ``qtpy`` and supports PyQt5 and PyQt6. A Qt
binding must be installed: the base package dependencies do not select one.
Use the ``pyqt5`` or ``pyqt6`` extra when installing from source, or a supplied
environment file with the desired binding.

Ordinary XY, polar and XY-intensity displays use 2D graphics. Cartesian XYZ
requires PyOpenGL and a working OpenGL 2.1-or-newer graphics driver. PyOpenGL
is declared as a package dependency. See :doc:`plot_displays` for display choices.

Install from the source checkout
---------------------------------

In a Python environment with the required interpreter:

.. code-block:: bash

   git clone https://github.com/gb119/stoner_measurement.git
   cd stoner_measurement
   python -m pip install -e ".[pyqt6]"
   stoner-measurement

Choose ``.[pyqt5]`` for PyQt5 instead. Install ``.[pyqt6,instruments]`` when the
additional instrument libraries are needed. Vendor drivers, VISA runtimes and
device-specific setup remain separate requirements for the chosen hardware.
An editable installation is useful when working from a checkout; a distributed
wheel can instead be installed with ``python -m pip install <wheel-path>`` in
an environment that already has the chosen Qt binding.

Use a supplied Conda environment
---------------------------------

From the checkout:

.. code-block:: powershell

   conda env create -f environment.yml
   conda run -n stoner_measurement python -m pip install -e . --no-deps
   conda run -n stoner_measurement stoner-measurement

The default environment includes the runtime and development tools. Alternative
``environment-pyqt5.yml`` and ``environment-pyqt6.yml`` files define explicit
binding choices; inspect their Python constraints when selecting one. Use one
environment definition consistently rather than mixing Qt stacks accidentally.

To build the local Conda recipe, install Conda Build and run
``conda build conda-recipe/`` followed by
``conda install --use-local stoner_measurement``. This is a local package-build
route, not a statement that a particular remote channel has a published build.

First launch
-------------

Start with the hardware-free example in :doc:`usage`. It exercises configuration,
execution and plotting before adding rig-specific instrument dependencies.
Use :doc:`configuration` for preferences and local resources, and
:doc:`simulated_instruments` for controller simulations.
