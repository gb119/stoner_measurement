"""SI-aware combo-box widget.

Provides :class:`SIComboBox`, a :class:`~PyQt6.QtWidgets.QComboBox` subclass
whose items store float values and whose labels are automatically formatted
with SI engineering prefixes using :func:`pyqtgraph.functions.siFormat`.
"""

from __future__ import annotations

import pyqtgraph as pg
from stoner_measurement.qt_compat import pyqtSignal
from qtpy.QtWidgets import QComboBox

__all__ = ["SIComboBox"]


class SIComboBox(QComboBox):
    """A :class:`~PyQt6.QtWidgets.QComboBox` that displays float values with SI prefixes.

    Items can be added in two ways:

    * :meth:`addValueItem` — stores a float and auto-generates an SI-prefixed
      label (e.g. ``1e-9`` with unit ``"A"`` → ``"1 nA"``).
    * :meth:`addSpecialItem` — stores an arbitrary float with a custom label,
      for entries such as ``"Auto"`` or ``"Best (auto, set once)"``.

    The standard :meth:`~PyQt6.QtWidgets.QComboBox.addItem` / ``addItems``
    methods still work and can be used to add items whose ``itemData`` is
    *not* a plain float (useful when the combo doubles as a mode selector that
    carries additional metadata).  In that case use the inherited
    :meth:`~PyQt6.QtWidgets.QComboBox.currentData` to retrieve the stored
    object, and avoid calling :meth:`currentFloatValue` or
    :meth:`setFloatValue`.

    The :attr:`valueChanged` signal is emitted with the current item's float
    data whenever the selection changes; items whose data cannot be cast to
    ``float`` (i.e. ``float(data)`` raises :exc:`TypeError` or
    :exc:`ValueError`) suppress the signal.  This means the signal fires for
    stored ``float``, ``int``, and ``numpy.float64`` values, among others.

    Attributes:
        valueChanged (pyqtSignal[float]):
            Emitted with the new float value when the current index changes
            and the selected item's data is castable to ``float``.

    Keyword Parameters:
        unit (str):
            SI base unit appended to auto-generated labels (e.g. ``"A"``,
            ``"V"``).  Passed to :func:`pyqtgraph.functions.siFormat`.
        precision (int):
            Number of significant digits in auto-generated labels.  Defaults
            to ``3``.
        parent:
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> cb = SIComboBox(unit="V")
        >>> cb.addSpecialItem("Auto", 0.0)
        >>> cb.addValueItem(0.01)
        >>> cb.addValueItem(0.1)
        >>> cb.addValueItem(1.0)
        >>> cb.itemText(1)
        '10 mV'
        >>> cb.itemText(2)
        '100 mV'
        >>> cb.itemText(3)
        '1 V'
        >>> cb.setFloatValue(0.01)
        >>> cb.currentFloatValue()
        0.01
    """

    valueChanged = pyqtSignal(float)

    def __init__(self, *, unit: str = "", precision: int = 3, parent=None) -> None:
        """Initialise the combo box with the given unit and precision."""
        super().__init__(parent)
        self._unit = unit
        self._precision = precision
        self.currentIndexChanged.connect(self._on_index_changed)

    # ------------------------------------------------------------------
    # Class-level SI formatter (usable without an instance)
    # ------------------------------------------------------------------

    @staticmethod
    def format_si(value: float, unit: str, *, precision: int = 3) -> str:
        """Format *value* with an appropriate SI prefix and *unit*.

        Delegates to :func:`pyqtgraph.functions.siFormat` for consistent
        formatting across the application.

        Args:
            value (float):
                The numerical value to format.
            unit (str):
                The base unit string (e.g. ``"A"``, ``"V"``).

        Keyword Parameters:
            precision (int):
                Number of significant digits.  Defaults to ``3``.

        Returns:
            (str):
                A human-readable string such as ``"1 nA"`` or ``"100 mV"``.

        Examples:
            >>> SIComboBox.format_si(1e-9, "A")
            '1 nA'
            >>> SIComboBox.format_si(100e-3, "V")
            '100 mV'
            >>> SIComboBox.format_si(120.0, "V")
            '120 V'
            >>> SIComboBox.format_si(1e-10, "A")
            '100 pA'
        """
        return pg.functions.siFormat(value, suffix=unit, precision=precision)

    def refresh(self) -> None:
        """Refresh the widget display."""
        self.update()

    # ------------------------------------------------------------------
    # Item-addition helpers
    # ------------------------------------------------------------------

    def addValueItem(self, value: float, label: str | None = None) -> None:
        """Append a numeric item, auto-formatting the label with SI prefix.

        The *value* is stored as the item's ``itemData``.

        Args:
            value (float):
                Numeric value to add (stored as item data).

        Keyword Parameters:
            label (str | None):
                Custom display label.  When ``None`` (default), the label is
                generated automatically from *value* and the combo's
                :attr:`unit`.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> cb = SIComboBox(unit="A")
            >>> cb.addValueItem(1e-3)
            >>> cb.itemText(0)
            '1 mA'
        """
        display = label if label is not None else self.format_si(value, self._unit, precision=self._precision)
        self.addItem(display, float(value))

    def addSpecialItem(self, label: str, value: float) -> None:
        """Append an item with a custom label and a float *value*.

        Use this for entries such as ``"Auto"`` or ``"Best (auto, set once)"``
        where the label cannot be auto-generated.

        Args:
            label (str):
                Display label for the item.
            value (float):
                Float value stored as item data.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> cb = SIComboBox(unit="V")
            >>> cb.addSpecialItem("Auto", 0.0)
            >>> cb.itemText(0)
            'Auto'
            >>> cb.itemData(0)
            0.0
        """
        self.addItem(label, float(value))

    # ------------------------------------------------------------------
    # Value accessors
    # ------------------------------------------------------------------

    def currentFloatValue(self) -> float:
        """Return the currently selected item's float data value.

        Returns:
            (float):
                Data of the current item cast to ``float``.

        Raises:
            TypeError:
                If the current item's data is not a ``float`` or cannot be
                cast to one (e.g. when the item was added via plain
                :meth:`~PyQt6.QtWidgets.QComboBox.addItem` with non-numeric
                data).

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> cb = SIComboBox(unit="V")
            >>> cb.addValueItem(1.0)
            >>> cb.currentFloatValue()
            1.0
        """
        return float(self.currentData())

    def setFloatValue(self, value: float) -> None:
        """Select the item whose float data matches *value*.

        Items are compared with a relative tolerance of ``1e-9`` to handle
        floating-point rounding, falling back to absolute tolerance of ``1e-30``
        for values very close to zero (``abs_tol`` guards against false positives
        near zero where relative comparison is unreliable; ``1e-300`` is used as
        the minimum scale to avoid division-by-zero in the relative check).
        If no exact match is found the selection is not changed.

        Args:
            value (float):
                Target float value.  Must match one of the items added via
                :meth:`addValueItem` or :meth:`addSpecialItem`.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> cb = SIComboBox(unit="V")
            >>> cb.addSpecialItem("Auto", 0.0)
            >>> cb.addValueItem(1.0)
            >>> cb.setFloatValue(1.0)
            >>> cb.currentFloatValue()
            1.0
        """
        for i in range(self.count()):
            data = self.itemData(i)
            try:
                item_val = float(data)
            except (TypeError, ValueError):
                continue
            # Use absolute tolerance (1e-30) to guard zero vs near-zero, and
            # relative tolerance (1e-9) for larger values.  The scale floor of
            # 1e-300 prevents division-by-zero in the relative comparison.
            abs_tol = 1e-30
            rel_tol = 1e-9
            scale_floor = 1e-300
            diff = abs(item_val - value)
            scale = max(abs(item_val), abs(value), scale_floor)
            if diff <= abs_tol or diff / scale <= rel_tol:
                self.setCurrentIndex(i)
                return

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_index_changed(self, index: int) -> None:
        """Emit :attr:`valueChanged` when the selected item's data is castable to float."""
        data = self.itemData(index)
        try:
            self.valueChanged.emit(float(data))
        except (TypeError, ValueError):
            pass
