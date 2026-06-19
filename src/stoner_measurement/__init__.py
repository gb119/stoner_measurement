"""stoner_measurement — A Qt (PyQt5/PyQt6 via qtpy) application for running scientific measurements."""

# --- Qt compatibility shim ---------------------------------------------------
# This allows existing `from PyQt6...` imports to continue working while
# actually using qtpy underneath (supporting PyQt5 or PyQt6).

import sys

try:
    from qtpy import QtCore, QtGui, QtWidgets

    # Provide PyQt-compatible names expected by the existing codebase.
    if not hasattr(QtCore, "pyqtSignal") and hasattr(QtCore, "Signal"):
        QtCore.pyqtSignal = QtCore.Signal

    if not hasattr(QtCore, "pyqtSlot") and hasattr(QtCore, "Slot"):
        QtCore.pyqtSlot = QtCore.Slot

    # Map PyQt6-style module paths to qtpy modules
    sys.modules.setdefault("PyQt6", sys.modules[__name__])
    sys.modules["PyQt6.QtCore"] = QtCore
    sys.modules["PyQt6.QtGui"] = QtGui
    sys.modules["PyQt6.QtWidgets"] = QtWidgets

    # Some classes moved between Qt5/Qt6; ensure availability
    if not hasattr(QtGui, "QAction"):
        from qtpy.QtWidgets import QAction as _QAction

        QtGui.QAction = _QAction

except ImportError:
    # Fall back to real PyQt6 if qtpy is not available
    pass

# ----------------------------------------------------------------------------- 

__version__ = "0.1.0"
__author__ = "Gavin Burnell"
