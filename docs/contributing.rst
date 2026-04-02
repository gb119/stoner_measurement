Contributing
============

Development setup
-----------------

.. code-block:: bash

    git clone https://github.com/gb119/stoner_measurement.git
    cd stoner_measurement
    pip install -e ".[dev,docs]"

Running tests
-------------

.. code-block:: bash

    pytest

Linting
-------

.. code-block:: bash

    ruff check src/ tests/

Building the documentation
--------------------------

.. code-block:: bash

    cd docs
    make html
    # Output is in docs/_build/html/
