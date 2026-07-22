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
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.addressing import DEFAULT_ETHERNET_HOST, DEFAULT_ETHERNET_PORT
from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.mass_flow_controller import MassFlowController
from stoner_measurement.instruments.pressure_controller import (
    PressureGaugeController,
    PressureStatus,
)
from stoner_measurement.pressure_control.engine import PressureControllerEngine
from stoner_measurement.pressure_control.types import PressureEngineState, PressureEngineStatus
from stoner_measurement.qt_compat import pyqtSlot
from stoner_measurement.ui.plot_widget import PlotWidget
from stoner_measurement.ui.time_utils import format_local_time
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

_CHART_DURATIONS: list[tuple[int, str]] = [
    (5, "5 min"),
    (10, "10 min"),
    (30, "30 min"),
    (60, "60 min"),
]


def _colour_dot(colour: str, size: int = 12) -> str:
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'border-radius:{size // 2}px;background:{colour};"></span>'
    )


def _line_edit(placeholder: str = "") -> QLineEdit:
    widget = QLineEdit()
    widget.setPlaceholderText(placeholder)
    widget.setText(placeholder)
    return widget


class PressureControlPanel(QWidget):
    """Non-blocking window for pressure controller and MFC monitoring."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pressure Control")
        self.setMinimumSize(820, 620)
        self.setWindowFlags(Qt.WindowType.Window)

        self._engine = PressureControllerEngine.instance()
        self._driver_manager = InstrumentDriverManager()
        self._driver_manager.discover()
        self._allow_exit_close = False
        self._channel_rows: dict[int, tuple[QLabel, QLabel, QLabel]] = {}
        self._chart_history: dict[str, list[tuple[float, float]]] = {}
        self._chart_duration_min = _CHART_DURATIONS[1][0]
        self._mfc_row_widgets: dict[int, dict[str, QWidget]] = {}
        self._legend_items: dict[str, QTreeWidgetItem] = {}

        self._build_ui()
        self._load_connection_preferences()
        self._load_mfc_preferences()
        self._connect_engine_signals()

    def show_and_raise(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._allow_exit_close:
            logger.info("Closing pressure control panel during application shutdown.")
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._sync_existing_connection_state()

    def _build_ui(self) -> None:
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_connection_tab(), "Connection")
        self._tabs.addTab(self._build_monitor_tab(), "Monitor")
        self._tabs.addTab(self._build_chart_tab(), "Chart")

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
        layout.addWidget(self._build_pressure_connection_group())
        layout.addWidget(self._build_mfc_connection_group())
        save_row = QHBoxLayout()
        self._btn_save_configuration = QPushButton("Save Settings to YAML")
        self._btn_save_configuration.clicked.connect(self._on_save_configuration)
        save_row.addWidget(self._btn_save_configuration)
        save_row.addStretch()
        layout.addLayout(save_row)
        layout.addStretch()
        return widget

    def _build_pressure_connection_group(self) -> QWidget:
        group = QGroupBox("Pressure Gauge Controller")
        layout = QVBoxLayout(group)

        driver_form = QFormLayout()
        self._driver_combo = QComboBox()
        self._populate_pressure_driver_combo()
        driver_form.addRow("Driver:", self._driver_combo)
        self._transport_combo = QComboBox()
        for label in ("Serial", "GPIB", "Ethernet", "Null (test)"):
            self._transport_combo.addItem(label)
        self._transport_combo.currentIndexChanged.connect(self._on_transport_changed)
        driver_form.addRow("Transport:", self._transport_combo)
        layout.addLayout(driver_form)

        self._address_group = QGroupBox("Pressure Gauge Address")
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
        self._btn_connect = QPushButton("Connect Gauge")
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect = QPushButton("Disconnect Gauge")
        self._btn_disconnect.setEnabled(False)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        button_row.addWidget(self._btn_connect)
        button_row.addWidget(self._btn_disconnect)
        button_row.addStretch()
        layout.addLayout(button_row)
        return group

    def _build_mfc_connection_group(self) -> QWidget:
        group = QGroupBox("Mass Flow Controller")
        layout = QVBoxLayout(group)

        driver_form = QFormLayout()
        self._mfc_driver_combo = QComboBox()
        self._populate_mfc_driver_combo()
        driver_form.addRow("Driver:", self._mfc_driver_combo)
        self._mfc_transport_combo = QComboBox()
        for label in ("Serial", "GPIB", "Ethernet", "Null (test)"):
            self._mfc_transport_combo.addItem(label)
        self._mfc_transport_combo.currentIndexChanged.connect(self._on_mfc_transport_changed)
        driver_form.addRow("Transport:", self._mfc_transport_combo)
        layout.addLayout(driver_form)

        self._mfc_address_group = QGroupBox("MFC Address")
        address_stack = QVBoxLayout(self._mfc_address_group)
        self._mfc_serial_form_widget = self._build_mfc_serial_address_form()
        self._mfc_gpib_form_widget = self._build_mfc_gpib_address_form()
        self._mfc_ethernet_form_widget = self._build_mfc_ethernet_address_form()
        self._mfc_null_form_widget = QLabel("No address required for Null transport.")
        for child in (
            self._mfc_serial_form_widget,
            self._mfc_gpib_form_widget,
            self._mfc_ethernet_form_widget,
            self._mfc_null_form_widget,
        ):
            address_stack.addWidget(child)
            child.hide()
        self._mfc_serial_form_widget.show()
        layout.addWidget(self._mfc_address_group)

        button_row = QHBoxLayout()
        self._btn_mfc_connect = QPushButton("Connect MFC")
        self._btn_mfc_connect.clicked.connect(self._on_connect_mfc)
        self._btn_mfc_disconnect = QPushButton("Disconnect MFC")
        self._btn_mfc_disconnect.setEnabled(False)
        self._btn_mfc_disconnect.clicked.connect(self._on_disconnect_mfc)
        button_row.addWidget(self._btn_mfc_connect)
        button_row.addWidget(self._btn_mfc_disconnect)
        button_row.addStretch()
        layout.addLayout(button_row)
        return group

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

    def _build_mfc_serial_address_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)
        self._mfc_serial_port_combo = VisaResourceComboBox(
            resource_filter=FILTER_SERIAL,
            placeholder="/dev/ttyUSB1",
            extra_resources=["/dev/ttyUSB1"],
        )
        self._mfc_serial_baud_combo = QComboBox()
        for baud in (9600, 19200, 38400):
            self._mfc_serial_baud_combo.addItem(str(baud), baud)
        form.addRow("Port:", self._mfc_serial_port_combo)
        form.addRow("Baud rate:", self._mfc_serial_baud_combo)
        return widget

    def _build_mfc_gpib_address_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)
        self._mfc_gpib_resource_combo = VisaResourceComboBox(
            resource_filter=FILTER_GPIB,
            placeholder="GPIB0::2::INSTR",
            extra_resources=["GPIB0::2::INSTR"],
        )
        form.addRow("VISA resource:", self._mfc_gpib_resource_combo)
        return widget

    def _build_mfc_ethernet_address_form(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)
        self._mfc_eth_host_edit = _line_edit(DEFAULT_ETHERNET_HOST)
        self._mfc_eth_port_spin = QSpinBox()
        self._mfc_eth_port_spin.setRange(1, 65535)
        self._mfc_eth_port_spin.setValue(DEFAULT_ETHERNET_PORT)
        form.addRow("Host:", self._mfc_eth_host_edit)
        form.addRow("Port:", self._mfc_eth_port_spin)
        return widget

    def _build_monitor_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        readings_group = QGroupBox("Pressure Readings")
        grid = QGridLayout(readings_group)
        for col, label in enumerate(("Channel", "Pressure", "Status")):
            grid.addWidget(QLabel(f"<b>{label}</b>"), 0, col)
        for channel in range(1, 4):
            channel_label = QLabel(str(channel))
            pressure_label = QLabel("—")
            status_label = QLabel("—")
            grid.addWidget(channel_label, channel, 0)
            grid.addWidget(pressure_label, channel, 1)
            grid.addWidget(status_label, channel, 2)
            self._channel_rows[channel] = (channel_label, pressure_label, status_label)
        layout.addWidget(readings_group)

        gauge_group = QGroupBox("Gauge Channel Control")
        gauge_layout = QVBoxLayout(gauge_group)
        self._gauge_table = QTableWidget(0, 3, gauge_group)
        self._gauge_table.setHorizontalHeaderLabels(["Channel", "Enabled", "Action"])
        gauge_layout.addWidget(self._gauge_table)

        interlock_group = QGroupBox("Interlocks")
        interlock_layout = QVBoxLayout(interlock_group)
        self._interlock_table = QTableWidget(0, 2, interlock_group)
        self._interlock_table.setHorizontalHeaderLabels(["Interlock", "State"])
        interlock_layout.addWidget(self._interlock_table)
        interlock_group.hide()
        self._interlock_group = interlock_group

        self._monitor_aux_layout = QHBoxLayout()
        self._monitor_aux_layout.addWidget(gauge_group, stretch=1)
        self._monitor_aux_layout.addWidget(interlock_group, stretch=1)
        layout.addLayout(self._monitor_aux_layout)

        mfc_group = QGroupBox("Mass Flow Controller")
        mfc_layout = QVBoxLayout(mfc_group)
        self._mfc_table = QTableWidget(0, 7, mfc_group)
        self._mfc_table.setHorizontalHeaderLabels(
            [
                "Channel",
                "Actual Flow",
                "Set Flow",
                "Apply Flow",
                "Target Pressure",
                "Apply Pressure",
                "Unit",
            ]
        )
        mfc_layout.addWidget(self._mfc_table)
        layout.addWidget(mfc_group, stretch=1)

        button_row = QHBoxLayout()
        self._btn_read_state = QPushButton("Read Now")
        self._btn_read_state.clicked.connect(self._on_read_state)
        button_row.addWidget(self._btn_read_state)
        button_row.addStretch()
        layout.addLayout(button_row)
        return widget

    def _build_chart_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Duration:"))
        self._duration_combo = QComboBox()
        for minutes, label in _CHART_DURATIONS:
            self._duration_combo.addItem(label, minutes)
        self._duration_combo.setCurrentIndex(1)
        self._duration_combo.currentIndexChanged.connect(self._on_duration_changed)
        controls.addWidget(self._duration_combo)
        controls.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._on_clear_chart)
        controls.addWidget(clear_btn)
        layout.addLayout(controls)
        content = QHBoxLayout()
        self._chart_widget = PlotWidget(show_axis_controls=False, show_trace_table=False)
        self._chart_widget.set_default_axis_labels("Time (s ago)", "Pressure")
        self._chart_widget.set_axis_log_scale("left", True)
        self._chart_widget.add_y_axis("flow", "Flow")
        content.addWidget(self._chart_widget, stretch=4)
        self._legend_tree = QTreeWidget()
        self._legend_tree.setHeaderLabels(["Trace", "Value"])
        self._legend_tree.setMinimumWidth(220)
        self._legend_tree.itemChanged.connect(self._on_legend_item_changed)
        content.addWidget(self._legend_tree, stretch=1)
        layout.addLayout(content)
        return widget

    def _build_status_bar(self) -> QWidget:
        status_bar = QWidget()
        status_bar.setFixedHeight(28)
        layout = QHBoxLayout(status_bar)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(12)
        self._status_label = QLabel("Engine: —")
        self._driver_label = QLabel("Gauge: —")
        self._mfc_driver_label = QLabel("MFC: —")
        self._updated_label = QLabel("Last updated: —")
        layout.addWidget(self._status_label)
        layout.addWidget(self._driver_label)
        layout.addWidget(self._mfc_driver_label)
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
        self._btn_connect.setEnabled(
            self._engine.connected_driver is None and status != PressureEngineStatus.STOPPED
        )
        self._btn_disconnect.setEnabled(self._engine.connected_driver is not None)
        self._btn_mfc_connect.setEnabled(
            self._engine.connected_mfc_driver is None and status != PressureEngineStatus.STOPPED
        )
        self._btn_mfc_disconnect.setEnabled(self._engine.connected_mfc_driver is not None)
        self._refresh_connection_indicators()

    @pyqtSlot(PressureEngineState)
    def _on_state_updated(self, state: PressureEngineState) -> None:
        self._driver_label.setText(f"Gauge: {state.driver_name or '—'}")
        self._mfc_driver_label.setText(f"MFC: {state.mfc_driver_name or '—'}")
        self._updated_label.setText(
            f"Last updated: {format_local_time(datetime.now(tz=UTC).astimezone())}"
        )
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
            status_text = (
                status.value.replace("_", " ") if hasattr(status, "value") else str(status)
            )
            status_label.setText(status_text)
            bg = _PRESSURE_STATUS_COLOURS.get(status, "#757575")
            status_label.setStyleSheet(
                f"color: white; background: {bg}; padding: 2px 6px; border-radius: 3px;"
            )
        self._refresh_gauge_table(state)
        self._refresh_interlock_table(state)
        self._refresh_mfc_table(state)
        self._append_chart_state(state)
        self._refresh_chart()
        self._refresh_connection_indicators()

    @pyqtSlot()
    def _on_connection_changed(self) -> None:
        self._sync_existing_connection_state()

    def _populate_pressure_driver_combo(self) -> None:
        self._driver_combo.clear()
        pressure_drivers = self._driver_manager.drivers_by_type(PressureGaugeController)
        for name in sorted(pressure_drivers):
            driver_cls = pressure_drivers[name]
            capabilities = getattr(driver_cls, "_CAPABILITIES", None)
            if capabilities is not None and getattr(capabilities, "analogue_only", False):
                continue
            self._driver_combo.addItem(driver_cls.display_name(), driver_cls)
            self._driver_combo.setItemData(
                self._driver_combo.count() - 1, name, Qt.ItemDataRole.UserRole + 1
            )
        if self._driver_combo.count() == 0:
            self._driver_combo.addItem("(no drivers found)", None)

    def _populate_mfc_driver_combo(self) -> None:
        self._mfc_driver_combo.clear()
        mfc_drivers = self._driver_manager.drivers_by_type(MassFlowController)
        for name in sorted(mfc_drivers):
            driver_cls = mfc_drivers[name]
            self._mfc_driver_combo.addItem(driver_cls.display_name(), driver_cls)
            self._mfc_driver_combo.setItemData(
                self._mfc_driver_combo.count() - 1, name, Qt.ItemDataRole.UserRole + 1
            )
        if self._mfc_driver_combo.count() == 0:
            self._mfc_driver_combo.addItem("(no drivers found)", None)

    def _load_connection_preferences(self) -> None:
        load_connection_preferences(self)
        restore_preferred_address(self)

    def _load_mfc_preferences(self) -> None:
        if self._engine.preferred_mfc_driver_name:
            index = self._mfc_driver_combo.findData(
                self._engine.preferred_mfc_driver_name, Qt.ItemDataRole.UserRole + 1
            )
            if index >= 0:
                self._mfc_driver_combo.setCurrentIndex(index)
        index = self._mfc_transport_combo.findText(self._engine.preferred_mfc_transport_name)
        if index >= 0:
            self._mfc_transport_combo.setCurrentIndex(index)
        self._apply_mfc_address(
            self._engine.preferred_mfc_transport_name, self._engine.preferred_mfc_address
        )

    @pyqtSlot(int)
    def _on_transport_changed(self, index: int) -> None:
        show_transport_widget(self, index)

    @pyqtSlot(int)
    def _on_mfc_transport_changed(self, index: int) -> None:
        for widget in (
            self._mfc_serial_form_widget,
            self._mfc_gpib_form_widget,
            self._mfc_ethernet_form_widget,
            self._mfc_null_form_widget,
        ):
            widget.hide()
        (
            self._mfc_serial_form_widget,
            self._mfc_gpib_form_widget,
            self._mfc_ethernet_form_widget,
            self._mfc_null_form_widget,
        )[index].show()

    @pyqtSlot()
    def _on_connect(self) -> None:
        if self._driver_combo.currentData() is None:
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
            QMessageBox.critical(
                self, "Pressure Controller", f"Failed to connect pressure controller:\n{exc}"
            )
            return
        self._sync_existing_connection_state()

    @pyqtSlot()
    def _on_connect_mfc(self) -> None:
        if self._mfc_driver_combo.currentData() is None:
            return
        transport_index = self._mfc_transport_combo.currentIndex()
        self._set_mfc_address_widget_status(transport_index, VisaResourceStatus.CONNECTING)
        try:
            transport_name, address = self._selected_mfc_transport()
            driver_name = self._mfc_driver_combo.currentData(Qt.ItemDataRole.UserRole + 1)
            resolved_driver_name = str(driver_name or self._mfc_driver_combo.currentText())
            self._engine.preferred_mfc_driver_name = resolved_driver_name
            self._engine.preferred_mfc_transport_name = transport_name
            self._engine.preferred_mfc_address = address
            self._engine.save_configuration()
            self._engine.connect_mfc_driver(resolved_driver_name, transport_name, address)
        except Exception as exc:
            logger.exception("Failed to connect MFC driver")
            self._set_mfc_address_widget_status(transport_index, VisaResourceStatus.ERROR)
            QMessageBox.critical(
                self, "Mass Flow Controller", f"Failed to connect mass flow controller:\n{exc}"
            )
            return
        self._sync_existing_connection_state()

    def _set_address_widget_status(self, transport_index: int, status: VisaResourceStatus) -> None:
        set_address_widget_status(self, transport_index, status)

    @pyqtSlot()
    def _on_disconnect(self) -> None:
        self._engine.disconnect_instrument()
        self._apply_disconnected_ui_state()

    @pyqtSlot()
    def _on_disconnect_mfc(self) -> None:
        self._engine.disconnect_mfc_instrument()
        self._apply_mfc_disconnected_ui_state()

    def _apply_disconnected_ui_state(self) -> None:
        self._set_address_widget_status(2, VisaResourceStatus.DISCONNECTED)
        self._set_address_widget_status(3, VisaResourceStatus.DISCONNECTED)
        self._serial_port_combo.set_status(VisaResourceStatus.DISCONNECTED)
        self._gpib_resource_combo.set_status(VisaResourceStatus.DISCONNECTED)

    def _apply_mfc_disconnected_ui_state(self) -> None:
        for index in range(4):
            self._set_mfc_address_widget_status(index, VisaResourceStatus.DISCONNECTED)

    def _set_mfc_address_widget_status(
        self, transport_index: int, status: VisaResourceStatus
    ) -> None:
        if transport_index == 0:
            self._mfc_serial_port_combo.set_status(status)
        elif transport_index == 1:
            self._mfc_gpib_resource_combo.set_status(status)
        else:
            widget = (
                self._mfc_ethernet_form_widget
                if transport_index == 2
                else self._mfc_null_form_widget
            )
            backgrounds = {
                VisaResourceStatus.DISCONNECTED: "",
                VisaResourceStatus.CONNECTING: "#fff3cd",
                VisaResourceStatus.CONNECTED: "#90ee90",
                VisaResourceStatus.ERROR: "#f8d7da",
            }
            background = backgrounds[status]
            widget.setStyleSheet(
                f"QWidget {{ background-color: {background}; }}" if background else ""
            )

    def _refresh_connection_indicators(self) -> None:
        if self._engine.connected_driver is not None or self._engine.pressure_has_error:
            pressure_status = (
                VisaResourceStatus.ERROR
                if self._engine.pressure_has_error
                else VisaResourceStatus.CONNECTED
            )
            self._set_address_widget_status(self._transport_combo.currentIndex(), pressure_status)
        if self._engine.connected_mfc_driver is not None or self._engine.mfc_has_error:
            mfc_status = (
                VisaResourceStatus.ERROR
                if self._engine.mfc_has_error
                else VisaResourceStatus.CONNECTED
            )
            self._set_mfc_address_widget_status(
                self._mfc_transport_combo.currentIndex(), mfc_status
            )

    def _sync_existing_connection_state(self) -> None:
        if self._engine.connected_driver is None:
            self._apply_disconnected_ui_state()
            if self._engine.pressure_has_error:
                self._set_address_widget_status(
                    self._transport_combo.currentIndex(), VisaResourceStatus.ERROR
                )
        else:
            transport_name = self._engine.connected_transport_name or "Null (test)"
            address = self._engine.connected_address or ""
            transport_index = self._transport_combo.findText(transport_name)
            if transport_index >= 0:
                self._transport_combo.setCurrentIndex(transport_index)
                restore_connection_address(self, transport_name, address)
                status = (
                    VisaResourceStatus.ERROR
                    if self._engine.pressure_has_error
                    else VisaResourceStatus.CONNECTED
                )
                self._set_address_widget_status(transport_index, status)
        if self._engine.connected_mfc_driver is None:
            self._apply_mfc_disconnected_ui_state()
            if self._engine.mfc_has_error:
                self._set_mfc_address_widget_status(
                    self._mfc_transport_combo.currentIndex(), VisaResourceStatus.ERROR
                )
        else:
            self._apply_mfc_address(
                self._engine.connected_mfc_transport_name or "Null (test)",
                self._engine.connected_mfc_address or "",
            )
            transport_index = self._mfc_transport_combo.currentIndex()
            status = (
                VisaResourceStatus.ERROR
                if self._engine.mfc_has_error
                else VisaResourceStatus.CONNECTED
            )
            self._set_mfc_address_widget_status(transport_index, status)
        self._on_engine_status_changed(self._engine.status)
        state = self._engine.read_controller_state()
        if state is not None:
            self._on_state_updated(state)

    def _selected_mfc_transport(self) -> tuple[str, str]:
        transport_name = self._mfc_transport_combo.currentText()
        if transport_name == "Serial":
            port = (
                self._mfc_serial_port_combo.current_resource()
                or self._mfc_serial_port_combo.currentText()
            )
            baud = int(self._mfc_serial_baud_combo.currentData() or 9600)
            return transport_name, f"port={port};baud={baud}"
        if transport_name == "GPIB":
            resource = (
                self._mfc_gpib_resource_combo.current_resource()
                or self._mfc_gpib_resource_combo.currentText()
            )
            return transport_name, resource
        if transport_name == "Ethernet":
            return (
                transport_name,
                f"{self._mfc_eth_host_edit.text().strip()}:{self._mfc_eth_port_spin.value()}",
            )
        return transport_name, ""

    def _apply_mfc_address(self, transport_name: str, address: str) -> None:
        transport_index = self._mfc_transport_combo.findText(transport_name)
        if transport_index >= 0:
            self._mfc_transport_combo.setCurrentIndex(transport_index)
        if transport_name == "Serial":
            parts = dict(part.split("=", 1) for part in address.split(";") if "=" in part)
            self._mfc_serial_port_combo.setCurrentText(parts.get("port", ""))
            try:
                baud = int(parts.get("baud", "9600"))
            except ValueError:
                baud = 9600
            baud_index = self._mfc_serial_baud_combo.findData(baud)
            if baud_index >= 0:
                self._mfc_serial_baud_combo.setCurrentIndex(baud_index)
        elif transport_name == "GPIB":
            self._mfc_gpib_resource_combo.setCurrentText(address)
        elif transport_name == "Ethernet" and ":" in address:
            host, port = address.rsplit(":", 1)
            self._mfc_eth_host_edit.setText(host)
            try:
                self._mfc_eth_port_spin.setValue(int(port))
            except ValueError:
                pass

    def _refresh_gauge_table(self, state: PressureEngineState) -> None:
        channels = sorted(set(state.readings) | set(state.gauge_channel_enabled))
        self._gauge_table.setRowCount(len(channels))
        for row, channel in enumerate(channels):
            self._gauge_table.setItem(row, 0, QTableWidgetItem(str(channel)))
            enabled = state.gauge_channel_enabled.get(channel)
            text = "On" if enabled else "Off" if enabled is not None else "Unknown"
            self._gauge_table.setItem(row, 1, QTableWidgetItem(text))
            button = QPushButton("Disable" if enabled is not False else "Enable")
            button.clicked.connect(
                lambda _checked=False, ch=channel, en=enabled is False: self._set_gauge_channel(
                    ch, en
                )
            )
            self._gauge_table.setCellWidget(row, 2, button)

    def _refresh_interlock_table(self, state: PressureEngineState) -> None:
        self._interlock_group.setVisible(bool(state.interlocks))
        self._interlock_table.setRowCount(len(state.interlocks))
        for row, (name, value) in enumerate(sorted(state.interlocks.items())):
            if isinstance(value, bool):
                state_text = "OK" if value else "Tripped"
            elif value is None:
                state_text = "Unknown"
            else:
                state_text = str(value)
            self._interlock_table.setItem(row, 0, QTableWidgetItem(str(name)))
            self._interlock_table.setItem(row, 1, QTableWidgetItem(state_text))

    def _refresh_mfc_table(self, state: PressureEngineState) -> None:
        channels = sorted(
            set(state.flow_actual) | set(state.flow_setpoints) | set(state.target_pressures)
        )
        existing = set(self._mfc_row_widgets)
        self._mfc_table.setRowCount(len(channels))
        unit_text = "" if state.flow_unit is None else str(state.flow_unit)
        for row, channel in enumerate(channels):
            self._mfc_table.setItem(row, 0, QTableWidgetItem(str(channel)))
            self._mfc_table.setItem(
                row, 1, QTableWidgetItem(self._format_float(state.flow_actual.get(channel)))
            )
            widgets = self._mfc_row_widgets.setdefault(channel, {})
            flow_edit = widgets.get("flow_edit")
            if not isinstance(flow_edit, QLineEdit):
                flow_edit = QLineEdit(str(state.flow_setpoints.get(channel, "")))
                widgets["flow_edit"] = flow_edit
            if not flow_edit.text().strip():
                flow_edit.setText(str(state.flow_setpoints.get(channel, "")))
            self._mfc_table.setCellWidget(row, 2, flow_edit)
            flow_button = widgets.get("flow_button")
            if not isinstance(flow_button, QPushButton):
                flow_button = QPushButton("Set Flow")
                flow_button.clicked.connect(lambda _checked=False, ch=channel: self._apply_flow(ch))
                widgets["flow_button"] = flow_button
            self._mfc_table.setCellWidget(row, 3, flow_button)
            target_edit = widgets.get("target_edit")
            if not isinstance(target_edit, QLineEdit):
                target_edit = QLineEdit(str(state.target_pressures.get(channel, "")))
                widgets["target_edit"] = target_edit
            self._mfc_table.setCellWidget(row, 4, target_edit)
            target_button = widgets.get("target_button")
            if not isinstance(target_button, QPushButton):
                target_button = QPushButton("Set Pressure")
                target_button.clicked.connect(
                    lambda _checked=False, ch=channel: self._apply_target_pressure(ch)
                )
                widgets["target_button"] = target_button
            self._mfc_table.setCellWidget(row, 5, target_button)
            self._mfc_table.setItem(row, 6, QTableWidgetItem(unit_text))
        for channel in existing - set(channels):
            self._mfc_row_widgets.pop(channel, None)

    def _append_chart_state(self, state: PressureEngineState) -> None:
        if state.reading is None:
            return
        timestamp = state.reading.timestamp.timestamp()
        for channel, reading in state.readings.items():
            if reading.value is not None:
                trace = f"Pressure {channel}"
                self._chart_history.setdefault(trace, []).append((timestamp, float(reading.value)))
                unit = reading.unit.value if hasattr(reading.unit, "value") else str(reading.unit)
                self._update_legend_value(trace, f"{reading.value:.4E} {unit}")
        for channel, value in state.flow_setpoints.items():
            trace = f"Flow setpoint {channel}"
            self._chart_history.setdefault(trace, []).append((timestamp, float(value)))
            self._update_legend_value(trace, self._format_flow_value(value, state.flow_unit))
        for channel, value in state.flow_actual.items():
            trace = f"Flow actual {channel}"
            self._chart_history.setdefault(trace, []).append((timestamp, float(value)))
            self._update_legend_value(trace, self._format_flow_value(value, state.flow_unit))

    def _refresh_chart(self) -> None:
        now = datetime.now(tz=UTC).timestamp()
        cutoff = now - self._chart_duration_min * 60.0
        self._chart_widget.clear_all()
        for trace, samples in list(self._chart_history.items()):
            trimmed = [(ts, value) for ts, value in samples if ts >= cutoff]
            self._chart_history[trace] = trimmed
            for ts, value in trimmed:
                self._chart_widget.append_point(trace, ts - now, value)
            if trace.startswith("Flow "):
                self._chart_widget.assign_trace_axes(trace, y_axis="flow")
            item = self._legend_items.get(trace)
            if item is not None:
                self._chart_widget.set_trace_visible(
                    trace, item.checkState(0) == Qt.CheckState.Checked
                )

    def _update_legend_value(self, trace: str, value: str) -> None:
        item = self._legend_items.get(trace)
        if item is None:
            item = QTreeWidgetItem([trace, value])
            item.setData(0, Qt.ItemDataRole.UserRole, trace)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            self._legend_tree.addTopLevelItem(item)
            self._legend_items[trace] = item
        else:
            item.setText(1, value)

    def _on_legend_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        trace = item.data(0, Qt.ItemDataRole.UserRole)
        if trace:
            self._chart_widget.set_trace_visible(trace, item.checkState(0) == Qt.CheckState.Checked)

    @staticmethod
    def _format_flow_value(value: float, unit: int | str | None) -> str:
        suffix = "" if unit is None else f" {unit}"
        return f"{value:.4g}{suffix}"

    def _set_gauge_channel(self, channel: int, enabled: bool) -> None:
        try:
            self._engine.set_gauge_channel_enabled(channel, enabled)
            self._engine.read_controller_state()
        except Exception as exc:
            QMessageBox.warning(
                self, "Gauge Channel", f"Failed to update gauge channel {channel}:\n{exc}"
            )

    def _apply_flow(self, channel: int) -> None:
        widget = self._mfc_row_widgets.get(channel, {}).get("flow_edit")
        if not isinstance(widget, QLineEdit):
            return
        try:
            self._engine.set_flow_rate(channel, float(widget.text()))
            self._engine.read_controller_state()
        except Exception as exc:
            QMessageBox.warning(
                self, "Set Flow", f"Failed to set flow on channel {channel}:\n{exc}"
            )

    def _apply_target_pressure(self, channel: int) -> None:
        widget = self._mfc_row_widgets.get(channel, {}).get("target_edit")
        if not isinstance(widget, QLineEdit):
            return
        try:
            self._engine.set_target_pressure(channel, float(widget.text()))
            self._engine.read_controller_state()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Set Target Pressure",
                f"Failed to set target pressure on channel {channel}:\n{exc}",
            )

    @pyqtSlot()
    def _on_read_state(self) -> None:
        state = self._engine.read_controller_state()
        if state is None:
            QMessageBox.warning(self, "Pressure State", "No instrument connected or read failed.")

    @pyqtSlot()
    def _on_save_configuration(self) -> None:
        try:
            driver_name = self._driver_combo.currentData(Qt.ItemDataRole.UserRole + 1)
            self._engine.preferred_driver_name = str(
                driver_name or self._driver_combo.currentText()
            )
            transport_name, address = selected_transport(self, self._transport_combo.currentIndex())
            self._engine.preferred_transport_name = transport_name
            self._engine.preferred_address = address
            mfc_driver_name = self._mfc_driver_combo.currentData(Qt.ItemDataRole.UserRole + 1)
            self._engine.preferred_mfc_driver_name = str(
                mfc_driver_name or self._mfc_driver_combo.currentText()
            )
            mfc_transport_name, mfc_address = self._selected_mfc_transport()
            self._engine.preferred_mfc_transport_name = mfc_transport_name
            self._engine.preferred_mfc_address = mfc_address
            path = self._engine.save_configuration()
        except Exception as exc:
            QMessageBox.critical(
                self, "Save Configuration", f"Failed to save configuration:\n{exc}"
            )
            return
        QMessageBox.information(self, "Save Configuration", f"Configuration saved to:\n{path}")

    @pyqtSlot(int)
    def _on_duration_changed(self, index: int) -> None:
        self._chart_duration_min = int(self._duration_combo.itemData(index))
        self._refresh_chart()

    @pyqtSlot()
    def _on_clear_chart(self) -> None:
        self._chart_history.clear()
        self._chart_widget.clear_all()
        self._legend_tree.clear()
        self._legend_items.clear()

    @staticmethod
    def _format_float(value: float | None) -> str:
        if value is None:
            return "—"
        return f"{value:.4g}"
