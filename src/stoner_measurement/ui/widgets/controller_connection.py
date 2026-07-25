"""Shared helpers for controller connection panels."""

from __future__ import annotations

from collections.abc import Iterable

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QWidget

from stoner_measurement.instruments.addressing import (
    parse_ethernet_address,
    parse_serial_address,
)
from stoner_measurement.ui.widgets.visa_resource_widget import VisaResourceStatus

_STATUS_BACKGROUND = {
    VisaResourceStatus.DISCONNECTED: "",
    VisaResourceStatus.CONNECTING: "#fff3cd",
    VisaResourceStatus.CONNECTED: "#90ee90",
    VisaResourceStatus.ERROR: "#f8d7da",
}

_TRANSPORT_NAME_ALIASES = {
    "null": "Null (test)",
    "null (test)": "Null (test)",
    "serial": "Serial",
    "gpib": "GPIB",
    "ethernet": "Ethernet",
    "kinesis": "Kinesis USB",
    "kinesis usb": "Kinesis USB",
}


def _normalise_transport_name(name: str) -> str:
    """Return the canonical UI label for a transport name.

    Args:
        name (str):
            Stored or selected transport name.

    Returns:
        (str):
            Canonical combo-box label.
    """
    return _TRANSPORT_NAME_ALIASES.get(str(name).strip().lower(), str(name).strip())


def _transport_combo_labels(panel) -> Iterable[str]:
    """Yield all transport combo labels for *panel*."""
    for index in range(panel._transport_combo.count()):
        yield panel._transport_combo.itemText(index)


def _transport_index_from_name(panel, transport: str) -> int:
    """Return the combo-box index for *transport*, accepting aliases."""
    canonical = _normalise_transport_name(transport)
    for index, label in enumerate(_transport_combo_labels(panel)):
        if _normalise_transport_name(label) == canonical:
            return index
    return -1

def _set_widget_background(widget: QWidget, status: VisaResourceStatus) -> None:
    """Apply a connection-status background colour to a generic widget."""
    colour = _STATUS_BACKGROUND.get(status, "")
    if colour:
        widget.setStyleSheet(f"QWidget {{ background-color: {colour}; }}")
    else:
        widget.setStyleSheet("")


def load_connection_preferences(panel) -> None:
    """Initialise connection widgets from engine preferences."""
    driver = panel._engine.preferred_driver_name
    if driver:
        index = panel._driver_combo.findData(driver, role=Qt.ItemDataRole.UserRole + 1)
        if index < 0:
            index = panel._driver_combo.findText(driver)
        if index >= 0:
            panel._driver_combo.setCurrentIndex(index)

    transport = panel._engine.preferred_transport_name
    index = _transport_index_from_name(panel, transport)
    if index >= 0:
        panel._transport_combo.setCurrentIndex(index)

    restore_preferred_address(panel)


def _restore_address(panel, transport: str, address: str) -> None:
    """Restore transport-specific address widgets for the supplied address."""
    transport = _normalise_transport_name(transport)
    if not address:
        return

    if transport == "Serial":
        try:
            port, baud = parse_serial_address(address)
        except ValueError:
            return
        panel._serial_port_combo.set_resource(port)
        index = panel._serial_baud_combo.findData(baud)
        if index >= 0:
            panel._serial_baud_combo.setCurrentIndex(index)
    elif transport == "GPIB":
        panel._gpib_resource_combo.set_resource(address)
    elif transport == "Ethernet":
        try:
            host, port = parse_ethernet_address(address)
        except ValueError:
            return
        panel._eth_host_edit.setText(host)
        panel._eth_port_spin.setValue(port)
    elif transport == "Kinesis USB" and hasattr(panel, "_kinesis_serial_edit"):
        panel._kinesis_serial_edit.setText(address)


def restore_preferred_address(panel) -> None:
    """Restore transport-specific address widgets from engine preferences."""
    _restore_address(
        panel,
        panel._engine.preferred_transport_name,
        panel._engine.preferred_address,
    )


def restore_connection_address(panel, transport: str, address: str) -> None:
    """Restore transport-specific address widgets from a live connection."""
    _restore_address(panel, transport, address)


def show_transport_widget(panel, index: int) -> None:
    """Show widgets for the selected transport."""
    widgets = {
        "Serial": panel._serial_form_widget,
        "GPIB": panel._gpib_form_widget,
        "Ethernet": panel._ethernet_form_widget,
        "Null (test)": panel._null_form_widget,
    }
    if hasattr(panel, "_kinesis_form_widget"):
        widgets["Kinesis USB"] = panel._kinesis_form_widget
    for widget in widgets.values():
        widget.hide()
    selected = _normalise_transport_name(panel._transport_combo.itemText(index))
    widget = widgets.get(selected)
    if widget is not None:
        widget.show()


def selected_transport(panel, index: int) -> tuple[str, str]:
    """Return selected transport name and address."""
    transport = _normalise_transport_name(panel._transport_combo.itemText(index))
    if transport == "Serial":
        port = panel._serial_port_combo.current_resource() or "/dev/ttyUSB0"
        baud = panel._serial_baud_combo.currentData()
        return "Serial", f"port={port};baud={baud}"
    if transport == "GPIB":
        resource = panel._gpib_resource_combo.current_resource() or "GPIB0::2::INSTR"
        return "GPIB", resource
    if transport == "Ethernet":
        host = panel._eth_host_edit.text().strip() or "localhost"
        port = panel._eth_port_spin.value()
        return "Ethernet", f"{host}:{port}"
    if transport == "Kinesis USB":
        return "Kinesis USB", panel._kinesis_serial_edit.text().strip()
    return "Null (test)", ""


def set_address_widget_status(panel, transport_index: int, status: VisaResourceStatus) -> None:
    """Update connection status on address widgets that support it."""
    transport = _normalise_transport_name(panel._transport_combo.itemText(transport_index))
    if transport == "Serial":
        panel._serial_port_combo.set_status(status)
    elif transport == "GPIB":
        panel._gpib_resource_combo.set_status(status)
    elif transport == "Ethernet":
        _set_widget_background(panel._ethernet_form_widget, status)
        _set_widget_background(panel._eth_host_edit, status)
        _set_widget_background(panel._eth_port_spin, status)
    elif transport == "Kinesis USB":
        _set_widget_background(panel._kinesis_form_widget, status)
        _set_widget_background(panel._kinesis_serial_edit, status)
    elif transport == "Null (test)":
        _set_widget_background(panel._null_form_widget, status)
