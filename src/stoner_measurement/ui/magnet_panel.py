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

import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.magnet_controller import MagnetController
from stoner_measurement.instruments.transport import (
    EthernetTransport,
    GpibTransport,
    NullTransport,
    SerialTransport,
)
from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.magnet_control.types import (
    MagnetEngineState,
    MagnetEngineStatus,
    MagnetStabilityConfig,
)
from stoner_measurement.ui.widgets import (
    FILTER_GPIB,
    FILTER_SERIAL,
    VisaResourceComboBox,
    VisaResourceStatus,
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
    from PyQt6.QtWidgets import QLineEdit

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
        >>> from PyQt6.QtWidgets import QApplication
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
        self._chart_curves: dict[str, pg.PlotDataItem] = {}
        self._chart_duration_min: int = _CHART_DURATIONS[0][0]

        # Cached magnet constant for current ↔ field conversion in UI.
        self._magnet_constant: float = 1.0

        self._build_ui()
        self._connect_engine_signals()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def show_and_raise(self) -> None:
        """Show the panel and bring it to the front.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
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
        self._eth_host_edit = _line_edit("192.168.0.1")
        self._eth_port_spin = QSpinBox()
        self._eth_port_spin.setRange(1, 65535)
        self._eth_port_spin.setValue(5025)
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

        self._target_field_spin = pg.SpinBox()
        self._target_field_spin.setOpts(bounds=(-20.0, 20.0), decimals=4, suffix="T", siPrefix=True, step=0.1)
        self._target_field_spin.valueChanged.connect(self._on_target_field_changed)
        target_form.addRow("Target field:", self._target_field_spin)

        self._target_current_label = QLabel("— A")
        self._target_current_label.setToolTip("Equivalent current (computed from magnet constant)")
        target_form.addRow("Equiv. current:", self._target_current_label)

        go_btn_row = QHBoxLayout()
        self._btn_go = QPushButton("Go To Field")
        self._btn_go.setToolTip("Set the target and begin ramping")
        self._btn_go.clicked.connect(self._on_go_to_field)
        go_btn_row.addWidget(self._btn_go)
        go_btn_row.addStretch()
        target_form.addRow("", go_btn_row)
        layout.addWidget(target_group)

        # Ramp rate group.
        ramp_group = QGroupBox("Ramp Rate")
        ramp_form = QFormLayout(ramp_group)

        self._ramp_field_spin = pg.SpinBox()
        self._ramp_field_spin.setOpts(bounds=(0.001, 10.0), decimals=4, suffix="T/min", siPrefix=True)
        self._ramp_field_spin.setValue(0.1)
        ramp_form.addRow("Field ramp rate:", self._ramp_field_spin)

        self._ramp_current_spin = pg.SpinBox()
        self._ramp_current_spin.setOpts(bounds=(0.01, 1000.0), decimals=3, suffix="A/min", siPrefix=True)
        self._ramp_current_spin.setValue(1.0)
        ramp_form.addRow("Current ramp rate:", self._ramp_current_spin)

        ramp_btn_row = QHBoxLayout()
        self._btn_apply_ramp = QPushButton("Apply Ramp Rates")
        self._btn_apply_ramp.clicked.connect(self._on_apply_ramp)
        ramp_btn_row.addWidget(self._btn_apply_ramp)
        ramp_btn_row.addStretch()
        ramp_form.addRow("", ramp_btn_row)
        layout.addWidget(ramp_group)

        # Ramp control buttons.
        ramp_ctrl_group = QGroupBox("Ramp Control")
        ramp_ctrl_layout = QHBoxLayout(ramp_ctrl_group)
        self._btn_pause_ramp = QPushButton("Pause Ramp")
        self._btn_pause_ramp.clicked.connect(self._on_pause_ramp)
        self._btn_abort_ramp = QPushButton("Abort Ramp")
        self._btn_abort_ramp.clicked.connect(self._on_abort_ramp)
        ramp_ctrl_layout.addWidget(self._btn_pause_ramp)
        ramp_ctrl_layout.addWidget(self._btn_abort_ramp)
        ramp_ctrl_layout.addStretch()
        layout.addWidget(ramp_ctrl_group)

        # Persistent switch heater group.
        heater_group = QGroupBox("Persistent Switch Heater")
        heater_layout = QHBoxLayout(heater_group)
        self._btn_heater_on = QPushButton("Heater On")
        self._btn_heater_on.clicked.connect(self._on_heater_on)
        self._btn_heater_off = QPushButton("Heater Off")
        self._btn_heater_off.clicked.connect(self._on_heater_off)
        heater_layout.addWidget(self._btn_heater_on)
        heater_layout.addWidget(self._btn_heater_off)
        heater_layout.addStretch()
        layout.addWidget(heater_group)

        # Magnet constants group.
        const_group = QGroupBox("Magnet Constants && Limits")
        const_form = QFormLayout(const_group)

        self._magnet_const_spin = pg.SpinBox()
        self._magnet_const_spin.setOpts(bounds=(0.0001, 100.0), decimals=6, suffix="T/A", siPrefix=True)
        self._magnet_const_spin.setValue(0.1)
        const_form.addRow("Magnet constant:", self._magnet_const_spin)

        self._max_current_spin = pg.SpinBox()
        self._max_current_spin.setOpts(bounds=(0.0, 1000.0), decimals=2, suffix="A", siPrefix=True)
        self._max_current_spin.setValue(100.0)
        const_form.addRow("Max current:", self._max_current_spin)

        self._max_field_spin = pg.SpinBox()
        self._max_field_spin.setOpts(bounds=(0.0, 100.0), decimals=3, suffix="T", siPrefix=True)
        self._max_field_spin.setValue(10.0)
        const_form.addRow("Max field:", self._max_field_spin)

        self._max_ramp_spin = pg.SpinBox()
        self._max_ramp_spin.setOpts(bounds=(0.0, 100.0), decimals=3, suffix="T/min", siPrefix=True)
        self._max_ramp_spin.setValue(1.0)
        const_form.addRow("Max ramp rate:", self._max_ramp_spin)

        limits_btn_row = QHBoxLayout()
        self._btn_apply_limits = QPushButton("Apply Constants && Limits")
        self._btn_apply_limits.clicked.connect(self._on_apply_limits)
        limits_btn_row.addWidget(self._btn_apply_limits)
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

        splitter = QSplitter(Qt.Orientation.Vertical)

        self._field_plot = pg.PlotWidget(title="Magnetic Field")
        self._field_plot.setLabel("left", "Field", units="T")
        self._field_plot.setLabel("bottom", "Time", units="s ago")
        self._field_plot.addLegend()
        self._field_plot.showGrid(x=True, y=True, alpha=0.3)
        splitter.addWidget(self._field_plot)

        self._aux_plot = pg.PlotWidget(title="Current / Voltage / Heater")
        self._aux_plot.setLabel("left", "Value")
        self._aux_plot.setLabel("bottom", "Time", units="s ago")
        self._aux_plot.addLegend()
        self._aux_plot.showGrid(x=True, y=True, alpha=0.3)
        splitter.addWidget(self._aux_plot)

        layout.addWidget(splitter)
        return widget

    # --- Status bar ---

    def _build_status_bar(self) -> QWidget:
        """Build the bottom status bar.

        Returns:
            (QWidget):
                The assembled status bar.
        """
        bar = QWidget()
        bar.setFixedHeight(28)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(4, 2, 4, 2)
        bar_layout.setSpacing(12)

        self._status_label = QLabel("Engine: —")
        bar_layout.addWidget(self._status_label)

        self._at_target_label = QLabel("At target: —")
        bar_layout.addWidget(self._at_target_label)

        bar_layout.addStretch()

        self._updated_label = QLabel("Last updated: —")
        bar_layout.addWidget(self._updated_label)
        return bar

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

        self._update_chart(state, now_ts)

        self._updated_label.setText(
            f"Last updated: {datetime.fromtimestamp(now_ts).strftime('%H:%M:%S')}"
        )
        at_colour = "#44aa44" if state.at_target else "#cc4444"
        self._at_target_label.setText(
            f"{_colour_dot(at_colour)} At target: {'yes' if state.at_target else 'no'}"
        )

    # ------------------------------------------------------------------
    # Chart helpers
    # ------------------------------------------------------------------

    def _upsert_chart_curve(
        self,
        key: str,
        xs: list[float],
        ys: list[float],
        pen,
        plot_widget,
        name: str,
    ) -> None:
        """Create or update a named curve on *plot_widget*.

        Args:
            key (str):
                Unique curve identifier.
            xs (list[float]):
                X-axis data.
            ys (list[float]):
                Y-axis data.
            pen:
                pyqtgraph pen for new curves.
            plot_widget:
                Plot item to add new curves to.
            name (str):
                Legend name for new curves.
        """
        if key not in self._chart_curves:
            self._chart_curves[key] = plot_widget.plot(xs, ys, pen=pen, name=name)
        else:
            self._chart_curves[key].setData(xs, ys)

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

        self._upsert_chart_curve(
            "field",
            xs,
            self._chart_field,
            pg.mkPen(color=_FIELD_COLOUR, width=2),
            self._field_plot,
            "Field (T)",
        )

        # Target field as a horizontal dashed line.
        if state.target_field is not None and xs:
            target_ys = [state.target_field] * len(xs)
            self._upsert_chart_curve(
                "target",
                xs,
                target_ys,
                pg.mkPen(color=_TARGET_COLOUR, width=1, style=Qt.PenStyle.DashLine),
                self._field_plot,
                "Target",
            )

        self._upsert_chart_curve(
            "current",
            xs,
            self._chart_current,
            pg.mkPen(color=_CURRENT_COLOUR, width=2),
            self._aux_plot,
            "Current (A)",
        )
        self._upsert_chart_curve(
            "voltage",
            xs,
            self._chart_voltage,
            pg.mkPen(color=_VOLTAGE_COLOUR, width=2),
            self._aux_plot,
            "Voltage (V)",
        )
        self._upsert_chart_curve(
            "heater",
            xs,
            self._chart_heater,
            pg.mkPen(color=_HEATER_COLOUR, width=1, style=Qt.PenStyle.DotLine),
            self._aux_plot,
            "Heater",
        )

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

    @pyqtSlot(int)
    def _on_transport_changed(self, index: int) -> None:
        """Show the address fields for the selected transport.

        Args:
            index (int):
                Index of the selected transport in the transport combo box.
        """
        for w in (
            self._serial_form_widget,
            self._gpib_form_widget,
            self._ethernet_form_widget,
            self._null_form_widget,
        ):
            w.hide()
        [
            self._serial_form_widget,
            self._gpib_form_widget,
            self._ethernet_form_widget,
            self._null_form_widget,
        ][index].show()

    @pyqtSlot()
    def _on_connect(self) -> None:
        """Build transport + driver and connect to the engine."""
        driver_cls = self._driver_combo.currentData()
        if driver_cls is None:
            return
        transport_index = self._transport_combo.currentIndex()
        self._set_address_widget_status(transport_index, VisaResourceStatus.CONNECTING)
        try:
            transport = self._build_transport(transport_index)
        except Exception:
            logger.exception("Failed to build transport")
            self._set_address_widget_status(transport_index, VisaResourceStatus.ERROR)
            return

        try:
            from stoner_measurement.instruments.protocol.oxford import OxfordProtocol

            name = self._driver_combo.currentText().lower()
            if "oxford" in name or "ips" in name:
                protocol = OxfordProtocol()
            else:
                from stoner_measurement.instruments.protocol.lakeshore import LakeshoreProtocol

                protocol = LakeshoreProtocol()
            transport.open()
            driver = driver_cls(transport=transport, protocol=protocol)
        except Exception:
            logger.exception("Failed to instantiate magnet driver")
            self._set_address_widget_status(transport_index, VisaResourceStatus.ERROR)
            return

        self._engine.connect_instrument(driver)
        self._set_address_widget_status(transport_index, VisaResourceStatus.CONNECTED)

        # Seed the engine with the UI-configured magnet constant and limits.
        try:
            self._on_apply_limits()
        except Exception:
            logger.exception("Failed to apply initial magnet limits after connection")

    def _set_address_widget_status(self, transport_index: int, status: VisaResourceStatus) -> None:
        """Update connection-status colour on the active address widget.

        Args:
            transport_index (int):
                Index of the currently selected transport.
            status (VisaResourceStatus):
                Status to apply.
        """
        if transport_index == 0:
            self._serial_port_combo.set_status(status)
        elif transport_index == 1:
            self._gpib_resource_combo.set_status(status)

    def _build_transport(self, index: int):
        """Instantiate the selected transport.

        Args:
            index (int):
                Index of the selected transport.

        Returns:
            (BaseTransport):
                Constructed transport instance (not yet opened).
        """
        if index == 0:  # Serial
            port = self._serial_port_combo.current_resource() or "/dev/ttyUSB0"
            baud = self._serial_baud_combo.currentData()
            return SerialTransport(port=port, baud_rate=baud)
        if index == 1:  # GPIB
            resource = self._gpib_resource_combo.current_resource() or "GPIB0::2::INSTR"
            return GpibTransport.from_resource_string(resource)
        if index == 2:  # Ethernet
            host = self._eth_host_edit.text().strip()
            port = self._eth_port_spin.value()
            return EthernetTransport(host=host, port=port)
        return NullTransport()  # Null (test)

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
        """Update the equivalent-current label when the target field changes.

        Args:
            value (float):
                New target field in tesla.
        """
        if self._magnet_constant > 0:
            equiv_current = value / self._magnet_constant
            self._target_current_label.setText(f"{equiv_current:.4f} A")
        else:
            self._target_current_label.setText("— A")

    @pyqtSlot()
    def _on_go_to_field(self) -> None:
        """Set the target field and begin ramping."""
        field = self._target_field_spin.value()
        self._engine.ramp_to_field(field)

    @pyqtSlot()
    def _on_apply_ramp(self) -> None:
        """Apply the ramp rate settings to the engine."""
        self._engine.set_ramp_rate_field(self._ramp_field_spin.value())
        self._engine.set_ramp_rate_current(self._ramp_current_spin.value())

    @pyqtSlot()
    def _on_pause_ramp(self) -> None:
        """Pause the active ramp."""
        self._engine.pause_ramp()

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
        for key, curve in self._chart_curves.items():
            try:
                if key in ("current", "voltage", "heater"):
                    self._aux_plot.removeItem(curve)
                else:
                    self._field_plot.removeItem(curve)
            except Exception:
                pass
        self._chart_curves.clear()
