"""Reusable per-controller connection forms for the temperature panel."""

import logging

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.addressing import DEFAULT_ETHERNET_HOST, DEFAULT_ETHERNET_PORT
from stoner_measurement.instruments.temperature_controller import TemperatureController
from stoner_measurement.qt_compat import pyqtSlot
from stoner_measurement.ui.widgets import (
    FILTER_GPIB,
    FILTER_SERIAL,
    VisaResourceComboBox,
    VisaResourceStatus,
    load_connection_preferences,
    restore_preferred_address,
    selected_transport,
    set_address_widget_status,
    show_transport_widget,
)

logger = logging.getLogger(__name__)


class TemperatureConnectionMixin:
    """Build one connection form using the shared transport widgets."""

    def _build_connection_form(self) -> QWidget:
        """Build the Connection tab widget.

        Returns:
            (QWidget):
                The assembled connection tab.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        # Driver selection
        driver_group = QGroupBox("Instrument Driver")
        driver_form = QFormLayout(driver_group)

        self._driver_combo = QComboBox()
        self._driver_combo.setToolTip("Select the temperature controller driver")
        self._populate_driver_combo()
        driver_form.addRow("Driver:", self._driver_combo)

        # Transport type
        self._transport_combo = QComboBox()
        for label in ("Serial", "GPIB", "Ethernet", "Null (test)"):
            self._transport_combo.addItem(label)
        self._transport_combo.currentIndexChanged.connect(self._on_transport_changed)
        driver_form.addRow("Transport:", self._transport_combo)

        layout.addWidget(driver_group)

        # Transport-specific address fields
        self._address_group = QGroupBox("Connection Address")
        self._address_stack_layout = QVBoxLayout(self._address_group)

        self._serial_form_widget = self._build_serial_address_form()
        self._gpib_form_widget = self._build_gpib_address_form()
        self._ethernet_form_widget = self._build_ethernet_address_form()
        self._null_form_widget = QLabel("No address required for Null transport.")

        for w in (
            self._serial_form_widget,
            self._gpib_form_widget,
            self._ethernet_form_widget,
            self._null_form_widget,
        ):
            self._address_stack_layout.addWidget(w)
            w.hide()

        self._serial_form_widget.show()
        layout.addWidget(self._address_group)

        # Connect / Disconnect buttons
        btn_row = QHBoxLayout()
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect = QPushButton("Disconnect")
        self._btn_disconnect.setEnabled(False)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        btn_row.addWidget(self._btn_connect)
        btn_row.addWidget(self._btn_disconnect)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

        return widget

    def _build_serial_address_form(self) -> QWidget:
        """Build the serial-port address fields.

        Returns:
            (QWidget):
                Serial address form widget.
        """
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        self._serial_port_combo = VisaResourceComboBox(
            resource_filter=FILTER_SERIAL,
            placeholder="/dev/ttyUSB0",
            extra_resources=["/dev/ttyUSB0"],
            auto_refresh=False,
        )
        self._serial_baud_combo = QComboBox()
        for baud in (9600, 19200, 38400, 57600, 115200):
            self._serial_baud_combo.addItem(str(baud), baud)
        form.addRow("Port:", self._serial_port_combo)
        form.addRow("Baud rate:", self._serial_baud_combo)
        return w

    def _build_gpib_address_form(self) -> QWidget:
        """Build the GPIB address fields.

        Returns:
            (QWidget):
                GPIB address form widget.
        """
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        self._gpib_resource_combo = VisaResourceComboBox(
            resource_filter=FILTER_GPIB,
            placeholder="GPIB0::2::INSTR",
            extra_resources=["GPIB0::2::INSTR"],
            auto_refresh=False,
        )
        form.addRow("VISA resource:", self._gpib_resource_combo)
        return w

    def _build_ethernet_address_form(self) -> QWidget:
        """Build the Ethernet address fields.

        Returns:
            (QWidget):
                Ethernet address form widget.
        """
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        self._eth_host_edit = QLineEdit(DEFAULT_ETHERNET_HOST)
        self._eth_port_spin = QSpinBox()
        self._eth_port_spin.setRange(1, 65535)
        self._eth_port_spin.setValue(DEFAULT_ETHERNET_PORT)
        form.addRow("Host:", self._eth_host_edit)
        form.addRow("Port:", self._eth_port_spin)
        return w

    def _populate_driver_combo(self) -> None:
        """Populate the driver combo with discovered TemperatureController drivers."""
        self._driver_combo.clear()
        tc_drivers = self._driver_manager.drivers_by_type(TemperatureController)
        added = 0
        for name in sorted(tc_drivers):
            if not name.startswith("_"):
                driver_cls = tc_drivers[name]
                display_name = name
                if hasattr(driver_cls, "display_name"):
                    try:
                        display_name = str(driver_cls.display_name())
                    except Exception:
                        display_name = name
                self._driver_combo.addItem(display_name, driver_cls)
                self._driver_combo.setItemData(
                    self._driver_combo.count() - 1,
                    name,
                    Qt.ItemDataRole.UserRole + 1,
                )
                added += 1
        if added == 0:
            self._driver_combo.addItem("(no drivers found)", None)

    def _load_connection_preferences(self) -> None:
        load_connection_preferences(self)

    def _restore_preferred_address(self) -> None:
        restore_preferred_address(self)

    @pyqtSlot(int)
    def _on_transport_changed(self, index: int) -> None:
        """Show the address fields appropriate to the selected transport type.

        Args:
            index (int):
                Index of the selected transport in the transport combo box.
        """
        show_transport_widget(self, index)

    @pyqtSlot()
    def _on_connect(self) -> None:
        """Send selected connection settings to the engine and connect."""
        driver_cls = self._driver_combo.currentData()
        if driver_cls is None:
            return
        transport_index = self._transport_combo.currentIndex()
        self._set_address_widget_status(transport_index, VisaResourceStatus.CONNECTING)

        try:
            transport_name, address = selected_transport(self, transport_index)
            driver_name = self._driver_combo.currentData(Qt.ItemDataRole.UserRole + 1)
            resolved_driver_name = str(driver_name or self._driver_combo.currentText())
            self._engine.preferred_driver_name = resolved_driver_name
            self._engine.preferred_transport_name = transport_name
            self._engine.preferred_address = address
            self._service._check_connection(self._slot, transport_name, address)
            if not self._service.controller_enabled(self._slot):
                self._service.set_controller_enabled(self._slot, True)
            self._engine.connect_driver(
                driver_name=resolved_driver_name,
                transport_name=transport_name,
                address=address,
            )
        except Exception:
            logger.exception("Failed to connect temperature controller")
            self._set_address_widget_status(transport_index, VisaResourceStatus.ERROR)
            return

        self._sync_existing_connection_state()

    def _set_address_widget_status(self, transport_index: int, status: VisaResourceStatus) -> None:
        """Update the connection-status colour on the active address widget.

        Only :class:`VisaResourceComboBox` instances (serial and GPIB) support
        status colouring; other transport address widgets are left unchanged.

        Args:
            transport_index (int):
                Index of the currently selected transport.
            status (VisaResourceStatus):
                Status to apply.
        """
        set_address_widget_status(self, transport_index, status)

    def _selected_transport(self, index: int) -> tuple[str, str]:
        """Return selected transport type and address string.

        Args:
            index (int):
                Index of the selected transport in the transport combo box.

        Returns:
            (tuple[str, str]):
                Selected transport name and address.
        """
        return selected_transport(self, index)

    def _sync_driver_choice(self):
        """Reflect the live driver when a connection was opened by a plugin or script."""
        name = self._engine.connected_driver_name
        if name:
            index = self._driver_combo.findData(name, role=Qt.ItemDataRole.UserRole + 1)
            if index >= 0:
                self._driver_combo.setCurrentIndex(index)

    def store_preferences(self):
        """Save edited connection preferences even before an instrument is connected."""
        driver = self._driver_combo.currentData(Qt.ItemDataRole.UserRole + 1)
        self._engine.preferred_driver_name = str(driver or "")
        transport, address = selected_transport(self, self._transport_combo.currentIndex())
        self._engine.preferred_transport_name = transport
        self._engine.preferred_address = address


class TemperatureConnectionGroup(TemperatureConnectionMixin, QGroupBox):
    """An independently connected secondary slot using the same form as primary."""

    def __init__(self, service, slot, manager, parent=None):
        super().__init__(slot.title(), parent)
        self._service = service
        self._slot = slot
        self._engine = service.controller(slot)
        self._driver_manager = manager
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_connection_form())
        self._connection_status = QLabel()
        layout.addWidget(self._connection_status)
        self._load_connection_preferences()
        self._engine.publisher.connection_changed.connect(self._sync_existing_connection_state)
        self._engine.publisher.engine_status_changed.connect(self._status_changed)
        self._sync_existing_connection_state()

    def _status_changed(self, _status):
        self._sync_existing_connection_state()

    def _sync_existing_connection_state(self):
        self._sync_driver_choice()
        connected = self._engine.connected_driver is not None
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)
        self._connection_status.setText(self._engine.status.value)
        self._set_address_widget_status(
            self._transport_combo.currentIndex(),
            VisaResourceStatus.CONNECTED if connected else VisaResourceStatus.DISCONNECTED,
        )

    def _on_disconnect(self):
        try:
            self._engine.disconnect_instrument()
        except Exception as error:
            QMessageBox.warning(self, "Temperature controller", str(error))
