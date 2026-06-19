"""Qt compatibility shim providing a unified API for PyQt5 and PyQt6.

Uses the ``qtpy`` abstraction layer (``pip install qtpy``) to normalise the
API surface across Qt bindings.  Set the ``QT_API`` environment variable to
``pyqt5`` or ``pyqt6`` (default: ``pyqt6`` when both are installed) before
importing this module or any other Qt code to select the backend.

The ``pyqtgraph`` backend is selected automatically by qtpy when
``PYQTGRAPH_QT_LIB`` is not set; alternatively, set that environment variable
to the same value as ``QT_API`` (``PyQt5`` or ``PyQt6``).

This module re-exports ``pyqtSignal`` and ``pyqtSlot`` under their PyQt names
so that the rest of the package can use the familiar spelling without importing
directly from a binding-specific module.

Examples:
    Selecting a backend before importing any application code::

        import os
        os.environ["QT_API"] = "pyqt5"
        from stoner_measurement import app  # noqa: E402

    Using the re-exported names::

        from stoner_measurement.qt_compat import pyqtSignal, pyqtSlot
"""

from __future__ import annotations

from qtpy.QtCore import Signal as pyqtSignal, Slot as pyqtSlot

__all__ = ["pyqtSignal", "pyqtSlot"]
