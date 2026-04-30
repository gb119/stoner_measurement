"""Non-blocking temperature controller panel window.

Provides :class:`TemperatureControlPanel`, a non-modal :class:`~PyQt6.QtWidgets.QWidget`
window that lets the user configure and monitor a temperature controller through
the :class:`~stoner_measurement.temperature_control.engine.TemperatureControllerEngine`
singleton.

The panel has five sections arranged in a :class:`~PyQt6.QtWidgets.QTabWidget`:

* **Connection** — driver type, transport type, address, Connect/Disconnect.
* **Control** — setpoint, mode, ramp, PID, needle valve per loop.
* **Stability** — tolerance, window, minimum rate-of-change settings.
* **Zone Table** — read/edit/write the zone PID/heater-range/ramp-rate table;
  only enabled when the connected driver advertises ``has_zone = True``.
* **Chart** — live scrolling pyqtgraph plot of temperatures, setpoints,
  heater output, and needle valve.

A status bar at the bottom shows the last-updated timestamp, engine status,
and at-setpoint/stable boolean indicators.

Closing the window only hides it; the engine keeps running.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.temperature_controller import (
    ControllerCapabilities,
    ControlMode,
    InputChannelSettings,
    TemperatureController,
    ZoneEntry,
)
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
from stoner_measurement.ui.widgets import (
    FILTER_GPIB,
    FILTER_SERIAL,
    PercentSliderWidget,
    SISpinBox,
    VisaResourceComboBox,
    VisaResourceStatus,
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
        self._zone_tab_index = self._tabs.count()
        self._tabs.addTab(self._build_zone_tab(), "Zone Table")
        self._tabs.setTabEnabled(self._zone_tab_index, False)
        self._input_settings_tab_index = self._tabs.count()
        self._tabs.addTab(self._build_input_settings_tab(), "Input Settings")
        self._tabs.setTabEnabled(self._input_settings_tab_index, False)
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
        self._needle_spin = PercentSliderWidget()
        self._needle_spin.setToolTip("Needle valve / gas flow position (0–100 %)")
        self._needle_apply_btn = QPushButton("Apply")
        self._needle_apply_btn.clicked.connect(self._on_apply_needle)
        self._needle_read_btn = QPushButton("Read")
        self._needle_read_btn.setToolTip("Read current needle valve position from instrument")
        self._needle_read_btn.clicked.connect(self._on_read_needle)
        needle_row = QHBoxLayout()
        needle_row.addWidget(self._needle_spin)
        needle_row.addWidget(self._needle_apply_btn)
        needle_row.addWidget(self._needle_read_btn)
        needle_form.addRow("Position:", needle_row)
        # Gas auto mode toggle (shown only for drivers with has_gas_auto_mode).
        self._gas_auto_check = QCheckBox("Automatic gas flow")
        self._gas_auto_check.setToolTip(
            "When checked the controller manages the needle valve automatically"
        )
        self._gas_auto_check.stateChanged.connect(self._on_gas_auto_changed)
        self._gas_auto_row_label = QLabel("Gas mode:")
        needle_form.addRow(self._gas_auto_row_label, self._gas_auto_check)
        self._gas_auto_row_label.hide()
        self._gas_auto_check.hide()
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

        self._stab_tolerance_spin = SISpinBox()
        self._stab_tolerance_spin.setOpts(bounds=(0.001, 10.0), decimals=3, suffix="K", siPrefix=True)
        self._stab_tolerance_spin.setValue(0.1)
        form.addRow("Tolerance:", self._stab_tolerance_spin)

        self._stab_window_spin = SISpinBox()
        self._stab_window_spin.setOpts(bounds=(1.0, 3600.0), suffix="s", siPrefix=True)
        self._stab_window_spin.setValue(60.0)
        form.addRow("Stability window:", self._stab_window_spin)

        self._stab_min_rate_spin = SISpinBox()
        self._stab_min_rate_spin.setOpts(bounds=(0.0001, 1.0), decimals=4, suffix="K/min", siPrefix=True)
        self._stab_min_rate_spin.setValue(0.005)
        form.addRow("Max rate of change:", self._stab_min_rate_spin)

        self._stab_holdoff_spin = SISpinBox()
        self._stab_holdoff_spin.setOpts(bounds=(0.0, 120.0), suffix="s", siPrefix=True)
        self._stab_holdoff_spin.setValue(5.0)
        form.addRow("Unstable holdoff:", self._stab_holdoff_spin)

        apply_btn = QPushButton("Apply Stability Settings")
        apply_btn.clicked.connect(self._on_apply_stability)
        form.addRow("", apply_btn)

        return widget

    # --- Zone table tab ---

    def _build_zone_tab(self) -> QWidget:
        """Build the Zone Table tab widget.

        Returns:
            (QWidget):
                The assembled zone table tab.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(6)

        # Loop selector row (hidden when only one loop is present).
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Loop:"))
        self._zone_loop_combo = QComboBox()
        self._zone_loop_combo.currentIndexChanged.connect(self._on_zone_loop_changed)
        selector_row.addWidget(self._zone_loop_combo)
        selector_row.addStretch()
        self._zone_loop_selector_widget = QWidget()
        self._zone_loop_selector_widget.setLayout(selector_row)
        self._zone_loop_selector_widget.hide()
        layout.addWidget(self._zone_loop_selector_widget)

        # Zone table
        self._zone_table_widget = _ZoneTableWidget(self._engine)
        layout.addWidget(self._zone_table_widget)

        return widget

    # --- Input Settings tab ---

    def _build_input_settings_tab(self) -> QWidget:
        """Build the Input Settings tab widget.

        Returns:
            (QWidget):
                The assembled input settings tab.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(6)

        # Channel selector row
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Channel:"))
        self._input_channel_combo = QComboBox()
        self._input_channel_combo.currentIndexChanged.connect(self._on_input_channel_changed)
        selector_row.addWidget(self._input_channel_combo)
        selector_row.addStretch()
        layout.addLayout(selector_row)

        # Settings form
        self._input_settings_widget = _InputSettingsWidget(self._engine)
        layout.addWidget(self._input_settings_widget)
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
                heater_range=state.heater_ranges.get(loop),
                input_channel=state.input_channels.get(loop),
            )

        # Needle valve
        if state.needle_valve is not None:
            self._needle_spin.blockSignals(True)
            self._needle_spin.setValue(state.needle_valve)
            self._needle_spin.blockSignals(False)
        if state.gas_auto_mode is not None:
            self._gas_auto_check.blockSignals(True)
            self._gas_auto_check.setChecked(state.gas_auto_mode)
            self._gas_auto_check.blockSignals(False)
            self._needle_spin.setEnabled(not state.gas_auto_mode)
            self._needle_apply_btn.setEnabled(not state.gas_auto_mode)

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

    def _upsert_chart_curve(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, key: str, xs: list[float], ys: list[float], pen, plot_widget, name: str
    ) -> None:
        """Create or update a named curve on *plot_widget*.

        Args:
            key (str):
                Unique identifier for this curve, used to look it up in
                :attr:`_chart_curves`.
            xs (list[float]):
                X-axis data (relative time offsets in seconds).
            ys (list[float]):
                Y-axis data.
            pen:
                :func:`pyqtgraph.mkPen` pen used when creating a new curve.
            plot_widget:
                pyqtgraph ``PlotItem`` to which a new curve is added.
            name (str):
                Legend name used when creating a new curve.
        """
        if key not in self._chart_curves:
            self._chart_curves[key] = plot_widget.plot(xs, ys, pen=pen, name=name)
        else:
            self._chart_curves[key].setData(xs, ys)

    def _align_buf_to_xs(self, key: str, xs: list[float], fill_value: float) -> list[float]:
        """Return the value buffer for *key*, aligned to the length of *xs*.

        Missing leading values are filled with *fill_value*; excess leading
        values are trimmed.  The final element is always set to *fill_value*
        to record the current reading.

        Args:
            key (str):
                Buffer identifier in :attr:`_chart_values`.
            xs (list[float]):
                Reference X-axis sequence whose length determines the target
                buffer length.
            fill_value (float):
                Value used to pad or update the buffer.

        Returns:
            (list[float]):
                The aligned buffer (also stored in :attr:`_chart_values`).
        """
        buf = self._chart_values.setdefault(key, [])
        while len(buf) < len(xs):
            buf.insert(0, fill_value)
        while len(buf) > len(xs):
            buf.pop(0)
        buf[-1] = fill_value
        return buf

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
            self._upsert_chart_curve(
                f"T_{ch}", xs, buf_v, pg.mkPen(color=colour, width=2), self._temp_plot, f"T {ch}"
            )

        # Setpoint traces
        ts_ref = self._chart_times.get(next(iter(state.readings), ""), [])
        if ts_ref:
            xs = [t - now_ts for t in ts_ref]
            sp_pen = pg.mkPen(color=_SETPOINT_COLOUR, width=1, style=Qt.PenStyle.DashLine)
            for loop, sp in state.setpoints.items():
                sp_buf = self._align_buf_to_xs(f"SP_{loop}", xs, sp)
                self._upsert_chart_curve(f"SP_{loop}", xs, sp_buf, sp_pen, self._temp_plot, f"SP {loop}")

            # Heater output traces
            h_pen = pg.mkPen(color=_HEATER_COLOUR, width=2)
            for loop, ho in state.heater_outputs.items():
                h_buf = self._align_buf_to_xs(f"H_{loop}", xs, ho)
                self._upsert_chart_curve(
                    f"H_{loop}", xs, h_buf, h_pen, self._aux_plot, f"Heater {loop}"
                )

            # Needle valve
            if state.needle_valve is not None:
                nv_buf = self._align_buf_to_xs("NV", xs, state.needle_valve)
                nv_pen = pg.mkPen(color=_NEEDLE_COLOUR, width=2, style=Qt.PenStyle.DotLine)
                self._upsert_chart_curve("NV", xs, nv_buf, nv_pen, self._aux_plot, "Needle valve")

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
        self._set_address_widget_status(transport_index, VisaResourceStatus.CONNECTING)
        try:
            transport = self._build_transport(transport_index)
        except Exception:
            logger.exception("Failed to build transport")
            self._set_address_widget_status(transport_index, VisaResourceStatus.ERROR)
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
            self._set_address_widget_status(transport_index, VisaResourceStatus.ERROR)
            return

        self._engine.connect_instrument(driver)
        self._set_address_widget_status(transport_index, VisaResourceStatus.CONNECTED)

        # Populate control tab with loop groups.
        try:
            caps = driver.get_capabilities()
            self._capabilities = caps
            self._rebuild_loop_groups(caps)
            if caps.has_cryogen_control:
                self._needle_group.show()
            else:
                self._needle_group.hide()
            if caps.has_gas_auto_mode:
                self._gas_auto_row_label.show()
                self._gas_auto_check.show()
            else:
                self._gas_auto_row_label.hide()
                self._gas_auto_check.hide()
            self._configure_zone_tab(caps)
            self._configure_input_settings_tab(caps)
        except Exception:
            logger.exception("Failed to read capabilities after connection")

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
        if transport_index == 0:
            self._serial_port_combo.set_status(status)
        elif transport_index == 1:
            self._gpib_resource_combo.set_status(status)

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
        self._capabilities = None
        self._clear_loop_groups()
        self._needle_group.hide()
        self._gas_auto_row_label.hide()
        self._gas_auto_check.hide()
        # Disable zone table tab and clear its contents.
        self._tabs.setTabEnabled(self._zone_tab_index, False)
        self._zone_loop_combo.blockSignals(True)
        self._zone_loop_combo.clear()
        self._zone_loop_combo.blockSignals(False)
        self._zone_loop_selector_widget.hide()
        self._zone_table_widget.clear_table()
        # Disable input settings tab.
        self._tabs.setTabEnabled(self._input_settings_tab_index, False)
        self._input_channel_combo.blockSignals(True)
        self._input_channel_combo.clear()
        self._input_channel_combo.blockSignals(False)
        self._input_settings_widget.clear()
        # Reset address widget colours to disconnected state.
        self._serial_port_combo.set_status(VisaResourceStatus.DISCONNECTED)
        self._gpib_resource_combo.set_status(VisaResourceStatus.DISCONNECTED)

    # ------------------------------------------------------------------
    # Control tab slots
    # ------------------------------------------------------------------

    def _configure_zone_tab(self, caps: ControllerCapabilities) -> None:
        """Enable or disable the zone tab based on driver capabilities.

        Populates the loop selector with loops that support zone control and
        shows it only when there is more than one loop.

        Args:
            caps (ControllerCapabilities):
                The driver's capability descriptor.
        """
        enabled = caps.has_zone
        self._tabs.setTabEnabled(self._zone_tab_index, enabled)
        self._zone_loop_combo.blockSignals(True)
        self._zone_loop_combo.clear()
        if enabled:
            for lp in caps.loop_numbers:
                self._zone_loop_combo.addItem(f"Loop {lp}", lp)
            if len(caps.loop_numbers) > 1:
                self._zone_loop_selector_widget.show()
            else:
                self._zone_loop_selector_widget.hide()
            self._zone_table_widget.set_loop(caps.loop_numbers[0] if caps.loop_numbers else 1)
        else:
            self._zone_loop_selector_widget.hide()
            self._zone_table_widget.clear_table()
        self._zone_loop_combo.blockSignals(False)

    @pyqtSlot(int)
    def _on_zone_loop_changed(self, index: int) -> None:
        """Update the zone table widget when a different loop is selected.

        Args:
            index (int):
                Index of the newly selected loop in the loop combo box.
        """
        loop = self._zone_loop_combo.itemData(index)
        if loop is not None:
            self._zone_table_widget.set_loop(loop)

    def _configure_input_settings_tab(self, caps: ControllerCapabilities) -> None:
        """Enable or disable the Input Settings tab based on driver capabilities.

        Populates the channel selector with the available input channels and
        loads settings for the first channel.

        Args:
            caps (ControllerCapabilities):
                The driver's capability descriptor.
        """
        enabled = caps.has_input_settings
        self._tabs.setTabEnabled(self._input_settings_tab_index, enabled)
        self._input_channel_combo.blockSignals(True)
        self._input_channel_combo.clear()
        if enabled:
            for ch in caps.input_channels:
                self._input_channel_combo.addItem(ch, ch)
            self._input_settings_widget.set_channel(caps.input_channels[0] if caps.input_channels else "A")
        else:
            self._input_settings_widget.clear()
        self._input_channel_combo.blockSignals(False)

    @pyqtSlot(int)
    def _on_input_channel_changed(self, index: int) -> None:
        """Update the input settings widget when a different channel is selected.

        Args:
            index (int):
                Index of the newly selected channel in the channel combo box.
        """
        channel = self._input_channel_combo.itemData(index)
        if channel is not None:
            self._input_settings_widget.set_channel(channel)

    def _rebuild_loop_groups(self, caps) -> None:
        """Rebuild per-loop control groups from the driver capabilities.

        Args:
            caps (ControllerCapabilities):
                The driver's capability descriptor.
        """
        self._clear_loop_groups()
        stretch_item = self._control_layout.takeAt(self._control_layout.count() - 1)
        for lp in caps.loop_numbers:
            group = _LoopControlGroup(lp, self._engine, caps)
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

    @pyqtSlot()
    def _on_read_needle(self) -> None:
        """Read the current needle valve position from the instrument."""
        position = self._engine.get_needle_valve()
        if position is None:
            return
        self._needle_spin.blockSignals(True)
        self._needle_spin.setValue(position)
        self._needle_spin.blockSignals(False)

    @pyqtSlot(int)
    def _on_gas_auto_changed(self, state: int) -> None:
        """Send the gas auto mode toggle to the engine and update UI.

        Args:
            state (int):
                Qt check state integer (non-zero means checked).
        """
        auto = bool(state)
        self._engine.set_gas_auto(auto)
        # Disable manual position when in auto mode.
        self._needle_spin.setEnabled(not auto)
        self._needle_apply_btn.setEnabled(not auto)
        self._needle_read_btn.setEnabled(not auto)

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
# Zone table widget
# ---------------------------------------------------------------------------

#: Column indices for the zone table.
_COL_ZONE = 0
_COL_UPPER = 1
_COL_P = 2
_COL_I = 3
_COL_D = 4
_COL_RAMP = 5
_COL_RANGE = 6
_COL_OUTPUT = 7

_ZONE_COLUMNS = [
    "Zone",
    "Upper Bound (K)",
    "P",
    "I",
    "D",
    "Ramp Rate (K/min)",
    "Heater Range",
    "Heater Output (%)",
]


class _ZoneTableWidget(QWidget):
    """Self-contained widget for viewing and editing a zone PID table.

    Displays a :class:`~PyQt6.QtWidgets.QTableWidget` with one row per zone
    entry.  Provides buttons to read the table from and write it to the
    connected temperature controller via the engine, and to serialise/
    deserialise the table as JSON.

    Args:
        engine (TemperatureControllerEngine):
            Engine instance used to read and write zone data.
        parent (QWidget | None):
            Optional Qt parent widget.
    """

    def __init__(
        self, engine: TemperatureControllerEngine, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._loop: int = 1
        self._build()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_loop(self, loop: int) -> None:
        """Set the active control loop number.

        Args:
            loop (int):
                Control loop number (1-based) whose zone table will be
                read or written.
        """
        self._loop = loop

    def clear_table(self) -> None:
        """Remove all rows from the zone table."""
        self._table.setRowCount(0)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Assemble the layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Table
        self._table = QTableWidget(0, len(_ZONE_COLUMNS))
        self._table.setHorizontalHeaderLabels(_ZONE_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        for label, slot in (
            ("Read", self._on_read),
            ("Apply", self._on_apply),
            ("Add Row", self._on_add_row),
            ("Remove Row", self._on_remove_row),
            ("Load JSON", self._on_load_json),
            ("Save JSON", self._on_save_json),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------

    def _populate_table(self, entries: list[ZoneEntry]) -> None:
        """Replace all table rows with *entries*.

        Args:
            entries (list[ZoneEntry]):
                Zone-table entries to display.
        """
        self._table.setRowCount(0)
        for i, entry in enumerate(entries):
            self._append_row(i + 1, entry)

    def _append_row(self, zone_number: int, entry: ZoneEntry | None = None) -> None:
        """Append one editable row to the table.

        Args:
            zone_number (int):
                Display-only zone index shown in the first column.
            entry (ZoneEntry | None):
                Initial values; when ``None`` all numeric fields default to
                ``0.0`` / ``0``.
        """
        row = self._table.rowCount()
        self._table.insertRow(row)

        # Zone number — read-only label column.
        zone_item = QTableWidgetItem(str(zone_number))
        zone_item.setFlags(zone_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, _COL_ZONE, zone_item)

        def _dspin(value: float, max_val: float = 1000.0, decimals: int = 3) -> QDoubleSpinBox:
            w = QDoubleSpinBox()
            w.setRange(0.0, max_val)
            w.setDecimals(decimals)
            w.setValue(value)
            w.setFrame(False)
            return w

        def _ispin(value: int, max_val: int = 9) -> QSpinBox:
            w = QSpinBox()
            w.setRange(0, max_val)
            w.setValue(value)
            w.setFrame(False)
            return w

        ub = entry.upper_bound if entry else 0.0
        p = entry.p if entry else 0.0
        i = entry.i if entry else 0.0
        d = entry.d if entry else 0.0
        ramp = entry.ramp_rate if entry else 0.0
        hr = entry.heater_range if entry else 0
        ho = entry.heater_output if entry else 0.0

        self._table.setCellWidget(row, _COL_UPPER, _dspin(ub, max_val=9999.0))
        self._table.setCellWidget(row, _COL_P, _dspin(p))
        self._table.setCellWidget(row, _COL_I, _dspin(i))
        self._table.setCellWidget(row, _COL_D, _dspin(d))
        self._table.setCellWidget(row, _COL_RAMP, _dspin(ramp, max_val=999.0))
        self._table.setCellWidget(row, _COL_RANGE, _ispin(hr))
        self._table.setCellWidget(row, _COL_OUTPUT, _dspin(ho, max_val=100.0))

    def _collect_entries(self) -> list[ZoneEntry]:
        """Read all rows from the table and return a list of :class:`ZoneEntry`.

        Returns:
            (list[ZoneEntry]):
                Zone-table entries built from the current cell widget values.
        """
        entries = []
        for row in range(self._table.rowCount()):

            def _dval(col: int) -> float:
                w = self._table.cellWidget(row, col)
                return w.value() if w is not None else 0.0

            def _ival(col: int) -> int:
                w = self._table.cellWidget(row, col)
                return w.value() if w is not None else 0

            entries.append(
                ZoneEntry(
                    upper_bound=_dval(_COL_UPPER),
                    p=_dval(_COL_P),
                    i=_dval(_COL_I),
                    d=_dval(_COL_D),
                    ramp_rate=_dval(_COL_RAMP),
                    heater_range=_ival(_COL_RANGE),
                    heater_output=_dval(_COL_OUTPUT),
                )
            )
        return entries

    def _renumber_zones(self) -> None:
        """Refresh the read-only zone-number column after row additions/removals."""
        for row in range(self._table.rowCount()):
            item = self._table.item(row, _COL_ZONE)
            if item is not None:
                item.setText(str(row + 1))

    # ------------------------------------------------------------------
    # Button slots
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_read(self) -> None:
        """Read the zone table from the instrument via the engine."""
        entries = self._engine.get_zone_table(self._loop)
        if entries is None:
            QMessageBox.warning(self, "Zone Table", "No instrument connected.")
            return
        self._populate_table(entries)

    @pyqtSlot()
    def _on_apply(self) -> None:
        """Write the current table contents to the instrument via the engine."""
        entries = self._collect_entries()
        self._engine.set_zone_table(self._loop, entries)

    @pyqtSlot()
    def _on_add_row(self) -> None:
        """Append a blank row to the table."""
        self._append_row(self._table.rowCount() + 1)

    @pyqtSlot()
    def _on_remove_row(self) -> None:
        """Remove the currently selected row (or the last row if none selected)."""
        selected = self._table.selectedItems()
        if selected:
            row = self._table.row(selected[0])
        else:
            row = self._table.rowCount() - 1
        if row >= 0:
            self._table.removeRow(row)
            self._renumber_zones()

    @pyqtSlot()
    def _on_load_json(self) -> None:
        """Load zone-table entries from a JSON file chosen by the user."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Zone Table", "", "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            entries = [
                ZoneEntry(
                    upper_bound=float(item["upper_bound"]),
                    p=float(item["p"]),
                    i=float(item["i"]),
                    d=float(item["d"]),
                    ramp_rate=float(item["ramp_rate"]),
                    heater_range=int(item["heater_range"]),
                    heater_output=float(item["heater_output"]),
                )
                for item in data
            ]
        except Exception as exc:
            QMessageBox.critical(self, "Load Zone Table", f"Failed to load file:\n{exc}")
            return
        self._populate_table(entries)

    @pyqtSlot()
    def _on_save_json(self) -> None:
        """Save the current zone table to a JSON file chosen by the user."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Zone Table", "zone_table.json", "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        entries = self._collect_entries()
        data = [
            {
                "upper_bound": e.upper_bound,
                "p": e.p,
                "i": e.i,
                "d": e.d,
                "ramp_rate": e.ramp_rate,
                "heater_range": e.heater_range,
                "heater_output": e.heater_output,
            }
            for e in entries
        ]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Save Zone Table", f"Failed to save file:\n{exc}")


# ---------------------------------------------------------------------------
# Input settings widget
# ---------------------------------------------------------------------------

#: Human-readable sensor type labels for Lakeshore controllers.
_LAKESHORE_SENSOR_TYPES = [
    (0, "Disabled"),
    (1, "Diode"),
    (2, "PTC RTD"),
    (3, "NTC RTD"),
    (4, "Thermocouple"),
]

#: Human-readable temperature units labels.
_LAKESHORE_UNITS = [
    (1, "Kelvin"),
    (2, "Celsius"),
    (3, "Sensor"),
]


class _InputSettingsWidget(QWidget):
    """Self-contained widget for viewing and editing a single input channel's settings.

    Displays sensor type, range, filter, and calibration curve assignment.
    Provides Read and Apply buttons to synchronise with the connected
    instrument via the engine.

    Args:
        engine (TemperatureControllerEngine):
            Engine instance used to read and write settings.
        parent (QWidget | None):
            Optional Qt parent widget.
    """

    def __init__(
        self, engine: TemperatureControllerEngine, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._channel: str = "A"
        self._build()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_channel(self, channel: str) -> None:
        """Set the active sensor channel.

        Args:
            channel (str):
                Sensor channel identifier to display and edit.
        """
        self._channel = channel

    def clear(self) -> None:
        """Reset all fields to their default/blank state."""
        self._sensor_type_combo.setCurrentIndex(0)
        self._autorange_check.setChecked(False)
        self._range_spin.setValue(0)
        self._compensation_check.setChecked(False)
        self._units_combo.setCurrentIndex(0)
        self._filter_enable_check.setChecked(False)
        self._filter_points_spin.setValue(1)
        self._filter_window_spin.setValue(0.0)
        self._curve_spin.setValue(0)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Assemble the form layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Sensor type
        self._sensor_type_combo = QComboBox()
        for code, label in _LAKESHORE_SENSOR_TYPES:
            self._sensor_type_combo.addItem(label, code)
        form.addRow("Sensor type:", self._sensor_type_combo)

        # Autorange
        self._autorange_check = QCheckBox("Enabled")
        form.addRow("Autorange:", self._autorange_check)

        # Manual range
        self._range_spin = QSpinBox()
        self._range_spin.setRange(0, 15)
        self._range_spin.setToolTip("Manual range index (instrument-specific)")
        form.addRow("Range:", self._range_spin)

        # Compensation
        self._compensation_check = QCheckBox("Enabled")
        self._compensation_check.setToolTip("Current reversal compensation (diode/RTD inputs)")
        form.addRow("Compensation:", self._compensation_check)

        # Units
        self._units_combo = QComboBox()
        for code, label in _LAKESHORE_UNITS:
            self._units_combo.addItem(label, code)
        form.addRow("Units:", self._units_combo)

        # Filter separator
        filter_group = QGroupBox("Digital Filter")
        filter_form = QFormLayout(filter_group)

        self._filter_enable_check = QCheckBox("Enabled")
        filter_form.addRow("Filter:", self._filter_enable_check)

        self._filter_points_spin = QSpinBox()
        self._filter_points_spin.setRange(1, 200)
        self._filter_points_spin.setToolTip("Number of readings averaged (1 = no averaging)")
        filter_form.addRow("Points:", self._filter_points_spin)

        self._filter_window_spin = QDoubleSpinBox()
        self._filter_window_spin.setRange(0.0, 10.0)
        self._filter_window_spin.setDecimals(1)
        self._filter_window_spin.setSuffix(" %")
        self._filter_window_spin.setToolTip("Deviation window that resets the filter (0 = no windowing)")
        filter_form.addRow("Window:", self._filter_window_spin)

        # Curve number
        self._curve_spin = QSpinBox()
        self._curve_spin.setRange(0, 60)
        self._curve_spin.setToolTip("Calibration curve number (0 = none)")
        form.addRow("Calibration curve:", self._curve_spin)

        layout.addLayout(form)
        layout.addWidget(filter_group)

        # Button row
        btn_row = QHBoxLayout()
        read_btn = QPushButton("Read")
        read_btn.setToolTip("Read input channel settings from the instrument")
        read_btn.clicked.connect(self._on_read)
        apply_btn = QPushButton("Apply")
        apply_btn.setToolTip("Write input channel settings to the instrument")
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(read_btn)
        btn_row.addWidget(apply_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Button slots
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_read(self) -> None:
        """Read input channel settings from the instrument via the engine."""
        settings = self._engine.get_input_channel_settings(self._channel)
        if settings is None:
            QMessageBox.warning(self, "Input Settings", "No instrument connected or read failed.")
            return
        self._populate_from_settings(settings)

    @pyqtSlot()
    def _on_apply(self) -> None:
        """Write current input channel settings to the instrument via the engine."""
        settings = self._collect_settings()
        self._engine.set_input_channel_settings(self._channel, settings)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _populate_from_settings(self, settings: InputChannelSettings) -> None:
        """Update form widgets from *settings*.

        Args:
            settings (InputChannelSettings):
                Settings read from the instrument.
        """
        if settings.sensor_type is not None:
            idx = self._sensor_type_combo.findData(settings.sensor_type)
            if idx >= 0:
                self._sensor_type_combo.setCurrentIndex(idx)
        if settings.autorange is not None:
            self._autorange_check.setChecked(settings.autorange)
        if settings.range_ is not None:
            self._range_spin.setValue(settings.range_)
        if settings.compensation is not None:
            self._compensation_check.setChecked(settings.compensation)
        if settings.units is not None:
            idx = self._units_combo.findData(settings.units)
            if idx >= 0:
                self._units_combo.setCurrentIndex(idx)
        if settings.filter_enabled is not None:
            self._filter_enable_check.setChecked(settings.filter_enabled)
        if settings.filter_points is not None:
            self._filter_points_spin.setValue(settings.filter_points)
        if settings.filter_window is not None:
            self._filter_window_spin.setValue(settings.filter_window)
        if settings.curve_number is not None:
            self._curve_spin.setValue(settings.curve_number)

    def _collect_settings(self) -> InputChannelSettings:
        """Build an :class:`InputChannelSettings` from the current form values.

        Returns:
            (InputChannelSettings):
                Settings ready to be sent to the instrument.
        """
        return InputChannelSettings(
            sensor_type=self._sensor_type_combo.currentData(),
            autorange=self._autorange_check.isChecked(),
            range_=self._range_spin.value(),
            compensation=self._compensation_check.isChecked(),
            units=self._units_combo.currentData(),
            filter_enabled=self._filter_enable_check.isChecked(),
            filter_points=self._filter_points_spin.value(),
            filter_window=self._filter_window_spin.value(),
            curve_number=self._curve_spin.value(),
        )


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
        caps (ControllerCapabilities):
            Capability descriptor of the connected driver, used to populate
            the heater range combo and the input-channel selector.
    """

    def __init__(self, loop: int, engine: TemperatureControllerEngine, caps: ControllerCapabilities) -> None:
        super().__init__(f"Loop {loop}")
        self._loop = loop
        self._engine = engine
        self._caps = caps
        self._build()

    def _build(self) -> None:
        """Build the form layout."""
        form = QFormLayout(self)
        self._build_readback_rows(form)
        self._build_control_rows(form)
        self._build_pid_row(form)
        self._build_button_row(form)
        # Apply initial visibility based on the default mode selection.
        self._update_mode_visibility(self._mode_combo.currentData())

    def _build_readback_rows(self, form: QFormLayout) -> None:
        """Add live-readback label rows to *form*."""
        self._setpoint_label = QLabel("—")
        self._heater_label = QLabel("—")
        self._mode_label = QLabel("—")
        form.addRow("Setpoint (live):", self._setpoint_label)
        form.addRow("Heater output:", self._heater_label)
        form.addRow("Mode (live):", self._mode_label)

        self._channel_combo = QComboBox()
        for ch in self._caps.input_channels:
            self._channel_combo.addItem(ch, ch)
        form.addRow("Control sensor:", self._channel_combo)

    def _build_control_rows(self, form: QFormLayout) -> None:
        """Add setpoint, mode, ramp, heater-range and manual-output rows to *form*."""
        self._sp_spin = SISpinBox()
        self._sp_spin.setOpts(bounds=(0.0, 1000.0), decimals=3, suffix="K", siPrefix=True)
        self._sp_row_label = QLabel("New setpoint:")
        form.addRow(self._sp_row_label, self._sp_spin)

        self._mode_combo = QComboBox()
        for mode in ControlMode:
            self._mode_combo.addItem(mode.value.replace("_", " ").title(), mode)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        form.addRow("Control mode:", self._mode_combo)

        self._ramp_enable = QCheckBox("Enable")
        self._ramp_rate_spin = SISpinBox()
        self._ramp_rate_spin.setOpts(bounds=(0.0, 100.0), decimals=3, suffix="K/min", siPrefix=True)
        ramp_row = QHBoxLayout()
        ramp_row.addWidget(self._ramp_enable)
        ramp_row.addWidget(self._ramp_rate_spin)
        self._ramp_widget = QWidget()
        self._ramp_widget.setLayout(ramp_row)
        self._ramp_row_label = QLabel("Ramp:")
        form.addRow(self._ramp_row_label, self._ramp_widget)

        self._heater_range_label = QLabel("Heater range:")
        range_labels = self._caps.heater_range_labels.get(self._loop, ())
        if range_labels:
            self._heater_range_combo = QComboBox()
            for idx, label in enumerate(range_labels):
                self._heater_range_combo.addItem(label, idx)
            self._heater_range_spin = None
            form.addRow(self._heater_range_label, self._heater_range_combo)
        else:
            self._heater_range_spin = QSpinBox()
            self._heater_range_spin.setRange(0, 5)
            self._heater_range_spin.setToolTip("Heater range index (0 = off; instrument-specific)")
            self._heater_range_combo = None
            form.addRow(self._heater_range_label, self._heater_range_spin)

        self._manual_output_spin = PercentSliderWidget()
        self._manual_output_spin.setToolTip(
            "Manual heater output percentage for open-loop control"
        )
        self._manual_output_label = QLabel("Manual output:")
        form.addRow(self._manual_output_label, self._manual_output_spin)

    def _build_pid_row(self, form: QFormLayout) -> None:
        """Add PID spin boxes row to *form*."""
        self._pid_p_spin = SISpinBox()
        self._pid_p_spin.setOpts(bounds=(0.0, 1000.0), decimals=3)
        self._pid_i_spin = SISpinBox()
        self._pid_i_spin.setOpts(bounds=(0.0, 1000.0), decimals=3)
        self._pid_d_spin = SISpinBox()
        self._pid_d_spin.setOpts(bounds=(0.0, 1000.0), decimals=3)
        pid_row = QHBoxLayout()
        pid_row.addWidget(QLabel("P:"))
        pid_row.addWidget(self._pid_p_spin)
        pid_row.addWidget(QLabel("I:"))
        pid_row.addWidget(self._pid_i_spin)
        pid_row.addWidget(QLabel("D:"))
        pid_row.addWidget(self._pid_d_spin)
        self._pid_widget = QWidget()
        self._pid_widget.setLayout(pid_row)
        self._pid_row_label = QLabel("PID:")
        form.addRow(self._pid_row_label, self._pid_widget)

    def _build_button_row(self, form: QFormLayout) -> None:
        """Add Apply/Read button row to *form*."""
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        apply_btn.setToolTip("Send all loop settings to the instrument")
        apply_btn.clicked.connect(self._on_apply_all)
        read_btn = QPushButton("Read")
        read_btn.setToolTip("Read all loop settings from the instrument and update this panel")
        read_btn.clicked.connect(self._on_read)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(read_btn)
        btn_row.addStretch()
        form.addRow("", btn_row)

    # --- Mode visibility ---

    @pyqtSlot(int)
    def _on_mode_changed(self, _index: int) -> None:
        """Update widget visibility when the user selects a different control mode.

        Args:
            _index (int):
                Index of the newly selected item in the mode combo box (unused;
                the mode is read back via :meth:`~PyQt6.QtWidgets.QComboBox.currentData`).
        """
        self._update_mode_visibility(self._mode_combo.currentData())

    def _update_mode_visibility(self, mode: ControlMode | None) -> None:
        """Show or hide control widgets based on *mode*.

        The rules applied are:

        * **Off / Monitor**: heater range, setpoint, ramp, and PID are hidden
          because the loop is inactive or only observing.
        * **Open Loop**: setpoint and ramp are hidden (there is no PID feedback);
          the manual-output spin box becomes visible so the operator can drive a
          fixed heater output.  PID is hidden.
        * **Zone**: setpoint, ramp, and heater range remain visible; the PID
          spin boxes are shown but made read-only because PID gains are
          determined by the zone table rather than the operator.
        * **Closed Loop**: all control widgets are visible and editable.

        Args:
            mode (ControlMode | None):
                The mode to apply.  ``None`` is treated identically to
                :attr:`~ControlMode.OFF`.
        """
        off_like = mode in (ControlMode.OFF, ControlMode.MONITOR, None)
        open_loop = mode == ControlMode.OPEN_LOOP
        zone = mode == ControlMode.ZONE

        sp_visible = not off_like and not open_loop
        self._sp_row_label.setVisible(sp_visible)
        self._sp_spin.setVisible(sp_visible)

        ramp_visible = not off_like and not open_loop
        self._ramp_row_label.setVisible(ramp_visible)
        self._ramp_widget.setVisible(ramp_visible)

        heater_range_visible = not off_like
        self._heater_range_label.setVisible(heater_range_visible)
        heater_range_widget = (
            self._heater_range_combo
            if self._heater_range_combo is not None
            else self._heater_range_spin
        )
        if heater_range_widget is not None:
            heater_range_widget.setVisible(heater_range_visible)

        pid_visible = not off_like and not open_loop
        self._pid_row_label.setVisible(pid_visible)
        self._pid_widget.setVisible(pid_visible)
        pid_editable = pid_visible and not zone
        self._pid_p_spin.setEnabled(pid_editable)
        self._pid_i_spin.setEnabled(pid_editable)
        self._pid_d_spin.setEnabled(pid_editable)

        self._manual_output_label.setVisible(open_loop)
        self._manual_output_spin.setVisible(open_loop)

    # --- Live update ---

    def update_live(
        self,
        setpoint: float,
        heater_output: float,
        mode,
        *,
        heater_range: int | None = None,
        input_channel: str | None = None,
    ) -> None:
        """Refresh live-readback labels from the engine polling state.

        Only the read-only status labels are updated here; editable control
        widgets (mode combo, heater range, input channel, PID, ramp) are
        intentionally not overwritten during live polling to avoid disrupting
        values the user may be in the process of editing.  Use the **Read**
        button to populate the editable fields with the current hardware state.

        Args:
            setpoint (float):
                Current setpoint in Kelvin.
            heater_output (float):
                Current heater output percentage.
            mode (ControlMode | None):
                Current control mode.

        Keyword Parameters:
            heater_range (int | None):
                Current heater range index — provided for potential future use
                but not reflected in the editable range widget during live
                polling.
            input_channel (str | None):
                Current input channel — provided for potential future use but
                not reflected in the editable channel widget during live
                polling.
        """
        self._setpoint_label.setText(f"{setpoint:.3f} K")
        self._heater_label.setText(f"{heater_output:.1f} %")
        mode_text = mode.value.replace("_", " ").title() if mode is not None else "—"
        self._mode_label.setText(mode_text)

    # --- Apply / Read slots ---

    @pyqtSlot()
    def _on_apply_all(self) -> None:
        """Send all loop settings to the engine in a single call."""
        mode = self._mode_combo.currentData()
        channel = self._channel_combo.currentData()
        heater_range = (
            self._heater_range_combo.currentData()
            if self._heater_range_combo is not None
            else self._heater_range_spin.value()
        )
        self._engine.set_all_loop_settings(
            self._loop,
            setpoint=self._sp_spin.value(),
            mode=mode,
            input_channel=channel,
            ramp_enabled=self._ramp_enable.isChecked(),
            ramp_rate=self._ramp_rate_spin.value(),
            pid_p=self._pid_p_spin.value(),
            pid_i=self._pid_i_spin.value(),
            pid_d=self._pid_d_spin.value(),
            heater_range=heater_range,
        )
        if mode == ControlMode.OPEN_LOOP:
            # The spin box range constraint (0–100 %) guarantees a valid value.
            self._engine.set_manual_heater_output(self._loop, self._manual_output_spin.value())

    @pyqtSlot()
    def _on_read(self) -> None:
        """Query the hardware for all loop settings and update the UI."""
        settings = self._engine.get_loop_settings(self._loop)
        if settings is None:
            return
        # Setpoint
        self._sp_spin.blockSignals(True)
        self._sp_spin.setValue(settings.setpoint)
        self._sp_spin.blockSignals(False)
        # Control mode — update visibility before re-enabling signals so that
        # the visibility slot fires once with the final mode value.
        self._mode_combo.blockSignals(True)
        idx = self._mode_combo.findData(settings.mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        self._mode_combo.blockSignals(False)
        self._update_mode_visibility(settings.mode)
        # Input channel
        ch_idx = self._channel_combo.findData(settings.input_channel)
        if ch_idx >= 0:
            self._channel_combo.setCurrentIndex(ch_idx)
        # Ramp
        self._ramp_enable.setChecked(settings.ramp_enabled)
        self._ramp_rate_spin.blockSignals(True)
        self._ramp_rate_spin.setValue(settings.ramp_rate)
        self._ramp_rate_spin.blockSignals(False)
        # PID
        self._pid_p_spin.blockSignals(True)
        self._pid_i_spin.blockSignals(True)
        self._pid_d_spin.blockSignals(True)
        self._pid_p_spin.setValue(settings.pid_p)
        self._pid_i_spin.setValue(settings.pid_i)
        self._pid_d_spin.setValue(settings.pid_d)
        self._pid_p_spin.blockSignals(False)
        self._pid_i_spin.blockSignals(False)
        self._pid_d_spin.blockSignals(False)
        # Heater range
        if settings.heater_range is not None:
            if self._heater_range_combo is not None:
                r_idx = self._heater_range_combo.findData(settings.heater_range)
                if r_idx >= 0:
                    self._heater_range_combo.setCurrentIndex(r_idx)
            elif self._heater_range_spin is not None:
                self._heater_range_spin.setValue(settings.heater_range)
        # Manual heater output (only meaningful in OPEN_LOOP mode)
        if settings.manual_output is not None:
            self._manual_output_spin.blockSignals(True)
            self._manual_output_spin.setValue(settings.manual_output)
            self._manual_output_spin.blockSignals(False)


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
