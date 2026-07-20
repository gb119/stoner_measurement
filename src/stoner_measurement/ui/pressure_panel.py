"""Non-blocking pressure controller panel window."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.addressing import DEFAULT_ETHERNET_HOST, DEFAULT_ETHERNET_PORT
from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.pressure_controller import (
    PressureGaugeController,
    PressureStatus,
)
from stoner_measurement.pressure_control.engine import PressureControllerEngine
from stoner_measurement.pressure_control.types import PressureEngineState, PressureEngineStatus
from stoner_measurement.qt_compat import pyqtSlot
from stoner_measurement.ui.widgets import (
    FILTER_GPIB,
    FILTER_SERIAL,
    VisaResourceComboBox,
    VisaResourceStatus,
    load_connection_preferences,
    restore_connection_address,
    restore_preferred_address,
    selected_transport,
    set_address_widget_status,
    show_transport_widget,
)

logger = logging.getLogger(__name__)

_STATUS_COLOURS: dict[PressureEngineStatus, str] = {
    PressureEngineStatus.STOPPED: "#888888",
    PressureEngineStatus.DISCONNECTED: "#cc4444",
    PressureEngineStatus.CONNECTED: "#cc8800",
    PressureEngineStatus.POLLING: "#44aa44",
    PressureEngineStatus.ERROR: "#cc0000",
}

_PRESSURE_STATUS_COLOURS: dict[PressureStatus | str, str] = {
    PressureStatus.OK: "#2e7d32",
    PressureStatus.UNDERRANGE: "#f9a825",
    PressureStatus.OVERRANGE: "#f9a825",
    PressureStatus.TRANSMITTER_ERROR: "#c62828",
    PressureStatus.SWITCHED_OFF: "#757575",
    PressureStatus.NO_TRANSMITTER: "#757575",
    PressureStatus.IDENTIFICATION_ERROR: "#c62828",
    PressureStatus.ITR_ERROR: "#c62828",
    PressureStatus.UNKNOWN: "#c62828",
}


def _colour_dot(colour: str, size: int = 12) -> str:
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'border-radius:{size // 2}px;background:{colour};"></span>'
    )


def _line_edit(placeholder: str = "") -> QWidget:
    from qtpy.QtWidgets import QLineEdit

    widget = QLineEdit()
    widget.setPlaceholderText(placeholder)
    widget.setText(placeholder)
    return widget


class PressureControlPanel(QWidget):
    """Non-blocking window for pressure controller configuration and monitoring."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pressure Control")
        self.setMinimumSize(620, 420)
        self.setWindowFlags(Qt.WindowType.Window)

        self._engine = PressureControllerEngine.instance()
        self._driver_manager = InstrumentDriverManager()
        self._driver_manager.discover()
        self._allow_exit_close = False
        self._channel_rows: dict[int, tuple[QLabel, QLabel, QLabel]] = {}

        self._build_ui()
        self._load_connection_preferences()
        self._connect_engine_signals()

    def show_and_raise(self) -> None:
        """Show the window and raise it above other top-level windows."""
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Hide the panel instead of destroying it when the user closes it."""
        if self._allow_exit_close:
            logger.info("Closing pressure control panel during application shutdown.")
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def showEvent(self, event) -> None:  # type: ignore[override]
        """Refresh the UI from any existing engine connection when shown."""
        super().showEvent(event)
        self._sync_existing_connection_state()

    def _build_ui(self) -> None:
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_connection_tab(), "Connection")
        self._tabs.addTab(self._build_monitor_tab(), "Monitor")

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 4)
        root.setSpacing(4)
        root.addWidget(self._tabs)
        root.addWidget(self._build_status_bar())
        root.addLayout(self._build_hide_button_row())
        self.setLayout(root)

    def _build_hide_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()
        self._btn_hide = QPushButton("Hide")
        self._btn_hide.clicked.connect(self.hide)
        row.addWidget(self._btn_hide)
        return row

    def _build_connection_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        driver_group = QGroupBox("Instrument Driver")
        driver_form = QFormLayout(driver_group)
        self._driver_combo = QComboBox()
        self._populate_driver_combo()
        driver_form.addRow("Driver:", self._driver_combo)

        self._transport_combo = QComboBox()
        for label in ("Serial", "GPIB", "Ethernet", "Null (test)"):
            self._transport_combo.addItem(label)
        self._transport_combo.currentIndexChanged.connect(self._on_transport_changed)
        driver_form.addRow("Transport:", self._transport_combo)
        layout.addWidget(driver_group)

        self._address_group = QGroupBox("Connection Address")
        address_stack = QVBoxLayout(self._address_group)
        self._serial_form_widget = self._build_serial_address_form()
        self._gpib_form_widget = self._build_gpib_address_form()
        self._ethernet_form_widget = self._build_ethernet_address_form()
        self._null_form_widget = QLabel("No address required for Null transport.")
        for child in (
            self._serial_form_widget,
            self._gpib_form_widget,
            self._ethernet_form_widget,
            self._null_form_widget,
        ):
            address_stack.addWidget(child)
            child.hide()
        self._serial_form_widget.show()
        layout.addWidget(self._address_group)

        button_row = QHBoxLayout()
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect = QPushButton("Disconnect")
        self._btn_disconnect.setEnabled(False)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        self._btn_save_configuration = QPushButton("Save Settings to YAML")
        self._btn_save_configuration.clicked.connect(self._on_save_configuration)
        button_row.addWidget(self._btn_connect)
        button_row.addWidget(self._btn_disconnect)
        button_row.addWidget(self._btn_save_configuration)
        button_row.addStretch()
        layout.addLayout(button_row)
        layout.addStretch()
        return widget

    def _build_serial_address_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)
        self._serial_port_combo = VisaResourceComboBox(
            resource_filter=FILTER_SERIAL,
            placeholder="/dev/ttyUSB0",
            extra_resources=["/dev/ttyUSB0"],
        )
        self._serial_baud_combo = QComboBox()
        for baud in (9600, 19200, 38400):
            self._serial_baud_combo.addItem(str(baud), baud)
        form.addRow("Port:", self._serial_port_combo)
        form.addRow("Baud rate:", self._serial_baud_combo)
        return widget

    def _build_gpib_address_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)
        self._gpib_resource_combo = VisaResourceComboBox(
            resource_filter=FILTER_GPIB,
            placeholder="GPIB0::1::INSTR",
            extra_resources=["GPIB0::1::INSTR"],
        )
        form.addRow("VISA resource:", self._gpib_resource_combo)
        return widget

    def _build_ethernet_address_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)
        self._eth_host_edit = _line_edit(DEFAULT_ETHERNET_HOST)
        self._eth_port_spin = QSpinBox()
        self._eth_port_spin.setRange(1, 65535)
        self._eth_port_spin.setValue(DEFAULT_ETHERNET_PORT)
        form.addRow("Host:", self._eth_host_edit)
        form.addRow("Port:", self._eth_port_spin)
        return widget

    def _build_monitor_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        readings_group = QGroupBox("Pressure Readings")
        grid = QGridLayout(readings_group)
        for col, label in enumerate(("Channel", "Pressure", "Status")):
            header = QLabel(f"<b>{label}</b>")
            grid.addWidget(header, 0, col)
        for channel in range(1, 4):
            channel_label = QLabel(str(channel))
            pressure_label = QLabel("—")
            status_label = QLabel("—")
            grid.addWidget(channel_label, channel, 0)
            grid.addWidget(pressure_label, channel, 1)
            grid.addWidget(status_label, channel, 2)
            self._channel_rows[channel] = (channel_label, pressure_label, status_label)
        layout.addWidget(readings_group)
        button_row = QHBoxLayout()
        self._btn_read_state = QPushButton("Read Now")
        self._btn_read_state.clicked.connect(self._on_read_state)
        button_row.addWidget(self._btn_read_state)
        button_row.addStretch()
        layout.addLayout(button_row)
        layout.addStretch()
        return widget

    def _build_status_bar(self) -> QWidget:
        status_bar = QWidget()
        status_bar.setFixedHeight(28)
        layout = QHBoxLayout(status_bar)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(12)
        self._status_label = QLabel("Engine: —")
        self._driver_label = QLabel("Driver: —")
        self._updated_label = QLabel("Last updated: —")
        layout.addWidget(self._status_label)
        layout.addWidget(self._driver_label)
        layout.addStretch()
        layout.addWidget(self._updated_label)
        return status_bar

    def _connect_engine_signals(self) -> None:
        pub = self._engine.publisher
        pub.state_updated.connect(self._on_state_updated)
        pub.engine_status_changed.connect(self._on_engine_status_changed)
        pub.connection_changed.connect(self._on_connection_changed)
        self._on_engine_status_changed(self._engine.status)

    @pyqtSlot(PressureEngineStatus)
    def _on_engine_status_changed(self, status: PressureEngineStatus) -> None:
        colour = _STATUS_COLOURS.get(status, "#888888")
        self._status_label.setText(f"{_colour_dot(colour)} Engine: {status.value}")
        connected = status in (PressureEngineStatus.CONNECTED, PressureEngineStatus.POLLING)
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)

    @pyqtSlot(PressureEngineState)
    def _on_state_updated(self, state: PressureEngineState) -> None:
        self._driver_label.setText(f"Driver: {state.driver_name or '—'}")
        self._updated_label.setText(f"Last updated: {datetime.now(tz=UTC).strftime('%H:%M:%S')}")
        for channel, (_, pressure_label, status_label) in self._channel_rows.items():
            reading = state.readings.get(channel)
            if reading is None:
                pressure_label.setText("—")
                status_label.setText("—")
                status_label.setStyleSheet("")
                continue
            unit = reading.unit.value if hasattr(reading.unit, "value") else str(reading.unit)
            pressure_label.setText("—" if reading.value is None else f"{reading.value:.4E} {unit}")
            status = reading.status
            status_text = status.value.replace("_", " ") if hasattr(status, "value") else str(status)
            status_label.setText(status_text)
            bg = _PRESSURE_STATUS_COLOURS.get(status, "#757575")
            status_label.setStyleSheet(f"color: white; background: {bg}; padding: 2px 6px; border-radius: 3px;")

    @pyqtSlot()
    def _on_connection_changed(self) -> None:
        self._sync_existing_connection_state()

    def _populate_driver_combo(self) -> None:
        self._driver_combo.clear()
        pressure_drivers = self._driver_manager.drivers_by_type(PressureGaugeController)
        added = 0
        for name in sorted(pressure_drivers):
            if name.startswith("_"):
                continue
            driver_cls = pressure_drivers[name]
            capabilities = getattr(driver_cls, "_CAPABILITIES", None)
            if capabilities is not None and getattr(capabilities, "analogue_only", False):
                continue
            self._driver_combo.addItem(driver_cls.display_name(), driver_cls)
            self._driver_combo.setItemData(self._driver_combo.count() - 1, name, Qt.ItemDataRole.UserRole + 1)
            added += 1
        if added == 0:
            self._driver_combo.addItem("(no drivers found)", None)

    def _load_connection_preferences(self) -> None:
        load_connection_preferences(self)

    def _restore_preferred_address(self) -> None:
        restore_preferred_address(self)

    @pyqtSlot(int)
    def _on_transport_changed(self, index: int) -> None:
        show_transport_widget(self, index)

    @pyqtSlot()
    def _on_connect(self) -> None:
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
            self._engine.save_configuration()
            self._engine.connect_driver(resolved_driver_name, transport_name, address)
        except Exception as exc:
            logger.exception("Failed to connect pressure driver")
            self._set_address_widget_status(transport_index, VisaResourceStatus.ERROR)
            QMessageBox.critical(self, "Pressure Controller", f"Failed to connect pressure controller:\n{exc}")
            return
        self._sync_existing_connection_state()

    def _set_address_widget_status(self, transport_index: int, status: VisaResourceStatus) -> None:
        set_address_widget_status(self, transport_index, status)

    @pyqtSlot()
    def _on_disconnect(self) -> None:
        self._engine.disconnect_instrument()
        self._apply_disconnected_ui_state()

    def _apply_disconnected_ui_state(self) -> None:
        self._set_address_widget_status(2, VisaResourceStatus.DISCONNECTED)
        self._set_address_widget_status(3, VisaResourceStatus.DISCONNECTED)
        self._serial_port_combo.set_status(VisaResourceStatus.DISCONNECTED)
        self._gpib_resource_combo.set_status(VisaResourceStatus.DISCONNECTED)

    def _sync_existing_connection_state(self) -> None:
        transport_name = self._engine.connected_transport_name
        address = self._engine.connected_address
        if self._engine.connected_driver is None:
            self._apply_disconnected_ui_state()
            self._on_engine_status_changed(self._engine.status)
            return
        if transport_name:
            self._sync_live_connection_widgets(transport_name, address or "")
        state = self._engine.read_controller_state()
        if state is not None:
            self._on_state_updated(state)

    def _sync_live_connection_widgets(self, transport_name: str, address: str) -> None:
        transport_index = self._transport_combo.findText(transport_name)
        if transport_index < 0:
            return
        self._transport_combo.setCurrentIndex(transport_index)
        restore_connection_address(self, transport_name, address)
        self._set_address_widget_status(transport_index, VisaResourceStatus.CONNECTED)
        self._on_engine_status_changed(self._engine.status)

    @pyqtSlot()
    def _on_read_state(self) -> None:
        state = self._engine.read_controller_state()
        if state is None:
            QMessageBox.warning(self, "Pressure State", "No instrument connected or read failed.")

    @pyqtSlot()
    def _on_save_configuration(self) -> None:
        try:
            driver_name = self._driver_combo.currentData(Qt.ItemDataRole.UserRole + 1)
            self._engine.preferred_driver_name = str(driver_name or self._driver_combo.currentText())
            transport_name, address = selected_transport(self, self._transport_combo.currentIndex())
            self._engine.preferred_transport_name = transport_name
            self._engine.preferred_address = address
            path = self._engine.save_configuration()
        except Exception as exc:
            QMessageBox.critical(self, "Save Configuration", f"Failed to save configuration:\n{exc}")
            return
        QMessageBox.information(self, "Save Configuration", f"Configuration saved to:\n{path}")
