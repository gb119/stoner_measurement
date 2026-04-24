"""VISA resource selection widget.

Provides :class:`VisaResourceComboBox`, a compound widget that combines a
:class:`~PyQt6.QtWidgets.QComboBox` pre-populated with available VISA
resources with a *Refresh* button.  The combo box background changes to
reflect the connection status of the associated instrument.
"""

from __future__ import annotations

from enum import Enum
from typing import Sequence

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

#: Stylesheet templates for each connection status.  ``{bg}`` is replaced
#: with the actual background colour token.
_STYLE_TEMPLATE = "QComboBox {{ background-color: {bg}; }}"

#: Mapping from status to background colour CSS token.
_STATUS_COLOURS: dict[str, str] = {
    "disconnected": "",  # empty ⇒ default palette background
    "connecting": "#FFD580",  # amber
    "connected": "#90EE90",  # light green
    "error": "#FFAAAA",  # light red
}


class VisaResourceStatus(Enum):
    """Connection-status states that drive the combo-box background colour.

    Attributes:
        DISCONNECTED:
            No active connection — the widget shows its default background.
        CONNECTING:
            A connection attempt is in progress — amber background.
        CONNECTED:
            The instrument is connected and responding — green background.
        ERROR:
            A connection or communication error has occurred — light-red
            background.

    Examples:
        >>> VisaResourceStatus.CONNECTED.value
        'connected'
        >>> VisaResourceStatus.ERROR.value
        'error'
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

#: VISA filter string that matches all instrument resources.
FILTER_ALL: str = "?*::INSTR"
#: VISA filter string that matches serial (ASRL) instrument resources.
FILTER_SERIAL: str = "ASRL*::INSTR"
#: VISA filter string that matches GPIB instrument resources.
FILTER_GPIB: str = "GPIB*::*::INSTR"


def list_visa_resources(resource_filter: str = FILTER_ALL) -> list[str]:
    """Return a list of available VISA resource strings.

    Uses :mod:`pyvisa`'s :class:`~pyvisa.ResourceManager` to enumerate
    resources matching *resource_filter*.  If :mod:`pyvisa` is not installed,
    or if no resources are found, an empty list is returned.

    Args:
        resource_filter (str):
            VISA resource filter expression, e.g. ``"?*::INSTR"`` for all
            instruments, ``"ASRL*::INSTR"`` for serial ports, or
            ``"GPIB*::*::INSTR"`` for GPIB devices.  Defaults to
            :data:`FILTER_ALL`.

    Returns:
        (list[str]):
            Sorted list of VISA resource strings that match the filter.

    Examples:
        >>> resources = list_visa_resources()
        >>> isinstance(resources, list)
        True
    """
    try:
        import pyvisa

        rm = pyvisa.ResourceManager()
        resources = rm.list_resources(resource_filter)
        rm.close()
        return sorted(resources)
    except ImportError:
        return []
    except Exception:  # noqa: BLE001 – pyvisa.Error and OSError from missing VISA library
        return []


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------


class VisaResourceComboBox(QWidget):
    """A combo box pre-populated with VISA resource strings plus a *Refresh* button.

    The :class:`~PyQt6.QtWidgets.QComboBox` is editable so users can also
    type a resource string that does not appear in the enumerated list.

    The widget emits :attr:`resource_changed` whenever the selected or typed
    resource string changes, and :attr:`refresh_requested` when the *Refresh*
    button is pressed.

    The background colour of the combo box reflects the current
    :class:`VisaResourceStatus`:

    * **DISCONNECTED** — default palette background (no override).
    * **CONNECTING** — amber.
    * **CONNECTED** — light green.
    * **ERROR** — light red.

    Args:
        parent (QWidget | None):
            Optional Qt parent widget.

    Keyword Parameters:
        resource_filter (str):
            VISA filter expression used when enumerating resources.  Use one
            of the :data:`FILTER_ALL`, :data:`FILTER_SERIAL`, or
            :data:`FILTER_GPIB` constants, or any valid PyVISA filter string.
            Defaults to :data:`FILTER_ALL`.
        placeholder (str):
            Placeholder text displayed in the combo box when no resource has
            been selected.  Defaults to ``"(no resource selected)"``.
        extra_resources (Sequence[str]):
            Additional resource strings to include in the combo list
            regardless of what PyVISA discovers.  Useful for providing
            well-known defaults such as ``"GPIB0::2::INSTR"``.  Defaults to
            an empty sequence.

    Attributes:
        resource_changed (pyqtSignal[str]):
            Emitted when the currently selected resource string changes.
        refresh_requested (pyqtSignal):
            Emitted when the *Refresh* button is clicked.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.ui.widgets.visa_resource_widget import VisaResourceComboBox
        >>> w = VisaResourceComboBox()
        >>> w is not None
        True
        >>> w.current_resource() == "" or isinstance(w.current_resource(), str)
        True
    """

    resource_changed: pyqtSignal = pyqtSignal(str)
    refresh_requested: pyqtSignal = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        resource_filter: str = FILTER_ALL,
        placeholder: str = "(no resource selected)",
        extra_resources: Sequence[str] = (),
    ) -> None:
        super().__init__(parent)
        self._resource_filter = resource_filter
        self._placeholder = placeholder
        self._extra_resources: list[str] = list(extra_resources)
        self._status = VisaResourceStatus.DISCONNECTED

        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def current_resource(self) -> str:
        """Return the currently selected or entered VISA resource string.

        Returns:
            (str):
                The current text of the combo box, stripped of whitespace.
                Returns an empty string when nothing has been entered.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.ui.widgets.visa_resource_widget import VisaResourceComboBox
            >>> w = VisaResourceComboBox(extra_resources=["GPIB0::2::INSTR"])
            >>> w.set_resource("GPIB0::2::INSTR")
            >>> w.current_resource()
            'GPIB0::2::INSTR'
        """
        return self._combo.currentText().strip()

    def set_resource(self, resource: str) -> None:
        """Set the combo box to *resource*, adding it to the list if absent.

        Args:
            resource (str):
                VISA resource string to select.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.ui.widgets.visa_resource_widget import VisaResourceComboBox
            >>> w = VisaResourceComboBox()
            >>> w.set_resource("GPIB0::5::INSTR")
            >>> w.current_resource()
            'GPIB0::5::INSTR'
        """
        idx = self._combo.findText(resource)
        if idx == -1:
            self._combo.addItem(resource)
            idx = self._combo.findText(resource)
        self._combo.setCurrentIndex(idx)

    def set_status(self, status: VisaResourceStatus) -> None:
        """Update the combo-box background colour to reflect *status*.

        Args:
            status (VisaResourceStatus):
                The new connection status.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.ui.widgets.visa_resource_widget import (
            ...     VisaResourceComboBox, VisaResourceStatus,
            ... )
            >>> w = VisaResourceComboBox()
            >>> w.set_status(VisaResourceStatus.CONNECTED)
            >>> w.status
            <VisaResourceStatus.CONNECTED: 'connected'>
        """
        self._status = status
        colour = _STATUS_COLOURS.get(status.value, "")
        if colour:
            self._combo.setStyleSheet(_STYLE_TEMPLATE.format(bg=colour))
        else:
            self._combo.setStyleSheet("")

    @property
    def status(self) -> VisaResourceStatus:
        """Current connection status.

        Returns:
            (VisaResourceStatus):
                The most recently set status value.
        """
        return self._status

    @property
    def combo(self) -> QComboBox:
        """The underlying :class:`~PyQt6.QtWidgets.QComboBox`.

        Provides direct access for advanced customisation such as adjusting
        the minimum width or installing item delegates.

        Returns:
            (QComboBox):
                The combo-box widget.
        """
        return self._combo

    def refresh(self) -> None:
        """Re-enumerate VISA resources and repopulate the combo box.

        Preserves the currently selected resource if it is still available
        after the refresh, or if it was manually entered by the user.  Emits
        :attr:`refresh_requested` after the list has been rebuilt.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.ui.widgets.visa_resource_widget import VisaResourceComboBox
            >>> w = VisaResourceComboBox()
            >>> w.refresh()  # should not raise
        """
        previous = self.current_resource()

        self._combo.blockSignals(True)
        self._combo.clear()

        resources = list_visa_resources(self._resource_filter)
        # Merge in any extra resources that were not discovered automatically.
        merged: list[str] = list(resources)
        for r in self._extra_resources:
            if r not in merged:
                merged.append(r)

        for r in merged:
            self._combo.addItem(r)

        # Restore the previous selection if it is still present, otherwise
        # re-add it so the user's entry is not silently discarded.
        if previous:
            idx = self._combo.findText(previous)
            if idx == -1:
                self._combo.insertItem(0, previous)
                self._combo.setCurrentIndex(0)
            else:
                self._combo.setCurrentIndex(idx)

        self._combo.blockSignals(False)
        self.refresh_requested.emit()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the internal layout with combo box and refresh button."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._combo = QComboBox(self)
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._combo.setPlaceholderText(self._placeholder)
        self._combo.currentTextChanged.connect(self.resource_changed)
        layout.addWidget(self._combo)

        self._refresh_btn = QPushButton("Refresh", self)
        self._refresh_btn.setFixedWidth(70)
        self._refresh_btn.setToolTip("Re-scan for available VISA resources")
        self._refresh_btn.clicked.connect(self.refresh)
        layout.addWidget(self._refresh_btn)

        self.setLayout(layout)
