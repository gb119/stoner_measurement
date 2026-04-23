"""Non-blocking temperature controller panel window.

Provides :class:`TemperatureControlPanel`, a non-modal :class:`~PyQt6.QtWidgets.QWidget`
window that lets the user configure and monitor a temperature controller through
the :class:`~stoner_measurement.temperature_control.engine.TemperatureControllerEngine`
singleton.

The panel has four sections arranged in a :class:`~PyQt6.QtWidgets.QTabWidget`:

* **Connection** — driver type, transport type, address, Connect/Disconnect.
* **Control** — setpoint, mode, ramp, PID, needle valve per loop.
* **Stability** — tolerance, window, minimum rate-of-change settings.
* **Chart** — live scrolling pyqtgraph plot of temperatures, setpoints,
  heater output, and needle valve.

A status bar at the bottom shows the last-updated timestamp, engine status,
and at-setpoint/stable boolean indicators.

Closing the window only hides it; the engine keeps running.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.temperature_controller import ControlMode, TemperatureController
from stoner_measurement.instruments.transport import (
    EthernetTransport,
    GpibTransport,
    NullTransport,
    SerialTransport,
)
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.temperature_control.types import (
    EngineStatus,
    StabilityConfig,
    TemperatureEngineState,
)

logger = logging.getLogger(__name__)

#: Colours assigned to successive temperature channels on the chart.
_CHANNEL_COLOURS = [
    QColor("royalblue"),
    QColor("darkorange"),
    QColor("forestgreen"),
    QColor("firebrick"),
    QColor("mediumpurple"),
]

#: Colour for setpoint trace lines.
_SETPOINT_COLOUR = QColor("black")

#: Colour for heater output trace.
_HEATER_COLOUR = QColor("saddlebrown")

#: Colour for needle valve trace.
_NEEDLE_COLOUR = QColor("teal")

#: Available chart duration options (minutes, label).
_CHART_DURATIONS: list[tuple[int, str]] = [
    (5, "5 min"),
    (10, "10 min"),
    (30, "30 min"),
    (60, "60 min"),
]

#: Status indicator colours.
_STATUS_COLOURS: dict[EngineStatus, str] = {
    EngineStatus.STOPPED: "#888888",
    EngineStatus.DISCONNECTED: "#cc4444",
    EngineStatus.CONNECTED: "#cc8800",
    EngineStatus.POLLING: "#44aa44",
    EngineStatus.ERROR: "#cc0000",
}


def _colour_dot(colour: str, size: int = 12) -> str:
    """Return an HTML span rendering a filled coloured circle for use in labels.

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


class TemperatureControlPanel(QWidget):
    """Non-blocking window for temperature controller configuration and monitoring.

    Opens from the *Temperature* menu or toolbar button.  Communicates
    exclusively through the :class:`~stoner_measurement.temperature_control.engine.TemperatureControllerEngine`
    singleton — never talking to instrument hardware directly.

    Opening the window a second time raises the existing instance rather than
    creating a new one (call :meth:`show_and_raise`).

    Closing the window hides it; the engine keeps running.

    Args:
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.ui.temperature_panel import TemperatureControlPanel
        >>> panel = TemperatureControlPanel()
        >>> panel.windowTitle()
        'Temperature Control'
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Temperature Control")
        self.setMinimumSize(700, 560)
        self.setWindowFlags(Qt.WindowType.Window)

        self._engine = TemperatureControllerEngine.instance()
        self._driver_manager = InstrumentDriverManager()
        self._driver_manager.discover()

        # Chart data buffers — timestamps (seconds since epoch) and values.
        self._chart_times: dict[str, list[float]] = {}
        self._chart_values: dict[str, list[float]] = {}
        self._chart_curves: dict[str, pg.PlotDataItem] = {}

        self._chart_duration_min: int = _CHART_DURATIONS[0][0]

        # Current capabilities (populated after connection).
        self._capabilities = None

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
            >>> from stoner_measurement.ui.temperature_panel import TemperatureControlPanel
            >>> panel = TemperatureControlPanel()
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
        self._tabs.addTab(self._build_control_tab(), "Control")
        self._tabs.addTab(self._build_stability_tab(), "Stability")
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
        self._serial_port_edit = _line_edit("/dev/ttyUSB0")
        self._serial_baud_combo = QComboBox()
        for baud in (9600, 19200, 38400, 57600, 115200):
            self._serial_baud_combo.addItem(str(baud), baud)
        form.addRow("Port:", self._serial_port_edit)
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
        self._gpib_resource_edit = _line_edit("GPIB0::2::INSTR")
        form.addRow("VISA resource:", self._gpib_resource_edit)
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

    # --- Control tab ---

    def _build_control_tab(self) -> QWidget:
        """Build the Control tab widget.

        Returns:
            (QWidget):
                The assembled control tab.
        """
        self._control_widget = QWidget()
        self._control_layout = QVBoxLayout(self._control_widget)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._control_widget)
        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        # Loop groups are populated dynamically after connection.
        self._loop_groups: dict[int, _LoopControlGroup] = {}
        # Needle valve row (shown only for cryogen instruments).
        self._needle_group = QGroupBox("Needle Valve / Gas Flow")
        needle_form = QFormLayout(self._needle_group)
        self._needle_spin = QDoubleSpinBox()
        self._needle_spin.setRange(0.0, 100.0)
        self._needle_spin.setSuffix(" %")
        self._needle_spin.setSingleStep(1.0)
        self._needle_apply_btn = QPushButton("Apply")
        self._needle_apply_btn.clicked.connect(self._on_apply_needle)
        needle_row = QHBoxLayout()
        needle_row.addWidget(self._needle_spin)
        needle_row.addWidget(self._needle_apply_btn)
        needle_form.addRow("Position:", needle_row)
        self._control_layout.addWidget(self._needle_group)
        self._needle_group.hide()
        self._control_layout.addStretch()
        return wrapper

    # --- Stability tab ---

    def _build_stability_tab(self) -> QWidget:
        """Build the Stability settings tab.

        Returns:
            (QWidget):
                The assembled stability tab.
        """
        widget = QWidget()
        form = QFormLayout(widget)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._stab_tolerance_spin = QDoubleSpinBox()
        self._stab_tolerance_spin.setRange(0.001, 10.0)
        self._stab_tolerance_spin.setDecimals(3)
        self._stab_tolerance_spin.setSuffix(" K")
        self._stab_tolerance_spin.setValue(0.1)
        form.addRow("Tolerance:", self._stab_tolerance_spin)

        self._stab_window_spin = QDoubleSpinBox()
        self._stab_window_spin.setRange(1.0, 3600.0)
        self._stab_window_spin.setSuffix(" s")
        self._stab_window_spin.setValue(60.0)
        form.addRow("Stability window:", self._stab_window_spin)

        self._stab_min_rate_spin = QDoubleSpinBox()
        self._stab_min_rate_spin.setRange(0.0001, 1.0)
        self._stab_min_rate_spin.setDecimals(4)
        self._stab_min_rate_spin.setSuffix(" K/min")
        self._stab_min_rate_spin.setValue(0.005)
        form.addRow("Max rate of change:", self._stab_min_rate_spin)

        self._stab_holdoff_spin = QDoubleSpinBox()
        self._stab_holdoff_spin.setRange(0.0, 120.0)
        self._stab_holdoff_spin.setSuffix(" s")
        self._stab_holdoff_spin.setValue(5.0)
        form.addRow("Unstable holdoff:", self._stab_holdoff_spin)

        apply_btn = QPushButton("Apply Stability Settings")
        apply_btn.clicked.connect(self._on_apply_stability)
        form.addRow("", apply_btn)

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

        # Controls row
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Duration:"))
        self._duration_combo = QComboBox()
        for minutes, label in _CHART_DURATIONS:
            self._duration_combo.addItem(label, minutes)
        self._duration_combo.currentIndexChanged.connect(self._on_duration_changed)
        controls.addWidget(self._duration_combo)
        controls.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._on_clear_chart)
        controls.addWidget(clear_btn)
        layout.addLayout(controls)

        # Splitter: temperature plot (top) / heater+needle plot (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._temp_plot = pg.PlotWidget(title="Temperature")
        self._temp_plot.setLabel("left", "Temperature", units="K")
        self._temp_plot.setLabel("bottom", "Time", units="s ago")
        self._temp_plot.addLegend()
        self._temp_plot.showGrid(x=True, y=True, alpha=0.3)
        splitter.addWidget(self._temp_plot)

        self._aux_plot = pg.PlotWidget(title="Heater / Needle Valve")
        self._aux_plot.setLabel("left", "Output", units="%")
        self._aux_plot.setLabel("bottom", "Time", units="s ago")
        self._aux_plot.addLegend()
        self._aux_plot.showGrid(x=True, y=True, alpha=0.3)
        splitter.addWidget(self._aux_plot)

        layout.addWidget(splitter)
        return widget

    # --- Status bar ---

    def _build_status_bar(self) -> QWidget:
        """Build the bottom status bar widget.

        Returns:
            (QWidget):
                The assembled status bar.
        """
        bar = QWidget()
        bar.setFixedHeight(28)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(12)

        self._status_label = QLabel("Engine: —")
        layout.addWidget(self._status_label)

        self._at_setpoint_label = QLabel("At setpoint: —")
        layout.addWidget(self._at_setpoint_label)

        self._stable_label = QLabel("Stable: —")
        layout.addWidget(self._stable_label)

        layout.addStretch()

        self._updated_label = QLabel("Last updated: —")
        layout.addWidget(self._updated_label)

        return bar

    # ------------------------------------------------------------------
    # Signal connections
    # ------------------------------------------------------------------

    def _connect_engine_signals(self) -> None:
        """Connect to engine publisher signals for live updates."""
        pub = self._engine.publisher
        pub.state_updated.connect(self._on_state_updated)
        pub.engine_status_changed.connect(self._on_engine_status_changed)
        # Reflect current status immediately.
        self._on_engine_status_changed(self._engine.status)

    # ------------------------------------------------------------------
    # Engine signal slots
    # ------------------------------------------------------------------

    @pyqtSlot(EngineStatus)
    def _on_engine_status_changed(self, status: EngineStatus) -> None:
        """Update status indicator and button states when engine status changes.

        Args:
            status (EngineStatus):
                The new engine status.
        """
        colour = _STATUS_COLOURS.get(status, "#888888")
        dot = _colour_dot(colour)
        self._status_label.setText(f"{dot} Engine: {status.value}")
        connected = status in (EngineStatus.CONNECTED, EngineStatus.POLLING)
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)

    @pyqtSlot(TemperatureEngineState)
    def _on_state_updated(self, state: TemperatureEngineState) -> None:
        """Update all UI elements and chart traces from a new engine state.

        Args:
            state (TemperatureEngineState):
                The latest engine state snapshot.
        """
        now_ts = datetime.now(tz=UTC).timestamp()

        # Update control-loop groups with live readings.
        for loop, group in self._loop_groups.items():
            group.update_live(
                setpoint=state.setpoints.get(loop, 0.0),
                heater_output=state.heater_outputs.get(loop, 0.0),
                mode=state.loop_modes.get(loop),
            )

        # Needle valve
        if state.needle_valve is not None:
            self._needle_spin.blockSignals(True)
            self._needle_spin.setValue(state.needle_valve)
            self._needle_spin.blockSignals(False)

        # Update chart buffers and curves.
        self._update_chart(state, now_ts)

        # Status bar
        self._updated_label.setText(
            f"Last updated: {datetime.fromtimestamp(now_ts).strftime('%H:%M:%S')}"
        )
        all_at = all(state.at_setpoint.values()) if state.at_setpoint else None
        all_stable = all(state.stable.values()) if state.stable else None
        at_colour = "#44aa44" if all_at else ("#cc4444" if all_at is False else "#888888")
        st_colour = "#44aa44" if all_stable else ("#cc4444" if all_stable is False else "#888888")
        self._at_setpoint_label.setText(
            f"{_colour_dot(at_colour)} At setpoint: {'yes' if all_at else 'no' if all_at is False else '—'}"
        )
        self._stable_label.setText(
            f"{_colour_dot(st_colour)} Stable: {'yes' if all_stable else 'no' if all_stable is False else '—'}"
        )

    # ------------------------------------------------------------------
    # Chart helpers
    # ------------------------------------------------------------------

    def _update_chart(self, state: TemperatureEngineState, now_ts: float) -> None:
        """Append the latest readings to chart buffers and redraw curves.

        Args:
            state (TemperatureEngineState):
                Current state snapshot with channel readings and loop data.
            now_ts (float):
                Current time as a Unix timestamp.
        """
        duration_s = self._chart_duration_min * 60.0

        for i, (ch, reading) in enumerate(state.readings.items()):
            ts = reading.timestamp.timestamp()
            buf_t = self._chart_times.setdefault(ch, [])
            buf_v = self._chart_values.setdefault(ch, [])
            buf_t.append(ts)
            buf_v.append(reading.value)
            # Trim old data.
            while buf_t and now_ts - buf_t[0] > duration_s:
                buf_t.pop(0)
                buf_v.pop(0)
            xs = [t - now_ts for t in buf_t]
            colour = _CHANNEL_COLOURS[i % len(_CHANNEL_COLOURS)]
            key = f"T_{ch}"
            if key not in self._chart_curves:
                pen = pg.mkPen(color=colour, width=2)
                self._chart_curves[key] = self._temp_plot.plot(
                    xs, buf_v, pen=pen, name=f"T {ch}"
                )
            else:
                self._chart_curves[key].setData(xs, buf_v)

        # Setpoint traces
        for loop, sp in state.setpoints.items():
            key = f"SP_{loop}"
            ts_buf = self._chart_times.get(next(iter(state.readings), ""), [])
            if not ts_buf:
                continue
            xs = [t - now_ts for t in ts_buf]
            sp_buf = self._chart_values.setdefault(key, [])
            while len(sp_buf) < len(xs):
                sp_buf.insert(0, sp)
            while len(sp_buf) > len(xs):
                sp_buf.pop(0)
            sp_buf[-1] = sp
            if key not in self._chart_curves:
                pen = pg.mkPen(color=_SETPOINT_COLOUR, width=1, style=Qt.PenStyle.DashLine)
                self._chart_curves[key] = self._temp_plot.plot(
                    xs, sp_buf, pen=pen, name=f"SP {loop}"
                )
            else:
                self._chart_curves[key].setData(xs, sp_buf)

        # Heater output traces
        ts_ref = self._chart_times.get(next(iter(state.readings), ""), [])
        if ts_ref:
            xs = [t - now_ts for t in ts_ref]
            for loop, ho in state.heater_outputs.items():
                key = f"H_{loop}"
                h_buf = self._chart_values.setdefault(key, [])
                while len(h_buf) < len(xs):
                    h_buf.insert(0, ho)
                while len(h_buf) > len(xs):
                    h_buf.pop(0)
                h_buf[-1] = ho
                if key not in self._chart_curves:
                    pen = pg.mkPen(color=_HEATER_COLOUR, width=2)
                    self._chart_curves[key] = self._aux_plot.plot(
                        xs, h_buf, pen=pen, name=f"Heater {loop}"
                    )
                else:
                    self._chart_curves[key].setData(xs, h_buf)

            # Needle valve
            if state.needle_valve is not None:
                nv = state.needle_valve
                key = "NV"
                nv_buf = self._chart_values.setdefault(key, [])
                while len(nv_buf) < len(xs):
                    nv_buf.insert(0, nv)
                while len(nv_buf) > len(xs):
                    nv_buf.pop(0)
                nv_buf[-1] = nv
                if key not in self._chart_curves:
                    pen = pg.mkPen(color=_NEEDLE_COLOUR, width=2, style=Qt.PenStyle.DotLine)
                    self._chart_curves[key] = self._aux_plot.plot(
                        xs, nv_buf, pen=pen, name="Needle valve"
                    )
                else:
                    self._chart_curves[key].setData(xs, nv_buf)

    # ------------------------------------------------------------------
    # Connection tab slots
    # ------------------------------------------------------------------

    def _populate_driver_combo(self) -> None:
        """Populate the driver combo with discovered TemperatureController drivers."""
        self._driver_combo.clear()
        tc_drivers = self._driver_manager.drivers_by_type(TemperatureController)
        for name in sorted(tc_drivers):
            self._driver_combo.addItem(name, tc_drivers[name])
        if not tc_drivers:
            self._driver_combo.addItem("(no drivers found)", None)

    @pyqtSlot(int)
    def _on_transport_changed(self, index: int) -> None:
        """Show the address fields appropriate to the selected transport type.

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
        """Build transport + driver and tell the engine to connect."""
        driver_cls = self._driver_combo.currentData()
        if driver_cls is None:
            return
        transport_index = self._transport_combo.currentIndex()
        try:
            transport = self._build_transport(transport_index)
        except Exception:
            logger.exception("Failed to build transport")
            return

        try:
            from stoner_measurement.instruments.protocol.lakeshore import LakeshoreProtocol
            from stoner_measurement.instruments.protocol.oxford import OxfordProtocol

            # Select a default protocol based on driver name heuristics.
            name = self._driver_combo.currentText().lower()
            if "oxford" in name or "itc" in name or "mercury" in name:
                protocol = OxfordProtocol()
            else:
                protocol = LakeshoreProtocol()
            transport.open()
            driver = driver_cls(transport=transport, protocol=protocol)
        except Exception:
            logger.exception("Failed to instantiate driver")
            return

        self._engine.connect_instrument(driver)

        # Populate control tab with loop groups.
        try:
            caps = driver.get_capabilities()
            self._capabilities = caps
            self._rebuild_loop_groups(caps)
            if caps.has_cryogen_control:
                self._needle_group.show()
            else:
                self._needle_group.hide()
        except Exception:
            logger.exception("Failed to read capabilities after connection")

    def _build_transport(self, index: int):
        """Instantiate the selected transport.

        Args:
            index (int):
                Index of the selected transport in the transport combo box.

        Returns:
            (BaseTransport):
                The constructed transport instance (not yet opened).
        """
        if index == 0:  # Serial
            port = self._serial_port_edit.text().strip()
            baud = self._serial_baud_combo.currentData()
            return SerialTransport(port=port, baud_rate=baud)
        if index == 1:  # GPIB
            resource = self._gpib_resource_edit.text().strip()
            return GpibTransport(resource_string=resource)
        if index == 2:  # Ethernet
            host = self._eth_host_edit.text().strip()
            port = self._eth_port_spin.value()
            return EthernetTransport(host=host, port=port)
        return NullTransport()  # Null (test)

    @pyqtSlot()
    def _on_disconnect(self) -> None:
        """Tell the engine to disconnect."""
        self._engine.disconnect_instrument()
        self._capabilities = None
        self._clear_loop_groups()
        self._needle_group.hide()

    # ------------------------------------------------------------------
    # Control tab slots
    # ------------------------------------------------------------------

    def _rebuild_loop_groups(self, caps) -> None:
        """Rebuild per-loop control groups from the driver capabilities.

        Args:
            caps (ControllerCapabilities):
                The driver's capability descriptor.
        """
        self._clear_loop_groups()
        stretch_item = self._control_layout.takeAt(self._control_layout.count() - 1)
        for lp in caps.loop_numbers:
            group = _LoopControlGroup(lp, self._engine)
            self._loop_groups[lp] = group
            insert_pos = self._control_layout.count()
            self._control_layout.insertWidget(insert_pos, group)
        self._control_layout.addStretch()
        if stretch_item:
            del stretch_item

    def _clear_loop_groups(self) -> None:
        """Remove all existing per-loop control group widgets."""
        for group in self._loop_groups.values():
            self._control_layout.removeWidget(group)
            group.deleteLater()
        self._loop_groups.clear()

    @pyqtSlot()
    def _on_apply_needle(self) -> None:
        """Send the needle valve position to the engine."""
        self._engine.set_needle_valve(self._needle_spin.value())

    # ------------------------------------------------------------------
    # Stability tab slot
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_apply_stability(self) -> None:
        """Apply the stability settings to the engine."""
        cfg = StabilityConfig(
            tolerance_k=self._stab_tolerance_spin.value(),
            window_s=self._stab_window_spin.value(),
            min_rate=self._stab_min_rate_spin.value(),
            unstable_holdoff_s=self._stab_holdoff_spin.value(),
        )
        self._engine.set_stability_config(cfg)

    # ------------------------------------------------------------------
    # Chart tab slots
    # ------------------------------------------------------------------

    @pyqtSlot(int)
    def _on_duration_changed(self, index: int) -> None:
        """Update the chart scroll duration.

        Args:
            index (int):
                Index of the selected duration in the duration combo box.
        """
        self._chart_duration_min = self._duration_combo.itemData(index)

    @pyqtSlot()
    def _on_clear_chart(self) -> None:
        """Clear all chart history buffers and remove all curve items."""
        self._chart_times.clear()
        self._chart_values.clear()
        for key, curve in self._chart_curves.items():
            try:
                if key.startswith("H_") or key == "NV":
                    self._aux_plot.removeItem(curve)
                else:
                    self._temp_plot.removeItem(curve)
            except Exception:
                pass
        self._chart_curves.clear()


# ---------------------------------------------------------------------------
# Per-loop control group widget
# ---------------------------------------------------------------------------


class _LoopControlGroup(QGroupBox):
    """A group box containing all control inputs for a single PID loop.

    Args:
        loop (int):
            Loop number (1-based).
        engine (TemperatureControllerEngine):
            Engine instance to send commands to.
    """

    def __init__(self, loop: int, engine: TemperatureControllerEngine) -> None:
        super().__init__(f"Loop {loop}")
        self._loop = loop
        self._engine = engine
        self._build()

    def _build(self) -> None:
        """Build the form layout."""
        form = QFormLayout(self)

        # Live readback labels
        self._setpoint_label = QLabel("—")
        self._heater_label = QLabel("—")
        self._mode_label = QLabel("—")
        form.addRow("Setpoint (live):", self._setpoint_label)
        form.addRow("Heater output:", self._heater_label)
        form.addRow("Mode (live):", self._mode_label)

        # Editable setpoint
        self._sp_spin = QDoubleSpinBox()
        self._sp_spin.setRange(0.0, 1000.0)
        self._sp_spin.setSuffix(" K")
        self._sp_spin.setDecimals(3)
        sp_row = QHBoxLayout()
        sp_row.addWidget(self._sp_spin)
        sp_apply = QPushButton("Apply")
        sp_apply.clicked.connect(self._on_apply_setpoint)
        sp_row.addWidget(sp_apply)
        form.addRow("New setpoint:", sp_row)

        # Control mode
        self._mode_combo = QComboBox()
        for mode in ControlMode:
            self._mode_combo.addItem(mode.value.replace("_", " ").title(), mode)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self._mode_combo)
        mode_apply = QPushButton("Apply")
        mode_apply.clicked.connect(self._on_apply_mode)
        mode_row.addWidget(mode_apply)
        form.addRow("Control mode:", mode_row)

        # Ramp
        self._ramp_enable = QCheckBox("Enable")
        self._ramp_rate_spin = QDoubleSpinBox()
        self._ramp_rate_spin.setRange(0.0, 100.0)
        self._ramp_rate_spin.setSuffix(" K/min")
        self._ramp_rate_spin.setDecimals(3)
        ramp_row = QHBoxLayout()
        ramp_row.addWidget(self._ramp_enable)
        ramp_row.addWidget(self._ramp_rate_spin)
        ramp_apply = QPushButton("Apply")
        ramp_apply.clicked.connect(self._on_apply_ramp)
        ramp_row.addWidget(ramp_apply)
        form.addRow("Ramp:", ramp_row)

        # Heater range
        self._heater_range_spin = QSpinBox()
        self._heater_range_spin.setRange(0, 5)
        self._heater_range_spin.setToolTip("Heater range index (0 = off; instrument-specific)")
        hr_row = QHBoxLayout()
        hr_row.addWidget(self._heater_range_spin)
        hr_apply = QPushButton("Apply")
        hr_apply.clicked.connect(self._on_apply_heater_range)
        hr_row.addWidget(hr_apply)
        form.addRow("Heater range:", hr_row)

        # PID
        self._pid_p_spin = QDoubleSpinBox()
        self._pid_p_spin.setRange(0.0, 1000.0)
        self._pid_p_spin.setDecimals(3)
        self._pid_i_spin = QDoubleSpinBox()
        self._pid_i_spin.setRange(0.0, 1000.0)
        self._pid_i_spin.setDecimals(3)
        self._pid_d_spin = QDoubleSpinBox()
        self._pid_d_spin.setRange(0.0, 1000.0)
        self._pid_d_spin.setDecimals(3)
        pid_row = QHBoxLayout()
        pid_row.addWidget(QLabel("P:"))
        pid_row.addWidget(self._pid_p_spin)
        pid_row.addWidget(QLabel("I:"))
        pid_row.addWidget(self._pid_i_spin)
        pid_row.addWidget(QLabel("D:"))
        pid_row.addWidget(self._pid_d_spin)
        pid_apply = QPushButton("Apply")
        pid_apply.clicked.connect(self._on_apply_pid)
        pid_row.addWidget(pid_apply)
        form.addRow("PID:", pid_row)

    # --- Live update ---

    def update_live(self, setpoint: float, heater_output: float, mode) -> None:
        """Refresh live-readback labels.

        Args:
            setpoint (float):
                Current setpoint in Kelvin.
            heater_output (float):
                Current heater output percentage.
            mode (ControlMode | None):
                Current control mode.
        """
        self._setpoint_label.setText(f"{setpoint:.3f} K")
        self._heater_label.setText(f"{heater_output:.1f} %")
        mode_text = mode.value.replace("_", " ").title() if mode is not None else "—"
        self._mode_label.setText(mode_text)

    # --- Apply slots ---

    @pyqtSlot()
    def _on_apply_setpoint(self) -> None:
        """Send the new setpoint to the engine."""
        self._engine.set_setpoint(self._loop, self._sp_spin.value())

    @pyqtSlot()
    def _on_apply_mode(self) -> None:
        """Send the selected control mode to the engine."""
        mode = self._mode_combo.currentData()
        if mode is not None:
            self._engine.set_loop_mode(self._loop, mode)

    @pyqtSlot()
    def _on_apply_ramp(self) -> None:
        """Send ramp settings to the engine."""
        self._engine.set_ramp(
            self._loop,
            rate=self._ramp_rate_spin.value(),
            enabled=self._ramp_enable.isChecked(),
        )

    @pyqtSlot()
    def _on_apply_heater_range(self) -> None:
        """Send the heater range to the engine."""
        self._engine.set_heater_range(self._loop, self._heater_range_spin.value())

    @pyqtSlot()
    def _on_apply_pid(self) -> None:
        """Send PID parameters to the engine."""
        self._engine.set_pid(
            self._loop,
            p=self._pid_p_spin.value(),
            i=self._pid_i_spin.value(),
            d=self._pid_d_spin.value(),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _line_edit(placeholder: str = "") -> QWidget:
    """Return a QLineEdit-like widget via QWidget (avoids import cycle).

    Args:
        placeholder (str):
            Placeholder text.

    Returns:
        (QWidget):
            A line-edit widget.
    """
    from PyQt6.QtWidgets import QLineEdit

    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setText(placeholder)
    return w
