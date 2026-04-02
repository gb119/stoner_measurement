Installation
============

Prerequisites
-------------

* Python 3.13 or newer
* A working Qt 6 installation (provided automatically by ``PyQt6``)

Install from PyPI (once released)
----------------------------------

.. code-block:: bash

    pip install stoner_measurement

Install from source
-------------------

.. code-block:: bash

    git clone https://github.com/gb119/stoner_measurement.git
    cd stoner_measurement
    pip install -e ".[dev,docs]"

Install via conda
-----------------

A conda recipe is provided under ``conda-recipe/``.  Build and install with:

.. code-block:: bash

    conda build conda-recipe/
    conda install --use-local stoner_measurement
