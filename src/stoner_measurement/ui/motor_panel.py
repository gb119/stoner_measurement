"""Non-blocking motor controller panel window."""

from __future__ import annotations

import logging
import math
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

from stoner_measurement.instruments.addressing import (
    DEFAULT_ETHERNET_HOST,
    DEFAULT_ETHERNET_PORT,
)
from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.motor_controller import (
    MotorController,
    MotorMoveDirection,
)
from stoner_measurement.motor_control.engine import MotorControllerEngine
from stoner_measurement.motor_control.types import (
    MotorEngineState,
    MotorEngineStatus,
)
from stoner_measurement.qt_compat import pyqtSlot
from stoner_measurement.ui.theme import indicator_label_stylesheet
from stoner_measurement.ui.widgets import (
    FILTER_GPIB,
    FILTER_SERIAL,
    RoundDialWidget,
    SISpinBox,
    VisaResourceComboBox,
    VisaResourceStatus,
    load_connection_preferences,
    restore_preferred_address,
    selected_transport,
    set_address_widget_status,
    show_transport_widget,
)

logger = logging.getLogger(__name__)

_STATUS_COLOURS: dict[MotorEngineStatus, str] = {
    MotorEngineStatus.STOPPED: "#888888",
    MotorEngineStatus.DISCONNECTED: "#cc4444",
    MotorEngineStatus.CONNECTED: "#cc8800",
    MotorEngineStatus.POLLING: "#44aa44",
    MotorEngineStatus.ERROR: "#cc0000",
}


def _colour_dot(colour: str, size: int = 12) -> str:
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f"border-radius:{size // 2}px;background:{colour};\"></span>"
    )


def _line_edit(placeholder: str = "") -> QWidget:
    from qtpy.QtWidgets import QLineEdit

    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setText(placeholder)
    return w


def _signed_display_angle(angle: float) -> float:
    """Return *angle* folded into the signed display interval [-180, 180]."""
    wrapped = ((float(angle) + 180.0) % 360.0) - 180.0
    if math.isclose(wrapped, -180.0, abs_tol=1e-9) and angle > 0.0:
        return 180.0
    return wrapped


class MotorControlPanel(QWidget):
    """Non-blocking window for motor controller configuration and monitoring."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Motor Control")
        self.setMinimumSize(640, 520)
        self.setWindowFlags(Qt.WindowType.Window)

        self._engine = MotorControllerEngine.instance()
        self._driver_manager = InstrumentDriverManager()
        self._driver_manager.discover()
        self._allow_exit_close = False

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
            logger.info("Closing motor control panel during application shutdown.")
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def _build_ui(self) -> None:
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_connection_tab(), "Connection")
        self._tabs.addTab(self._build_control_tab(), "Control")

        status_bar = self._build_status_bar()

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 4)
        root.setSpacing(4)
        root.addWidget(self._tabs)
        root.addWidget(status_bar)
        root.addLayout(self._build_hide_button_row())
        self.setLayout(root)

    def _build_hide_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()
        self._btn_hide = QPushButton("Hide")
        self._btn_hide.setToolTip("Hide this panel")
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

        for w in (
            self._serial_form_widget,
            self._gpib_form_widget,
            self._ethernet_form_widget,
            self._null_form_widget,
        ):
            address_stack.addWidget(w)
            w.hide()
        self._serial_form_widget.show()
        layout.addWidget(self._address_group)

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
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        self._serial_port_combo = VisaResourceComboBox(
            resource_filter=FILTER_SERIAL,
            placeholder="/dev/ttyUSB0",
            extra_resources=["/dev/ttyUSB0"],
        )
        self._serial_baud_combo = QComboBox()
        for baud in (9600, 19200, 38400, 57600, 115200):
            self._serial_baud_combo.addItem(str(baud), baud)
        form.addRow("Port:", self._serial_port_combo)
        form.addRow("Baud rate:", self._serial_baud_combo)
        return w

    def _build_gpib_address_form(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        self._gpib_resource_combo = VisaResourceComboBox(
            resource_filter=FILTER_GPIB,
            placeholder="GPIB0::1::INSTR",
            extra_resources=["GPIB0::1::INSTR"],
        )
        form.addRow("VISA resource:", self._gpib_resource_combo)
        return w

    def _build_ethernet_address_form(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        self._eth_host_edit = _line_edit(DEFAULT_ETHERNET_HOST)
        self._eth_port_spin = QSpinBox()
        self._eth_port_spin.setRange(1, 65535)
        self._eth_port_spin.setValue(DEFAULT_ETHERNET_PORT)
        form.addRow("Host:", self._eth_host_edit)
        form.addRow("Port:", self._eth_port_spin)
        return w

    def _build_control_tab(self) -> QWidget:
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.setSpacing(8)

        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        motion_group = QGroupBox("Motion Control")
        motion_form = QFormLayout(motion_group)

        self._target_angle_spin = SISpinBox()
        self._target_angle_spin.setOpts(
            bounds=self._target_angle_bounds(),
            decimals=3,
            suffix="°",
            step=1.0,
        )
        motion_form.addRow("Target angle:", self._target_angle_spin)

        self._velocity_spin = SISpinBox()
        self._velocity_spin.setOpts(bounds=(0.001, 10000.0), decimals=3, suffix="°/s", step=1.0)
        self._velocity_spin.setValue(10.0)
        motion_form.addRow("Velocity:", self._velocity_spin)

        self._acceleration_spin = SISpinBox()
        self._acceleration_spin.setOpts(bounds=(0.001, 10000.0), decimals=3, suffix="°/s²", step=1.0)
        self._acceleration_spin.setValue(10.0)
        motion_form.addRow("Acceleration:", self._acceleration_spin)

        self._direction_combo = QComboBox()
        self._direction_combo.addItem("Clockwise", MotorMoveDirection.CLOCKWISE)
        self._direction_combo.addItem("Counter-clockwise", MotorMoveDirection.COUNTERCLOCKWISE)
        self._direction_combo.addItem("Shortest", MotorMoveDirection.SHORTEST)
        motion_form.addRow("Direction:", self._direction_combo)

        btn_row = QHBoxLayout()
        self._btn_apply_and_move = QPushButton("Apply && Move")
        self._btn_apply_and_move.clicked.connect(self._on_apply_and_move)
        self._btn_read_state = QPushButton("Read")
        self._btn_read_state.clicked.connect(self._on_read_state)
        self._btn_save_configuration = QPushButton("Save Settings to YAML")
        self._btn_save_configuration.clicked.connect(self._on_save_configuration)
        btn_row.addWidget(self._btn_apply_and_move)
        btn_row.addWidget(self._btn_read_state)
        btn_row.addWidget(self._btn_save_configuration)
        btn_row.addStretch()
        motion_form.addRow("", btn_row)
        left_layout.addWidget(motion_group)

        home_group = QGroupBox("Home")
        home_form = QFormLayout(home_group)

        self._home_angle_spin = SISpinBox()
        self._home_angle_spin.setOpts(bounds=(-3600.0, 3600.0), decimals=3, suffix="°", step=1.0)
        home_form.addRow("Home angle:", self._home_angle_spin)

        home_btn_row = QHBoxLayout()
        self._btn_set_home = QPushButton("Set Home")
        self._btn_set_home.clicked.connect(self._on_set_home)
        self._btn_move_home = QPushButton("Move Home")
        self._btn_move_home.clicked.connect(self._on_move_home)
        home_btn_row.addWidget(self._btn_set_home)
        home_btn_row.addWidget(self._btn_move_home)
        home_btn_row.addStretch()
        home_form.addRow("", home_btn_row)
        left_layout.addWidget(home_group)
        left_layout.addStretch()

        self._dial = RoundDialWidget(right_column)
        self._dial.setTitle("Motor Angle")
        self._dial.setBidirectionalAngleMode()
        self._dial.setMajorTickStep(30.0)
        self._dial.setShowValueText(True)
        self._dial.setValueTextSuffix("°")
        right_layout.addWidget(self._dial, stretch=1)

        self._angle_label = QLabel("Angle: —")
        self._angle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self._angle_label)

        self._target_label = QLabel("Target: —")
        self._target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self._target_label)

        self._motion_state_label = QLabel("State: —")
        self._motion_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self._motion_state_label)

        self._revolutions_label = QLabel("Revolutions: —")
        self._revolutions_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self._revolutions_label)

        layout.addWidget(left_column, 0, 0)
        layout.addWidget(right_column, 0, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        return widget

    def _build_status_bar(self) -> QWidget:
        status_bar = QWidget()
        status_bar.setFixedHeight(28)
        bar_layout = QHBoxLayout(status_bar)
        bar_layout.setContentsMargins(4, 2, 4, 2)
        bar_layout.setSpacing(12)

        self._status_label = QLabel("Engine: —")
        bar_layout.addWidget(self._status_label)

        self._at_target_label = QLabel("At target: —")
        bar_layout.addWidget(self._at_target_label)

        self._stable_label = QLabel("Stable: —")
        bar_layout.addWidget(self._stable_label)

        bar_layout.addStretch()

        self._updated_label = QLabel("Last updated: —")
        bar_layout.addWidget(self._updated_label)
        return status_bar

    def _connect_engine_signals(self) -> None:
        pub = self._engine.publisher
        pub.state_updated.connect(self._on_state_updated)
        pub.engine_status_changed.connect(self._on_engine_status_changed)
        self._on_engine_status_changed(self._engine.status)

    def _target_angle_bounds(self) -> tuple[float, float]:
        """Return the target-angle bounds derived from the configured soft limit."""
        soft_limit = abs(float(getattr(self._engine, "_soft_limit", 180.0)))
        return -soft_limit, soft_limit

    def _refresh_target_angle_bounds(self) -> None:
        """Keep the target control validation aligned with the engine soft limit."""
        self._target_angle_spin.setOpts(bounds=self._target_angle_bounds())

    @pyqtSlot(MotorEngineStatus)
    def _on_engine_status_changed(self, status: MotorEngineStatus) -> None:
        colour = _STATUS_COLOURS.get(status, "#888888")
        dot = _colour_dot(colour)
        self._status_label.setText(f"{dot} Engine: {status.value}")
        connected = status in (MotorEngineStatus.CONNECTED, MotorEngineStatus.POLLING)
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)
        self._refresh_target_angle_bounds()

    @pyqtSlot(MotorEngineState)
    def _on_state_updated(self, state: MotorEngineState) -> None:
        reading = state.reading
        now_ts = datetime.now(tz=UTC).timestamp()
        self._updated_label.setText(
            f"Last updated: {datetime.fromtimestamp(now_ts).strftime('%H:%M:%S')}"
        )

        at_colour = "#44aa44" if state.at_target else "#cc4444"
        self._at_target_label.setText(
            f"{_colour_dot(at_colour)} At target: {'yes' if state.at_target else 'no'}"
        )
        stable_colour = "#44aa44" if state.stable else "#cc4444"
        self._stable_label.setText(
            f"{_colour_dot(stable_colour)} Stable: {'yes' if state.stable else 'no'}"
        )

        if reading is None:
            return

        dial_angle = _signed_display_angle(reading.angle)
        self._dial.setValue(dial_angle)
        self._angle_label.setText(f"Angle: {dial_angle:.3f}°")
        self._target_label.setText(
            "Target: —"
            if reading.target_angle is None
            else f"Target: {_signed_display_angle(reading.target_angle):.3f}°"
        )
        self._revolutions_label.setText(f"Revolutions: {reading.revolutions:d} ({reading.move_direction or '—'})")

        label = "Moving" if reading.moving else "Idle"
        fg = "#ffffff" if reading.moving else "#ffffff"
        bg = "#1e88e5" if reading.moving else "#2e7d32"
        self._motion_state_label.setText(label)
        self._motion_state_label.setStyleSheet(indicator_label_stylesheet(bg, fg))

    def _populate_driver_combo(self) -> None:
        self._driver_combo.clear()
        mc_drivers = self._driver_manager.drivers_by_type(MotorController)
        added = 0
        for name in sorted(mc_drivers):
            if not name.startswith("_"):
                self._driver_combo.addItem(name, mc_drivers[name])
                added += 1
        if added == 0:
            self._driver_combo.addItem("(no drivers found)", None)

    def _load_connection_preferences(self) -> None:
        load_connection_preferences(self)
        if self._engine._velocity is not None:  # pylint: disable=protected-access
            self._velocity_spin.setValue(self._engine._velocity)  # pylint: disable=protected-access
        if self._engine._acceleration is not None:  # pylint: disable=protected-access
            self._acceleration_spin.setValue(self._engine._acceleration)  # pylint: disable=protected-access
        direction = self._engine._move_direction  # pylint: disable=protected-access
        if direction is MotorMoveDirection.TOWARDS_ZERO:
            direction = MotorMoveDirection.SHORTEST
        index = self._direction_combo.findData(direction)
        if index >= 0:
            self._direction_combo.setCurrentIndex(index)

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
            self._engine.preferred_driver_name = self._driver_combo.currentText()
            self._engine.preferred_transport_name = transport_name
            self._engine.preferred_address = address
            self._engine.save_configuration()
            self._engine.connect_driver(
                driver_name=self._driver_combo.currentText(),
                transport_name=transport_name,
                address=address,
            )
            self._refresh_target_angle_bounds()
        except Exception:
            logger.exception("Failed to connect motor driver")
            self._set_address_widget_status(transport_index, VisaResourceStatus.ERROR)
            return

        self._set_address_widget_status(transport_index, VisaResourceStatus.CONNECTED)
        self._on_read_state()

    def _set_address_widget_status(self, transport_index: int, status: VisaResourceStatus) -> None:
        set_address_widget_status(self, transport_index, status)

    @pyqtSlot()
    def _on_disconnect(self) -> None:
        self._engine.disconnect_instrument()
        self._set_address_widget_status(2, VisaResourceStatus.DISCONNECTED)
        self._set_address_widget_status(3, VisaResourceStatus.DISCONNECTED)
        self._serial_port_combo.set_status(VisaResourceStatus.DISCONNECTED)
        self._gpib_resource_combo.set_status(VisaResourceStatus.DISCONNECTED)

    @pyqtSlot()
    def _on_apply_and_move(self) -> None:
        self._engine.preferred_driver_name = self._driver_combo.currentText()
        transport_name, address = selected_transport(self, self._transport_combo.currentIndex())
        self._engine.preferred_transport_name = transport_name
        self._engine.preferred_address = address
        self._engine.set_velocity(self._velocity_spin.value())
        self._engine.set_acceleration(self._acceleration_spin.value())
        target_angle = self._target_angle_spin.value()
        direction = self._direction_combo.currentData()
        try:
            self._engine.move_to_angle(target_angle, direction=direction)
        except ValueError as exc:
            response = QMessageBox.warning(
                self,
                "Motor Soft Limit",
                (
                    f"{exc}\n\n"
                    "This move exceeds the configured motor soft limit. Continue anyway?\n\n"
                    "Reset the home position after any forced move."
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response == QMessageBox.StandardButton.Yes:
                self._engine.move_to_angle(target_angle, direction=direction, force=True)

    @pyqtSlot()
    def _on_read_state(self) -> None:
        state = self._read_controller_state_or_warn("Motor State")
        if state is None:
            return
        if state.target_angle is not None:
            self._target_angle_spin.setValue(state.target_angle)
        if state.move_direction is not None:
            try:
                direction = MotorMoveDirection(state.move_direction)
            except ValueError:
                direction = MotorMoveDirection.CLOCKWISE
            index = self._direction_combo.findData(direction)
            if index >= 0:
                self._direction_combo.setCurrentIndex(index)
        if state.velocity is not None:
            self._velocity_spin.setValue(state.velocity)
        if state.acceleration is not None:
            self._acceleration_spin.setValue(state.acceleration)

    @pyqtSlot()
    def _on_set_home(self) -> None:
        self._engine.set_home(self._home_angle_spin.value())

    @pyqtSlot()
    def _on_move_home(self) -> None:
        self._engine.move_home()

    @pyqtSlot()
    def _on_save_configuration(self) -> None:
        try:
            self._engine.preferred_driver_name = self._driver_combo.currentText()
            transport_name, address = selected_transport(self, self._transport_combo.currentIndex())
            self._engine.preferred_transport_name = transport_name
            self._engine.preferred_address = address
            self._engine._velocity = self._velocity_spin.value()  # pylint: disable=protected-access
            self._engine._acceleration = self._acceleration_spin.value()  # pylint: disable=protected-access
            self._engine._move_direction = self._direction_combo.currentData()  # pylint: disable=protected-access
            path = self._engine.save_configuration()
            self._refresh_target_angle_bounds()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Save Configuration",
                f"Failed to save configuration:\n{exc}",
            )
            return
        QMessageBox.information(self, "Save Configuration", f"Configuration saved to:\n{path}")

    def _read_controller_state_or_warn(self, title: str) -> MotorEngineState | None:
        state = self._engine.read_controller_state()
        if state is not None:
            return state
        QMessageBox.warning(self, title, "No instrument connected or read failed.")
        return None
