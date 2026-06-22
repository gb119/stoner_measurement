"""Non-blocking magnet controller panel window.

Provides :class:`MagnetControlPanel`, a non-modal :class:`~PyQt6.QtWidgets.QWidget`
window that lets the user configure and monitor a magnet controller through
the :class:`~stoner_measurement.magnet_control.engine.MagnetControllerEngine`
singleton.

The panel has three sections arranged in a :class:`~PyQt6.QtWidgets.QTabWidget`:

* **Connection** — driver type, transport type, address, Connect/Disconnect.
* **Configuration** — target field/current, ramp rates, persistent switch heater,
  magnet constants, and ramp control.
* **Chart** — live scrolling pyqtgraph plot of field, current, voltage, and
  heater state.

A status bar at the bottom shows the last-updated timestamp, engine status,
and at-target indicator.

Closing the window only hides it; the engine keeps running.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from qtpy.QtCore import Qt, QSettings
from stoner_measurement.qt_compat import pyqtSlot
from qtpy.QtGui import QColor, QIcon, QPixmap
from qtpy.QtWidgets import (
    QComboBox,
    QColorDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.addressing import (
    DEFAULT_ETHERNET_HOST,
    DEFAULT_ETHERNET_PORT,
)
from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.magnet_controller import (
    HeaterState,
    MagnetController,
    MagnetState,
)
from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.magnet_control.types import (
    MagnetEngineState,
    MagnetEngineStatus,
    MagnetReading,
)
from stoner_measurement.ui.icons import make_magnet_icon
from stoner_measurement.ui.plot_widget import PlotWidget
from stoner_measurement.ui.theme import indicator_label_stylesheet
from stoner_measurement.ui.widgets import (
    FILTER_GPIB,
    FILTER_SERIAL,
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

#: Colour for the field trace.
_FIELD_COLOUR = QColor("royalblue")

#: Colour for the current trace.
_CURRENT_COLOUR = QColor("darkorange")

#: Colour for the voltage trace.
_VOLTAGE_COLOUR = QColor("forestgreen")

#: Colour for the heater state trace.
_HEATER_COLOUR = QColor("firebrick")

#: Colour for the target-field horizontal marker.
_TARGET_COLOUR = QColor("black")

#: Available chart duration options (minutes, label).
_CHART_DURATIONS: list[tuple[int, str]] = [
    (5, "5 min"),
    (10, "10 min"),
    (30, "30 min"),
    (60, "60 min"),
]

#: Status indicator colours keyed by engine status.
_STATUS_COLOURS: dict[MagnetEngineStatus, str] = {
    MagnetEngineStatus.STOPPED: "#888888",
    MagnetEngineStatus.DISCONNECTED: "#cc4444",
    MagnetEngineStatus.CONNECTED: "#cc8800",
    MagnetEngineStatus.POLLING: "#44aa44",
    MagnetEngineStatus.ERROR: "#cc0000",
}


def _colour_dot(colour: str, size: int = 12) -> str:
    """Return an HTML span rendering a filled coloured circle.

    Args:
        colour (str):
            CSS colour string.

    Keyword Parameters:
        size (int):
            Circle diameter in pixels.  Defaults to ``12``.

    Returns:
        (str):
            HTML string for a coloured dot.
    """
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f"border-radius:{size // 2}px;background:{colour};\"></span>"
    )


def _line_edit(placeholder: str = "") -> QWidget:
    """Return a :class:`~PyQt6.QtWidgets.QLineEdit` with placeholder text.

    Args:
        placeholder (str):
            Placeholder and initial text.

    Returns:
        (QWidget):
            A configured line-edit widget.
    """
    from qtpy.QtWidgets import QLineEdit

    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setText(placeholder)
    return w


class MagnetControlPanel(QWidget):
    """Non-blocking window for magnet controller configuration and monitoring.

    Opens from the *Magnet* menu or toolbar button.  Communicates exclusively
    through the :class:`~stoner_measurement.magnet_control.engine.MagnetControllerEngine`
    singleton — never talking to instrument hardware directly.

    Closing the window hides it; the engine keeps running.

    Args:
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.ui.magnet_panel import MagnetControlPanel
        >>> panel = MagnetControlPanel()
        >>> panel.windowTitle()
        'Magnet Control'
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Magnet Control")
        self.setMinimumSize(640, 520)
        self.setWindowIcon(make_magnet_icon())
        self.setWindowFlags(Qt.WindowType.Window)

        self._engine = MagnetControllerEngine.instance()
        self._driver_manager = InstrumentDriverManager()
        self._driver_manager.discover()

        # Chart data buffers.
        self._chart_times: list[float] = []
        self._chart_field: list[float] = []
        self._chart_current: list[float] = []
        self._chart_voltage: list[float] = []
        self._chart_heater: list[float] = []
        self._legend_items: dict[str, QTreeWidgetItem] = {}
        self._chart_duration_min: int = _CHART_DURATIONS[0][0]

        # Cached magnet constant for current ↔ field conversion in UI.
        self._magnet_constant: float = 1.0

        self._load_chart_settings()
        self._build_ui()
        self._load_connection_preferences()
        self._connect_engine_signals()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def show_and_raise(self) -> None:
        """Show the panel and bring it to the front.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.ui.magnet_panel import MagnetControlPanel
            >>> panel = MagnetControlPanel()
            >>> panel.show_and_raise()
            >>> panel.isVisible()
            True
        """
        self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    # QWidget overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Hide the window instead of destroying it.

        The engine continues running when the panel is closed.
        """
        event.ignore()
        self.hide()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build all UI sections and assemble the tab widget."""
        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_connection_tab(), "Connection")
        self._tabs.addTab(self._build_config_tab(), "Configuration")
        self._tabs.addTab(self._build_chart_tab(), "Chart")

        status_bar = self._build_status_bar()

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 4)
        root.setSpacing(4)
        root.addWidget(self._tabs)
        root.addWidget(status_bar)
        self.setLayout(root)

    # --- Connection tab ---

    def _build_connection_tab(self) -> QWidget:
        """Build the Connection tab.

        Returns:
            (QWidget):
                The assembled connection tab.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        # Driver selection.
        driver_group = QGroupBox("Instrument Driver")
        driver_form = QFormLayout(driver_group)

        self._driver_combo = QComboBox()
        self._driver_combo.setToolTip("Select the magnet controller driver")
        self._populate_driver_combo()
        driver_form.addRow("Driver:", self._driver_combo)

        self._transport_combo = QComboBox()
        for label in ("Serial", "GPIB", "Ethernet", "Null (test)"):
            self._transport_combo.addItem(label)
        self._transport_combo.currentIndexChanged.connect(self._on_transport_changed)
        driver_form.addRow("Transport:", self._transport_combo)

        layout.addWidget(driver_group)

        # Transport-specific address fields.
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

        # Connect / Disconnect buttons.
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
        self._eth_host_edit = _line_edit(DEFAULT_ETHERNET_HOST)
        self._eth_port_spin = QSpinBox()
        self._eth_port_spin.setRange(1, 65535)
        self._eth_port_spin.setValue(DEFAULT_ETHERNET_PORT)
        form.addRow("Host:", self._eth_host_edit)
        form.addRow("Port:", self._eth_port_spin)
        return w

    # --- Configuration tab ---

    def _build_config_tab(self) -> QWidget:
        """Build the Configuration tab.

        Returns:
            (QWidget):
                The assembled configuration tab.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        # Target field group.
        target_group = QGroupBox("Target Field")
        target_form = QFormLayout(target_group)

        self._target_field_spin = SISpinBox()
        self._target_field_spin.setOpts(bounds=(-20.0, 20.0), decimals=4, suffix="T", siPrefix=True, step=0.1)
        self._target_field_spin.valueChanged.connect(self._on_target_field_changed)
        target_form.addRow("Target field:", self._target_field_spin)

        self._target_current_spin = SISpinBox()
        self._target_current_spin.setOpts(bounds=(-1000.0, 1000.0), decimals=4, suffix="A", siPrefix=True)
        self._target_current_spin.valueChanged.connect(self._on_target_current_changed)
        self._target_current_label = QLabel("—")
        self._target_current_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        target_current_widget = QWidget()
        target_current_row = QHBoxLayout(target_current_widget)
        target_current_row.setContentsMargins(0, 0, 0, 0)
        target_current_row.addWidget(self._target_current_spin, stretch=1)
        target_current_row.addWidget(self._target_current_label)
        target_form.addRow("Target current:", target_current_widget)

        go_btn_row = QHBoxLayout()
        self._btn_go = QPushButton("Go To Field")
        self._btn_go.setToolTip("Set the target and begin ramping")
        self._btn_go.clicked.connect(self._on_go_to_field)
        self._btn_read_target = QPushButton("Read")
        self._btn_read_target.setToolTip("Read the current target field from the controller state")
        self._btn_read_target.clicked.connect(self._on_read_target)
        go_btn_row.addWidget(self._btn_go)
        go_btn_row.addWidget(self._btn_read_target)
        go_btn_row.addStretch()
        target_form.addRow("", go_btn_row)
        layout.addWidget(target_group)

        # Ramp rate group.
        ramp_group = QGroupBox("Ramp Rate")
        ramp_form = QFormLayout(ramp_group)

        self._ramp_field_spin = SISpinBox()
        self._ramp_field_spin.setOpts(bounds=(0.001, 10.0), decimals=4, suffix="T/min", siPrefix=True)
        self._ramp_field_spin.setValue(0.1)
        self._ramp_field_spin.valueChanged.connect(self._on_ramp_field_changed)
        ramp_form.addRow("Field ramp rate:", self._ramp_field_spin)

        self._ramp_current_spin = SISpinBox()
        self._ramp_current_spin.setOpts(bounds=(0.01, 1000.0), decimals=3, suffix="A/min", siPrefix=True)
        self._ramp_current_spin.setValue(1.0)
        self._ramp_current_spin.valueChanged.connect(self._on_ramp_current_changed)
        ramp_form.addRow("Current ramp rate:", self._ramp_current_spin)

        ramp_btn_row = QHBoxLayout()
        self._btn_apply_ramp = QPushButton("Apply Ramp Rates")
        self._btn_apply_ramp.clicked.connect(self._on_apply_ramp)
        self._btn_read_ramp = QPushButton("Read")
        self._btn_read_ramp.setToolTip("Read current ramp rates from the controller state")
        self._btn_read_ramp.clicked.connect(self._on_read_ramp)
        ramp_btn_row.addWidget(self._btn_apply_ramp)
        ramp_btn_row.addWidget(self._btn_read_ramp)
        ramp_btn_row.addStretch()
        ramp_form.addRow("", ramp_btn_row)
        layout.addWidget(ramp_group)

        # Ramp control buttons.
        ramp_ctrl_group = QGroupBox("Ramp Control")
        ramp_ctrl_layout = QHBoxLayout(ramp_ctrl_group)
        self._btn_pause_ramp = QPushButton("Pause Ramp")
        self._btn_pause_ramp.clicked.connect(self._on_pause_ramp)
        self._btn_hold = QPushButton("Hold")
        self._btn_hold.clicked.connect(self._on_hold)
        self._btn_zero = QPushButton("Go To Zero")
        self._btn_zero.clicked.connect(self._on_go_to_zero)
        self._btn_abort_ramp = QPushButton("Abort Ramp")
        self._btn_abort_ramp.clicked.connect(self._on_abort_ramp)
        ramp_ctrl_layout.addWidget(self._btn_pause_ramp)
        ramp_ctrl_layout.addWidget(self._btn_hold)
        ramp_ctrl_layout.addWidget(self._btn_zero)
        ramp_ctrl_layout.addWidget(self._btn_abort_ramp)
        ramp_ctrl_layout.addStretch()
        self._ramp_action_label = QLabel("—")
        self._ramp_action_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ramp_ctrl_layout.addWidget(self._ramp_action_label)
        layout.addWidget(ramp_ctrl_group)

        # Persistent switch heater group.
        heater_group = QGroupBox("Persistent Switch Heater")
        heater_form = QFormLayout(heater_group)
        heater_btn_row = QHBoxLayout()
        self._btn_heater_on = QPushButton("Heater On")
        self._btn_heater_on.clicked.connect(self._on_heater_on)
        self._btn_heater_off = QPushButton("Heater Off")
        self._btn_heater_off.clicked.connect(self._on_heater_off)
        self._btn_read_heater = QPushButton("Read")
        self._btn_read_heater.setToolTip("Read the current heater state from the controller")
        self._btn_read_heater.clicked.connect(self._on_read_heater)
        heater_btn_row.addWidget(self._btn_heater_on)
        heater_btn_row.addWidget(self._btn_heater_off)
        heater_btn_row.addWidget(self._btn_read_heater)
        heater_btn_row.addStretch()
        self._heater_state_label = QLabel("—")
        self._heater_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heater_form.addRow("State:", self._heater_state_label)
        heater_form.addRow("", heater_btn_row)
        layout.addWidget(heater_group)

        # Magnet constants group.
        const_group = QGroupBox("Magnet Constants && Limits")
        const_form = QFormLayout(const_group)

        self._magnet_const_spin = SISpinBox()
        self._magnet_const_spin.setOpts(bounds=(0.0001, 100.0), decimals=6, suffix="T/A", siPrefix=True)
        self._magnet_const_spin.setValue(0.1)
        const_form.addRow("Magnet constant:", self._magnet_const_spin)

        self._max_current_spin = SISpinBox()
        self._max_current_spin.setOpts(bounds=(0.0, 1000.0), decimals=2, suffix="A", siPrefix=True)
        self._max_current_spin.setValue(100.0)
        const_form.addRow("Max current:", self._max_current_spin)

        self._max_field_spin = SISpinBox()
        self._max_field_spin.setOpts(bounds=(0.0, 100.0), decimals=3, suffix="T", siPrefix=True)
        self._max_field_spin.setValue(10.0)
        const_form.addRow("Max field:", self._max_field_spin)

        self._max_ramp_spin = SISpinBox()
        self._max_ramp_spin.setOpts(bounds=(0.0, 100.0), decimals=3, suffix="T/min", siPrefix=True)
        self._max_ramp_spin.setValue(1.0)
        const_form.addRow("Max ramp rate:", self._max_ramp_spin)

        limits_btn_row = QHBoxLayout()
        self._btn_apply_limits = QPushButton("Apply Constants && Limits")
        self._btn_apply_limits.clicked.connect(self._on_apply_limits)
        self._btn_read_limits = QPushButton("Read")
        self._btn_read_limits.setToolTip("Read magnet constant and limits from the controller")
        self._btn_read_limits.clicked.connect(self._on_read_limits)
        limits_btn_row.addWidget(self._btn_apply_limits)
        limits_btn_row.addWidget(self._btn_read_limits)
        limits_btn_row.addStretch()
        const_form.addRow("", limits_btn_row)
        layout.addWidget(const_group)

        layout.addStretch()
        return widget

    # --- Chart tab ---

    def _build_chart_tab(self) -> QWidget:
        """Build the live chart tab.

        Returns:
            (QWidget):
                The assembled chart tab.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Duration:"))
        self._duration_combo = QComboBox()
        for minutes, label in _CHART_DURATIONS:
            self._duration_combo.addItem(label, minutes)
        self._duration_combo.currentIndexChanged.connect(self._on_duration_changed)
        controls.addWidget(self._duration_combo)
        controls.addStretch()
        self._btn_clear_chart = QPushButton("Clear")
        self._btn_clear_chart.clicked.connect(self._on_clear_chart)
        controls.addWidget(self._btn_clear_chart)
        layout.addLayout(controls)

        content = QHBoxLayout()

        self._chart_widget = PlotWidget(
            show_axis_controls=False,
            show_trace_table=False,
        )
        self._chart_widget.set_default_axis_labels("Time (s ago)", "Field (T)")
        self._chart_widget.add_y_axis("electrical", "Current / Voltage")
        self._chart_widget.add_y_axis("heater", "Heater")
        content.addWidget(self._chart_widget, stretch=4)

        self._legend_tree = QTreeWidget()
        self._legend_tree.setHeaderLabels(["Trace", "Value"])
        self._legend_tree.setMinimumWidth(220)
        self._legend_tree.itemChanged.connect(self._on_legend_item_changed)
        self._legend_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._legend_tree.customContextMenuRequested.connect(self._on_legend_context_menu)
        content.addWidget(self._legend_tree, stretch=1)

        layout.addLayout(content)
        return widget

    # --- Status bar ---

    def _build_status_bar(self) -> QWidget:
        """Build the bottom status bar.

        Returns:
            (QWidget):
                The assembled status bar.
        """
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

    # ------------------------------------------------------------------
    # Signal connections
    # ------------------------------------------------------------------

    def _connect_engine_signals(self) -> None:
        """Connect to engine publisher signals for live updates."""
        pub = self._engine.publisher
        pub.state_updated.connect(self._on_state_updated)
        pub.engine_status_changed.connect(self._on_engine_status_changed)
        self._on_engine_status_changed(self._engine.status)

    # ------------------------------------------------------------------
    # Engine signal slots
    # ------------------------------------------------------------------

    @pyqtSlot(MagnetEngineStatus)
    def _on_engine_status_changed(self, status: MagnetEngineStatus) -> None:
        """Update status indicator and button states when engine status changes.

        Args:
            status (MagnetEngineStatus):
                The new engine status.
        """
        colour = _STATUS_COLOURS.get(status, "#888888")
        dot = _colour_dot(colour)
        self._status_label.setText(f"{dot} Engine: {status.value}")
        connected = status in (MagnetEngineStatus.CONNECTED, MagnetEngineStatus.POLLING)
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)

    @pyqtSlot(MagnetEngineState)
    def _on_state_updated(self, state: MagnetEngineState) -> None:
        """Update all UI elements and chart traces from a new engine state.

        Args:
            state (MagnetEngineState):
                The latest engine state snapshot.
        """
        now_ts = datetime.now(tz=UTC).timestamp()

        if state.magnet_constant is not None and state.magnet_constant > 0:
            self._magnet_constant = state.magnet_constant

        self._set_heater_state_label(self._heater_state_from_state(state))
        self._update_heater_controls(state)
        self._set_ramp_action_label(state)
        self._update_ramp_controls(state)
        self._update_chart(state, now_ts)

        self._updated_label.setText(
            f"Last updated: {datetime.fromtimestamp(now_ts).strftime('%H:%M:%S')}"
        )
        at_colour = "#44aa44" if state.at_target else "#cc4444"
        self._at_target_label.setText(
            f"{_colour_dot(at_colour)} At target: {'yes' if state.at_target else 'no'}"
        )
        if hasattr(self, "_stable_label"):
            stable_colour = "#44aa44" if state.stable else "#cc4444"
            self._stable_label.setText(
                f"{_colour_dot(stable_colour)} Stable: {'yes' if state.stable else 'no'}"
            )
        if state.reading is not None and state.reading.quench_detected:
            self._status_label.setText(f"{_colour_dot('#c62828')} Engine: quench")
            self._at_target_label.setText(f"{_colour_dot('#c62828')} At target: no")
            if hasattr(self, "_stable_label"):
                self._stable_label.setText(f"{_colour_dot('#c62828')} Stable: no")

    # ------------------------------------------------------------------
    # Chart helpers
    # ------------------------------------------------------------------

    def _update_chart(self, state: MagnetEngineState, now_ts: float) -> None:
        """Append the latest readings to chart buffers and redraw curves.

        Args:
            state (MagnetEngineState):
                Current state snapshot.
            now_ts (float):
                Current time as a Unix timestamp.
        """
        reading = state.reading
        if reading is None:
            return

        duration_s = self._chart_duration_min * 60.0
        ts = reading.timestamp.timestamp()
        self._chart_times.append(ts)
        field_val = reading.field if reading.field is not None else 0.0
        self._chart_field.append(field_val)
        self._chart_current.append(reading.current)
        self._chart_voltage.append(reading.voltage if reading.voltage is not None else 0.0)
        self._chart_heater.append(1.0 if reading.heater_on else 0.0)

        while self._chart_times and now_ts - self._chart_times[0] > duration_s:
            self._chart_times.pop(0)
            self._chart_field.pop(0)
            self._chart_current.pop(0)
            self._chart_voltage.pop(0)
            self._chart_heater.pop(0)

        xs = [t - now_ts for t in self._chart_times]

        self._chart_widget.set_trace("Field", xs, self._chart_field)
        self._chart_widget.assign_trace_axes("Field", y_axis="left")
        self._chart_widget.set_trace_style("Field", colour=_FIELD_COLOUR.name())
        self._update_legend_value("Field", f"{field_val:.4f} T")

        # Target field as a horizontal dashed line.
        if state.target_field is not None and xs:
            target_ys = [state.target_field] * len(xs)
            self._chart_widget.set_trace("Target", xs, target_ys)
            self._chart_widget.assign_trace_axes("Target", y_axis="left")
            self._chart_widget.set_trace_style(
                "Target",
                colour=_TARGET_COLOUR.name(),
                line_style="dash",
            )
            self._update_legend_value("Target", f"{state.target_field:.4f} T")

        self._chart_widget.set_trace("Current", xs, self._chart_current)
        self._chart_widget.assign_trace_axes("Current", y_axis="electrical")
        self._chart_widget.set_trace_style("Current", colour=_CURRENT_COLOUR.name())
        self._update_legend_value("Current", f"{reading.current:.4f} A")

        self._chart_widget.set_trace("Voltage", xs, self._chart_voltage)
        self._chart_widget.assign_trace_axes("Voltage", y_axis="electrical")
        self._chart_widget.set_trace_style("Voltage", colour=_VOLTAGE_COLOUR.name())
        self._update_legend_value(
            "Voltage",
            f"{(reading.voltage if reading.voltage is not None else 0.0):.4f} V",
        )

        self._chart_widget.set_trace("Heater", xs, self._chart_heater)
        self._chart_widget.assign_trace_axes("Heater", y_axis="heater")
        self._chart_widget.set_trace_style(
            "Heater",
            colour=_HEATER_COLOUR.name(),
            line_style="dot",
        )
        self._update_legend_value(
            "Heater",
            "On" if reading.heater_on else "Off",
        )

    def _update_legend_value(self, trace: str, value: str) -> None:
        """Create or update a live-value legend entry."""
        item = self._legend_items.get(trace)
        if item is None:
            item = QTreeWidgetItem([trace, value])
            item.setData(0, Qt.ItemDataRole.UserRole, trace)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)

            style = self._chart_widget.trace_style(trace)
            colour = QColor(style.get("colour", "#808080"))
            pixmap = QPixmap(12, 12)
            pixmap.fill(colour)
            item.setIcon(0, QIcon(pixmap))

            self._legend_tree.addTopLevelItem(item)
            self._legend_items[trace] = item
            self._restore_trace_settings(trace, item)
        else:
            item.setText(1, value)

    def _on_legend_item_changed(self, item, _column: int) -> None:
        """Show/hide traces from legend checkboxes."""
        trace = item.data(0, Qt.ItemDataRole.UserRole)
        if not trace:
            return
        visible = item.checkState(0) == Qt.CheckState.Checked
        self._chart_widget.set_trace_visible(trace, visible)
        self._save_chart_settings()

    def _on_legend_context_menu(self, pos) -> None:
        """Show a trace styling context menu."""
        item = self._legend_tree.itemAt(pos)
        if item is None:
            return

        trace = item.data(0, Qt.ItemDataRole.UserRole)
        if not trace:
            return

        menu = QMenu(self)

        colour_action = menu.addAction("Colour…")

        line_menu = menu.addMenu("Line Style")
        line_actions = {
            line_menu.addAction("Solid"): "solid",
            line_menu.addAction("Dash"): "dash",
            line_menu.addAction("Dot"): "dot",
            line_menu.addAction("Dash-Dot"): "dash-dot",
        }

        marker_menu = menu.addMenu("Marker")
        marker_actions = {
            marker_menu.addAction("None"): "none",
            marker_menu.addAction("Circle"): "circle",
            marker_menu.addAction("Square"): "square",
            marker_menu.addAction("Triangle"): "triangle",
            marker_menu.addAction("Diamond"): "diamond",
            marker_menu.addAction("Cross"): "cross",
        }

        action = menu.exec(self._legend_tree.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action == colour_action:
            current = self._chart_widget.trace_style(trace).get("colour", "#808080")
            selected = QColorDialog.getColor(QColor(current), self)
            if selected.isValid():
                self._chart_widget.set_trace_style(trace, colour=selected.name())
                pixmap = QPixmap(12, 12)
                pixmap.fill(selected)
                item.setIcon(0, QIcon(pixmap))
                self._save_chart_settings()
            return

        if action in line_actions:
            self._chart_widget.set_trace_style(trace, line_style=line_actions[action])
            self._save_chart_settings()
            return

        if action in marker_actions:
            self._chart_widget.set_trace_style(trace, point_style=marker_actions[action])
            self._save_chart_settings()

    def _save_chart_settings(self) -> None:
        """Persist chart preferences."""
        settings = QSettings()

        for trace, item in self._legend_items.items():
            settings.setValue(
                f"magnetPanel/chart/traceVisibility/{trace}",
                item.checkState(0) == Qt.CheckState.Checked,
            )

            style = self._chart_widget.trace_style(trace)
            for key, value in style.items():
                settings.setValue(
                    f"magnetPanel/chart/traceStyle/{trace}/{key}",
                    value,
                )

    def _load_chart_settings(self) -> None:
        """Restore persisted chart preferences."""

    def _restore_trace_settings(self, trace: str, item: QTreeWidgetItem) -> None:
        """Restore persisted visibility and style for a trace."""
        settings = QSettings()

        visible = settings.value(
            f"magnetPanel/chart/traceVisibility/{trace}",
            True,
            type=bool,
        )

        item.setCheckState(
            0,
            Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked,
        )
        self._chart_widget.set_trace_visible(trace, visible)

        colour = settings.value(
            f"magnetPanel/chart/traceStyle/{trace}/colour",
            None,
            type=str,
        )
        line_style = settings.value(
            f"magnetPanel/chart/traceStyle/{trace}/line",
            None,
            type=str,
        )
        point_style = settings.value(
            f"magnetPanel/chart/traceStyle/{trace}/point",
            None,
            type=str,
        )

        colour = colour or None
        line_style = line_style or None
        point_style = point_style or None

        if any(v is not None for v in (colour, line_style, point_style)):
            self._chart_widget.set_trace_style(
                trace,
                colour=colour,
                line_style=line_style,
                point_style=point_style,
            )

            style = self._chart_widget.trace_style(trace)
            colour_name = style.get("colour", "#808080")
            pixmap = QPixmap(12, 12)
            pixmap.fill(QColor(colour_name))
            item.setIcon(0, QIcon(pixmap))

    # ------------------------------------------------------------------
    # Connection tab slots
    # ------------------------------------------------------------------

    def _populate_driver_combo(self) -> None:
        """Populate the driver combo with discovered MagnetController drivers."""
        self._driver_combo.clear()
        mc_drivers = self._driver_manager.drivers_by_type(MagnetController)
        for name in sorted(mc_drivers):
            self._driver_combo.addItem(name, mc_drivers[name])
        if not mc_drivers:
            self._driver_combo.addItem("(no drivers found)", None)

    def _load_connection_preferences(self) -> None:
        load_connection_preferences(self)

    def _restore_preferred_address(self) -> None:
        restore_preferred_address(self)

    @pyqtSlot(int)
    def _on_transport_changed(self, index: int) -> None:
        """Show the address fields for the selected transport.

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
            self._engine.preferred_driver_name = self._driver_combo.currentText()
            self._engine.preferred_transport_name = transport_name
            self._engine.preferred_address = address
            self._engine.save_configuration()
            self._engine.connect_driver(
                driver_name=self._driver_combo.currentText(),
                transport_name=transport_name,
                address=address,
            )
        except Exception:
            logger.exception("Failed to connect magnet driver")
            self._set_address_widget_status(transport_index, VisaResourceStatus.ERROR)
            return

        self._set_address_widget_status(transport_index, VisaResourceStatus.CONNECTED)

        # Seed the engine with the UI-configured magnet constant and limits.
        try:
            self._on_apply_limits()
        except Exception:
            logger.exception("Failed to apply initial magnet limits after connection")

    def _set_address_widget_status(self, transport_index: int, status: VisaResourceStatus) -> None:
        set_address_widget_status(self, transport_index, status)

    def _selected_transport(self, index: int) -> tuple[str, str]:
        """Return selected transport type and address string.

        Args:
            index (int):
                Index of the selected transport.

        Returns:
            (tuple[str, str]):
                Selected transport name and address.
        """
        return selected_transport(self, index)

    @pyqtSlot()
    def _on_disconnect(self) -> None:
        """Tell the engine to disconnect."""
        self._engine.disconnect_instrument()
        self._serial_port_combo.set_status(VisaResourceStatus.DISCONNECTED)
        self._gpib_resource_combo.set_status(VisaResourceStatus.DISCONNECTED)

    # ------------------------------------------------------------------
    # Configuration tab slots
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def _on_target_field_changed(self, value: float) -> None:
        """Update target current when the target field changes.

        Args:
            value (float):
                New target field in tesla.
        """
        if self._magnet_constant > 0:
            self._target_current_spin.blockSignals(True)
            try:
                self._target_current_spin.setValue(value / self._magnet_constant)
                self._target_current_label.setText(f"{self._target_current_spin.value():.4f} A")
            finally:
                self._target_current_spin.blockSignals(False)

    @pyqtSlot(object)
    def _on_target_current_changed(self, value: float) -> None:
        """Update target field when the target current changes."""
        if self._magnet_constant > 0:
            self._target_field_spin.blockSignals(True)
            try:
                self._target_field_spin.setValue(value * self._magnet_constant)
                self._target_current_label.setText(f"{value:.4f} A")
            finally:
                self._target_field_spin.blockSignals(False)

    @pyqtSlot(object)
    def _on_ramp_field_changed(self, value: float) -> None:
        """Update current ramp rate from field ramp rate."""
        if self._magnet_constant > 0:
            self._ramp_current_spin.blockSignals(True)
            try:
                self._ramp_current_spin.setValue(value / self._magnet_constant)
            finally:
                self._ramp_current_spin.blockSignals(False)

    @pyqtSlot(object)
    def _on_ramp_current_changed(self, value: float) -> None:
        """Update field ramp rate from current ramp rate."""
        if self._magnet_constant > 0:
            self._ramp_field_spin.blockSignals(True)
            try:
                self._ramp_field_spin.setValue(value * self._magnet_constant)
            finally:
                self._ramp_field_spin.blockSignals(False)

    @pyqtSlot()
    def _on_go_to_field(self) -> None:
        """Set the target field and begin ramping."""
        field = self._target_field_spin.value()
        self._engine.ramp_to_field(field)

    @pyqtSlot()
    def _on_read_target(self) -> None:
        """Read the current target field and update the target widgets."""
        state = self._read_controller_state_or_warn("Target Field")
        if state is None:
            return
        self._target_field_spin.blockSignals(True)
        try:
            if state.target_field is not None:
                self._target_field_spin.setValue(state.target_field)
        finally:
            self._target_field_spin.blockSignals(False)
        self._on_target_field_changed(self._target_field_spin.value())

    @pyqtSlot()
    def _on_apply_ramp(self) -> None:
        """Apply the ramp rate settings to the engine."""
        self._engine.set_ramp_rate_field(self._ramp_field_spin.value())

    @pyqtSlot()
    def _on_read_ramp(self) -> None:
        """Read current ramp-rate settings and update the UI."""
        state = self._read_controller_state_or_warn("Ramp Rate")
        if state is None:
            return
        if state.ramp_rate_current is not None:
            self._ramp_current_spin.blockSignals(True)
            try:
                self._ramp_current_spin.setValue(state.ramp_rate_current)
            finally:
                self._ramp_current_spin.blockSignals(False)
        if state.ramp_rate_field is not None:
            self._ramp_field_spin.blockSignals(True)
            try:
                self._ramp_field_spin.setValue(state.ramp_rate_field)
            finally:
                self._ramp_field_spin.blockSignals(False)
        elif state.ramp_rate_current is not None:
            self._on_ramp_current_changed(state.ramp_rate_current)
            return
        if state.ramp_rate_field is not None and state.ramp_rate_current is None:
            self._on_ramp_field_changed(state.ramp_rate_field)

    @pyqtSlot()
    def _on_pause_ramp(self) -> None:
        """Pause the active ramp."""
        self._engine.pause_ramp()

    @pyqtSlot()
    def _on_hold(self) -> None:
        """Hold the present output without changing field."""
        self._engine.hold()

    @pyqtSlot()
    def _on_go_to_zero(self) -> None:
        """Ramp the supply output to zero."""
        self._engine.go_to_zero()

    @pyqtSlot()
    def _on_abort_ramp(self) -> None:
        """Abort the active ramp."""
        reply = QMessageBox.question(
            self,
            "Abort Ramp",
            "Abort the active ramp?  The output will be held at its current value.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._engine.abort_ramp()

    @pyqtSlot()
    def _on_heater_on(self) -> None:
        """Energise the persistent switch heater."""
        self._engine.heater_on()

    @pyqtSlot()
    def _on_heater_off(self) -> None:
        """De-energise the persistent switch heater."""
        self._engine.heater_off()

    @pyqtSlot()
    def _on_read_heater(self) -> None:
        """Read the current persistent-switch heater state."""
        state = self._read_controller_state_or_warn("Persistent Switch Heater")
        if state is None:
            return
        self._set_heater_state_label(self._heater_state_from_state(state))
        self._update_heater_controls(state)

    @pyqtSlot()
    def _on_apply_limits(self) -> None:
        """Apply magnet constant and limits from the UI to the engine."""
        from stoner_measurement.instruments.magnet_controller import MagnetLimits

        tesla_per_amp = self._magnet_const_spin.value()
        self._magnet_constant = tesla_per_amp
        self._engine.set_magnet_constant(tesla_per_amp)
        limits = MagnetLimits(
            max_current=self._max_current_spin.value(),
            max_field=self._max_field_spin.value(),
            max_ramp_rate=self._max_ramp_spin.value(),
        )
        self._engine.set_limits(limits)
        # Refresh the equivalent-current label.
        self._on_target_field_changed(self._target_field_spin.value())
        self._on_ramp_field_changed(self._ramp_field_spin.value())

    @pyqtSlot()
    def _on_read_limits(self) -> None:
        """Read magnet constant and limits from the controller and update the UI."""
        state = self._read_controller_state_or_warn("Magnet Constants & Limits")
        if state is None:
            return
        if state.magnet_constant is not None and state.magnet_constant > 0:
            self._magnet_constant = state.magnet_constant
            self._magnet_const_spin.setValue(state.magnet_constant)

        limits = self._engine.get_limits()
        if limits is not None:
            self._max_current_spin.setValue(limits.max_current)
            if limits.max_field is not None:
                self._max_field_spin.setValue(limits.max_field)
            if limits.max_ramp_rate is not None:
                self._max_ramp_spin.setValue(limits.max_ramp_rate)

        self._on_target_field_changed(self._target_field_spin.value())
        self._on_ramp_field_changed(self._ramp_field_spin.value())

    def _set_heater_state_label(self, heater_state: HeaterState | None) -> None:
        """Update the heater state label text.

        Args:
            heater_state (HeaterState | None):
                Current rich heater state, or ``None`` when unavailable.
        """
        label = "Unknown"
        fg = "#202020"
        bg = "#d0d0d0"
        if heater_state is HeaterState.ON:
            label = "On"
            fg = "#ffffff"
            bg = "#2e7d32"
        elif heater_state is HeaterState.OFF:
            label = "Off"
            fg = "#ffffff"
            bg = "#616161"
        elif heater_state is HeaterState.WARMING:
            label = "Warming"
            fg = "#202020"
            bg = "#ffd54f"
        elif heater_state is HeaterState.COOLING:
            label = "Cooling"
            fg = "#ffffff"
            bg = "#1e88e5"
        elif heater_state is HeaterState.FAULT:
            label = "Fault"
            fg = "#ffffff"
            bg = "#c62828"

        self._heater_state_label.setText(label)
        self._heater_state_label.setStyleSheet(indicator_label_stylesheet(bg, fg))

    def _heater_state_from_state(self, state: MagnetEngineState) -> HeaterState | None:
        """Return the heater state from a controller state snapshot."""
        return state.reading.heater_state if state.reading is not None else None

    def _set_ramp_action_label(self, state: MagnetEngineState) -> None:
        """Update the ramp-action indicator from the latest controller state."""
        reading = state.reading
        label = "Unknown"
        fg = "#202020"
        bg = "#d0d0d0"
        if reading is None:
            pass
        elif reading.quench_detected or reading.state is MagnetState.QUENCH:
            label = "Quench"
            fg = "#ffffff"
            bg = "#c62828"
        elif reading.state is MagnetState.RAMPING:
            target_field = state.target_field
            field = reading.field
            if target_field is not None and abs(target_field) < 1e-9:
                label = "Ramping to zero"
                fg = "#ffffff"
                bg = "#1565c0"
            elif field is not None and target_field is not None and abs(target_field) < abs(field):
                label = "Ramping down"
                fg = "#ffffff"
                bg = "#1e88e5"
            else:
                label = "Ramping"
                fg = "#202020"
                bg = "#ffd54f"
        elif reading.state in {MagnetState.STANDBY, MagnetState.HOLDING, MagnetState.AT_TARGET}:
            label = "Holding"
            fg = "#ffffff"
            bg = "#2e7d32"
        elif reading.state is MagnetState.PERSISTENT:
            label = "Persistent"
            fg = "#ffffff"
            bg = "#616161"
        elif reading.state is MagnetState.FAULT:
            label = "Fault"
            fg = "#ffffff"
            bg = "#c62828"

        self._ramp_action_label.setText(label)
        self._ramp_action_label.setStyleSheet(indicator_label_stylesheet(bg, fg))

    def _update_ramp_controls(self, state: MagnetEngineState) -> None:
        """Update ramp-control button enabled states from the latest polled state."""
        reading = state.reading
        if reading is None:
            self._btn_pause_ramp.setEnabled(False)
            self._btn_hold.setEnabled(False)
            self._btn_zero.setEnabled(False)
            self._btn_abort_ramp.setEnabled(False)
            return

        in_transition = reading.heater_state in {HeaterState.WARMING, HeaterState.COOLING}
        ramping = reading.state is MagnetState.RAMPING
        at_zero = abs(reading.current) <= 0.01 and (reading.field is None or abs(reading.field) <= 1e-4)
        faulted = reading.state in {MagnetState.FAULT, MagnetState.QUENCH}

        self._btn_pause_ramp.setEnabled(ramping and not faulted)
        self._btn_hold.setEnabled(ramping and not faulted)
        self._btn_zero.setEnabled((not in_transition) and (not at_zero) and (not faulted))
        self._btn_abort_ramp.setEnabled(ramping and not faulted)

        self._btn_pause_ramp.setToolTip("Pause the active ramp and hold the present output.")
        self._btn_hold.setToolTip("Hold the present field/current.")
        self._btn_zero.setToolTip("Ramp the supply output to zero." if not in_transition else "Go To Zero is disabled while the heater is transitioning.")
        self._btn_abort_ramp.setToolTip("Abort the active ramp immediately.")

    def _update_heater_controls(self, state: MagnetEngineState) -> None:
        """Update heater button enabled states from the latest polled state.

        Args:
            state (MagnetEngineState):
                Controller state snapshot.
        """
        reading = state.reading
        if reading is None:
            self._btn_heater_on.setEnabled(False)
            self._btn_heater_off.setEnabled(False)
            return

        heater_state = reading.heater_state
        in_transition = heater_state in {HeaterState.WARMING, HeaterState.COOLING}
        heater_is_on = heater_state is HeaterState.ON
        heater_is_off = heater_state is HeaterState.OFF
        ramping = reading.state is MagnetState.RAMPING

        persistent_matches_target = True
        if state.target_current is not None:
            if reading.persistent_current is None:
                persistent_matches_target = False
            else:
                delta_current = abs(reading.persistent_current - state.target_current)
                tolerance = max(abs(state.target_current) * 0.01, 0.01)
                persistent_matches_target = delta_current <= tolerance

        can_turn_on = (
            (not heater_is_on)
            and (not in_transition)
            and persistent_matches_target
        )
        can_turn_off = (
            (not heater_is_off)
            and (not in_transition)
            and (not ramping)
        )

        self._btn_heater_on.setEnabled(can_turn_on)
        self._btn_heater_off.setEnabled(can_turn_off)

        if in_transition:
            self._btn_heater_on.setToolTip("Heater is transitioning; wait for a stable state.")
            self._btn_heater_off.setToolTip("Heater is transitioning; wait for a stable state.")
        else:
            self._btn_heater_on.setToolTip(
                "Enable the persistent switch heater."
                if can_turn_on
                else "Heater On is disabled because the heater is already on, or the persistent current is unknown, or the persistent current does not match the target within 1% or 10 mA."
            )
            self._btn_heater_off.setToolTip(
                "Disable the persistent switch heater."
                if can_turn_off
                else "Heater Off is disabled because the heater is off, the heater is transitioning, or the magnet is ramping."
            )

    def _read_controller_state_or_warn(self, title: str) -> MagnetEngineState | None:
        """Read current controller state and show a warning if unavailable.

        Args:
            title (str):
                Dialog title used when showing a warning.

        Returns:
            (MagnetEngineState | None):
                Fresh controller state, or ``None`` when unavailable.
        """
        state = self._engine.read_controller_state()
        if state is not None:
            return state
        QMessageBox.warning(self, title, "No instrument connected or read failed.")
        return None

    # ------------------------------------------------------------------
    # Chart tab slots
    # ------------------------------------------------------------------

    @pyqtSlot(int)
    def _on_duration_changed(self, index: int) -> None:
        """Update the chart scroll duration.

        Args:
            index (int):
                Index of the selected duration.
        """
        self._chart_duration_min = self._duration_combo.itemData(index)

    @pyqtSlot()
    def _on_clear_chart(self) -> None:
        """Clear all chart history buffers and remove curve items."""
        self._chart_times.clear()
        self._chart_field.clear()
        self._chart_current.clear()
        self._chart_voltage.clear()
        self._chart_heater.clear()
        self._legend_items.clear()
        if hasattr(self, "_legend_tree"):
            self._legend_tree.clear()
        if hasattr(self, "_chart_widget"):
            self._chart_widget.clear_all()
