"""Non-modal control panel for the legacy X-ray diffractometer."""

from __future__ import annotations

import math

from qtpy.QtCore import QPointF, QRectF, Qt
from qtpy.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.qt_compat import pyqtSlot
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.theme import colour, value_display_frame_stylesheet
from stoner_measurement.ui.value_watch import seven_segment_font_family
from stoner_measurement.ui.widgets import StatusLineEdit, VisaResourceStatus
from stoner_measurement.xray_control import (
    XrayControllerEngine,
    XrayEngineState,
    XrayEngineStatus,
    XrayMotionMode,
)


class XrayGeometryWidget(QWidget):
    """Live vector synoptic of source, sample, detector and diffraction rays."""

    _SAMPLE_HALF_LENGTH = 21.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theta_deg = 0.0
        self._two_theta_deg = 0.0
        self._offset_deg = 0.0
        self.setMinimumSize(360, 300)
        self._build_count_rate_display()

    def _build_count_rate_display(self) -> None:
        """Build a compact value-watch-style count-rate readout."""
        self._count_rate_frame = QFrame(self)
        self._count_rate_frame.setObjectName("synoptic_count_rate")
        self._count_rate_frame.setStyleSheet(
            value_display_frame_stylesheet() + "QLabel { background: transparent; }"
        )
        self._count_rate_frame.setFixedSize(190, 82)

        label = QLabel("Count rate", self._count_rate_frame)
        label_font = QFont(self.font())
        label_font.setBold(True)
        label.setFont(label_font)

        self._count_rate_value = QLabel("—", self._count_rate_frame)
        value_font = QFont(seven_segment_font_family() or "Courier New")
        if not seven_segment_font_family():
            value_font.setStyleHint(QFont.StyleHint.TypeWriter)
        value_font.setPointSize(24)
        value_font.setBold(True)
        self._count_rate_value.setFont(value_font)
        self._count_rate_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        suffix = QLabel("count/s", self._count_rate_frame)
        suffix_font = QFont(self.font())
        suffix_font.setBold(True)
        suffix.setFont(suffix_font)
        suffix.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        readout_colour = colour("value_display_text")
        self._count_rate_value.setStyleSheet(f"color: {readout_colour};")
        suffix.setStyleSheet(f"color: {readout_colour};")

        layout = QGridLayout(self._count_rate_frame)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setHorizontalSpacing(4)
        layout.addWidget(label, 0, 0, 1, 2)
        layout.addWidget(self._count_rate_value, 1, 0)
        layout.addWidget(suffix, 1, 1)
        self._position_count_rate_display()

    def set_count_rate(self, count_rate_hz: float | None) -> None:
        """Show the most recently acquired count rate."""
        text = "—" if count_rate_hz is None else f"{count_rate_hz:.4g}"
        self._count_rate_value.setText(text)
        self._position_count_rate_display()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Keep the live readout anchored in the top-right corner."""
        super().resizeEvent(event)
        self._position_count_rate_display()

    def _position_count_rate_display(self) -> None:
        self._count_rate_frame.move(max(8, self.width() - self._count_rate_frame.width() - 8), 8)
        self._count_rate_frame.raise_()

    def set_geometry(self, theta_deg: float, two_theta_deg: float, offset_deg: float) -> None:
        """Update the measured geometry and schedule a repaint."""
        self._theta_deg = float(theta_deg)
        self._two_theta_deg = float(two_theta_deg)
        self._offset_deg = float(offset_deg)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._synoptic_font())
        painter.fillRect(self.rect(), QColor(colour("base")))

        width = float(self.width())
        height = float(self.height())
        centre = QPointF(width * 0.51, height * 0.49)
        radius = min(width, height) * 0.34
        source = QPointF(centre.x() - radius, centre.y())
        detector = self._detector_position(centre, radius)

        border_pen = QPen(QColor(colour("border")), 2.0)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(centre, radius, radius)

        zero_beam_pen = QPen(QColor(colour("muted_text")), 1.5, Qt.PenStyle.DashLine)
        painter.setPen(zero_beam_pen)
        painter.drawLine(centre, QPointF(centre.x() + radius, centre.y()))

        ray_pen = QPen(QColor("#d94747"), 2.5)
        painter.setPen(ray_pen)
        painter.drawLine(source, centre)
        painter.drawLine(centre, detector)

        # Draw the sample below the annotations so arcs and live values remain
        # legible even for small angles.
        painter.save()
        painter.translate(centre)
        painter.rotate(self._theta_deg)
        painter.setPen(QPen(QColor(colour("text")), 4.0))
        painter.drawLine(
            QPointF(-self._SAMPLE_HALF_LENGTH, 0.0),
            QPointF(self._SAMPLE_HALF_LENGTH, 0.0),
        )
        painter.restore()

        self._draw_angle_annotation(
            painter,
            centre,
            radius * 0.28,
            self._theta_deg,
            f"ω / θ = {self._theta_deg:.3f}°",
            QColor(colour("trace_teal")),
        )
        self._draw_angle_annotation(
            painter,
            centre,
            radius * 0.70,
            self._two_theta_deg,
            f"2θ = {self._two_theta_deg:.3f}°",
            QColor(colour("trace_blue")),
        )

        self._draw_instrument(painter, source, 0.0, "X-ray tube")
        detector_rotation = self._two_theta_deg
        self._draw_instrument(painter, detector, detector_rotation, "Detector")

        painter.setPen(QPen(QColor(colour("text")), 1.0))
        painter.drawText(
            QRectF(8.0, height - 32.0, width - 16.0, 24.0),
            int(Qt.AlignmentFlag.AlignCenter),
            f"Coupled datum: 2theta = 2 theta {self._offset_deg:+.3f} deg",
        )
        painter.drawText(
            QRectF(centre.x() - 45.0, centre.y() + 12.0, 90.0, 22.0),
            int(Qt.AlignmentFlag.AlignCenter),
            "Sample",
        )

    @staticmethod
    def _draw_angle_annotation(
        painter: QPainter,
        centre: QPointF,
        radius: float,
        angle_deg: float,
        label: str,
        annotation_colour: QColor,
    ) -> None:
        """Draw a clockwise angular arc and a horizontal live-value label."""
        segments = max(2, math.ceil(abs(angle_deg) / 2.0))
        points = []
        for index in range(segments + 1):
            angle = math.radians(angle_deg * index / segments)
            points.append(
                QPointF(
                    centre.x() + radius * math.cos(angle),
                    centre.y() + radius * math.sin(angle),
                )
            )
        painter.setPen(QPen(annotation_colour, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points))

        midpoint = math.radians(angle_deg / 2.0)
        label_radius = radius + 19.0
        label_centre = QPointF(
            centre.x() + label_radius * math.cos(midpoint),
            centre.y() + label_radius * math.sin(midpoint),
        )
        painter.drawText(
            QRectF(label_centre.x() - 82.0, label_centre.y() - 12.0, 164.0, 24.0),
            int(Qt.AlignmentFlag.AlignCenter),
            label,
        )

    def _detector_position(self, centre: QPointF, radius: float) -> QPointF:
        """Return the clockwise detector-arm endpoint in widget coordinates."""
        detector_angle = math.radians(self._two_theta_deg)
        return QPointF(
            centre.x() + radius * math.cos(detector_angle),
            centre.y() + radius * math.sin(detector_angle),
        )

    def _synoptic_font(self) -> QFont:
        """Return the inherited application font enlarged by two points."""
        font = QFont(self.font())
        point_size = font.pointSizeF()
        if point_size > 0.0:
            font.setPointSizeF(point_size + 2.0)
        else:
            font.setPixelSize(max(1, font.pixelSize() + 3))
        return font

    @staticmethod
    def _draw_instrument(
        painter: QPainter, position: QPointF, rotation_deg: float, label: str
    ) -> None:
        painter.save()
        painter.translate(position)
        painter.rotate(rotation_deg)
        painter.setPen(QPen(QColor(colour("border")), 2.0))
        painter.setBrush(QBrush(QColor(colour("alternate_base"))))
        painter.drawRect(QRectF(-20.0, -12.0, 40.0, 24.0))
        painter.restore()
        painter.setPen(QPen(QColor(colour("text")), 1.0))
        painter.drawText(
            QRectF(position.x() - 60.0, position.y() + 17.0, 120.0, 24.0),
            int(Qt.AlignmentFlag.AlignCenter),
            label,
        )


class XrayControlPanel(QWidget):
    """Connect, move and count with the X-ray diffractometer engine."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engine = XrayControllerEngine.instance()
        self._wharfdale_address = "index:0"
        self._settings_unlocked = False
        self._allow_exit_close = False
        self.setWindowTitle("X-ray Diffractometer Control")
        self.resize(920, 680)
        self._build_ui()
        self._connect_signals()
        self._load_preferences()
        self._on_state_updated(self._engine.get_engine_state())
        self._on_engine_status_changed(self._engine.status)

    def show_and_raise(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._allow_exit_close:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._tabs = FontAwareTabWidget(self)
        self._tabs.addTab(self._build_connection_tab(), "Connection")
        self._tabs.addTab(self._build_control_tab(), "Control")
        self._tabs.addTab(self._build_instrument_settings_tab(), "Instrument settings")
        layout.addWidget(self._tabs)

        status_row = QHBoxLayout()
        self._status_label = QLabel("Disconnected", self)
        self._error_label = QLabel("", self)
        self._error_label.setStyleSheet(f"color: {colour('status_error')};")
        status_row.addWidget(self._status_label)
        status_row.addStretch(1)
        status_row.addWidget(self._error_label)
        layout.addLayout(status_row)

        hide_row = QHBoxLayout()
        hide_row.addStretch(1)
        self._hide_button = QPushButton("Hide", self)
        self._hide_button.clicked.connect(self.hide)
        hide_row.addWidget(self._hide_button)
        layout.addLayout(hide_row)

    def _build_connection_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self._instrument_combo = QComboBox(page)
        self._instrument_combo.addItems(["Wharfedale", "Simulated"])
        # Compatibility for scripts written against the first panel prototype.
        self._transport_combo = self._instrument_combo
        self._address_edit = StatusLineEdit(page)
        self._address_edit.setPlaceholderText("index:0 / serial:FT123456")
        self._polling_rate_spin = QDoubleSpinBox(page)
        self._polling_rate_spin.setRange(0.0, 10.0)
        self._polling_rate_spin.setDecimals(1)
        self._polling_rate_spin.setSingleStep(0.1)
        self._polling_rate_spin.setSuffix(" Hz")
        self._polling_rate_spin.setSpecialValueText("Disabled")
        self._polling_rate_spin.setValue(self._engine.polling_rate_hz)
        self._polling_rate_spin.setToolTip("Set to 0 to disable automatic polling.")
        form.addRow("Instrument", self._instrument_combo)
        form.addRow("Device", self._address_edit)
        form.addRow("Polling rate", self._polling_rate_spin)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self._connect_button = QPushButton("Connect", page)
        self._disconnect_button = QPushButton("Disconnect", page)
        self._save_button = QPushButton("Save configuration", page)
        buttons.addWidget(self._connect_button)
        buttons.addWidget(self._disconnect_button)
        buttons.addWidget(self._save_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        warning = QLabel(
            "Motion remains disabled until the recovered travel limits, backlash and "
            "physical directions have been confirmed on this installation.",
            page,
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        layout.addStretch(1)
        return page

    def _build_control_tab(self) -> QWidget:
        page = QWidget(self)
        outer = QHBoxLayout(page)
        left = QVBoxLayout()

        readings = QGroupBox("Live snapshot", page)
        reading_grid = QGridLayout(readings)
        self._theta_label = QLabel("-- deg", readings)
        self._two_theta_label = QLabel("-- deg", readings)
        self._counts_label = QLabel("--", readings)
        self._rate_label = QLabel("-- count/s", readings)
        reading_grid.addWidget(QLabel("Theta", readings), 0, 0)
        reading_grid.addWidget(self._theta_label, 0, 1)
        reading_grid.addWidget(QLabel("2-theta", readings), 1, 0)
        reading_grid.addWidget(self._two_theta_label, 1, 1)
        reading_grid.addWidget(QLabel("Detector counts", readings), 2, 0)
        reading_grid.addWidget(self._counts_label, 2, 1)
        reading_grid.addWidget(QLabel("Count rate", readings), 3, 0)
        reading_grid.addWidget(self._rate_label, 3, 1)
        self._read_button = QPushButton("Read snapshot", readings)
        reading_grid.addWidget(self._read_button, 4, 0, 1, 2)
        left.addWidget(readings)

        motion = QGroupBox("Motion", page)
        motion_form = QFormLayout(motion)
        self._motion_enabled = QCheckBox("Confirmed safe for motion", motion)
        self._mode_combo = QComboBox(motion)
        for mode, label in (
            (XrayMotionMode.THETA, "Theta only"),
            (XrayMotionMode.COUPLED, "Theta / 2-theta coupled"),
            (XrayMotionMode.TWO_THETA, "2-theta only"),
        ):
            self._mode_combo.addItem(label, mode)
        self._target_spin = _angle_spin(motion, -180.0, 180.0)
        self._speed_spin = _angle_spin(motion, 0.01, 30.0)
        self._speed_spin.setValue(1.0)
        self._offset_spin = _angle_spin(motion, -180.0, 180.0)
        motion_form.addRow(self._motion_enabled)
        motion_form.addRow("Motion set", self._mode_combo)
        motion_form.addRow("Target / deg", self._target_spin)
        motion_form.addRow("Theta speed / deg min-1", self._speed_spin)
        motion_form.addRow("2-theta datum offset / deg", self._offset_spin)
        motion_buttons = QHBoxLayout()
        self._move_button = QPushButton("Move", motion)
        self._cancel_button = QPushButton("Cancel", motion)
        motion_buttons.addWidget(self._move_button)
        motion_buttons.addWidget(self._cancel_button)
        motion_form.addRow(motion_buttons)
        left.addWidget(motion)

        detector = QGroupBox("Detector", page)
        detector_form = QFormLayout(detector)
        self._duration_spin = QDoubleSpinBox(detector)
        self._duration_spin.setRange(0.01, 86_400.0)
        self._duration_spin.setDecimals(3)
        self._duration_spin.setValue(1.0)
        self._count_button = QPushButton("Acquire counts", detector)
        detector_form.addRow("Count time / s", self._duration_spin)
        detector_form.addRow(self._count_button)
        left.addWidget(detector)

        maintenance = QGroupBox("Controller operations", page)
        maintenance_layout = QGridLayout(maintenance)
        self._zero_theta_button = QPushButton("Zero theta", maintenance)
        self._zero_two_button = QPushButton("Zero 2-theta", maintenance)
        self._reset_limit_button = QPushButton("Reset limit latch", maintenance)
        self._disable_button = QPushButton("Disable motors", maintenance)
        maintenance_layout.addWidget(self._zero_theta_button, 0, 0)
        maintenance_layout.addWidget(self._zero_two_button, 0, 1)
        maintenance_layout.addWidget(self._reset_limit_button, 1, 0)
        maintenance_layout.addWidget(self._disable_button, 1, 1)
        left.addWidget(maintenance)
        left.addStretch(1)

        self._geometry = XrayGeometryWidget(page)
        right = QVBoxLayout()
        right.addWidget(self._geometry, 1)
        right.addWidget(self._build_motion_status_bar())
        outer.addLayout(left, 2)
        outer.addLayout(right, 3)
        return page

    def _build_instrument_settings_tab(self) -> QWidget:
        """Build the operator-locked hardware mechanics page."""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        warning = QLabel(
            "These values protect the instrument from unsafe motion. Only an "
            "experienced operator should unlock and change them.",
            page,
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self._settings_lock_button = QPushButton("Unlock settings", page)
        layout.addWidget(self._settings_lock_button)

        self._settings_controls = QWidget(page)
        controls_layout = QVBoxLayout(self._settings_controls)
        theta_group = QGroupBox("Theta axis", self._settings_controls)
        theta_form = QFormLayout(theta_group)
        self._theta_steps_spin = _integer_spin(theta_group, 1, 1_000_000)
        self._theta_min_spin = _angle_spin(theta_group, -360.0, 360.0)
        self._theta_max_spin = _angle_spin(theta_group, -360.0, 360.0)
        self._theta_backlash_spin = _integer_spin(theta_group, 0, 1_000_000)
        theta_form.addRow("Steps per degree", self._theta_steps_spin)
        theta_form.addRow("Minimum / deg", self._theta_min_spin)
        theta_form.addRow("Maximum / deg", self._theta_max_spin)
        theta_form.addRow("Backlash / steps", self._theta_backlash_spin)
        controls_layout.addWidget(theta_group)

        two_theta_group = QGroupBox("2-theta axis", self._settings_controls)
        two_theta_form = QFormLayout(two_theta_group)
        self._two_theta_steps_spin = _integer_spin(two_theta_group, 1, 1_000_000)
        self._two_theta_min_spin = _angle_spin(two_theta_group, -360.0, 360.0)
        self._two_theta_max_spin = _angle_spin(two_theta_group, -360.0, 360.0)
        self._two_theta_backlash_spin = _integer_spin(
            two_theta_group, 0, 1_000_000
        )
        two_theta_form.addRow("Steps per degree", self._two_theta_steps_spin)
        two_theta_form.addRow("Minimum / deg", self._two_theta_min_spin)
        two_theta_form.addRow("Maximum / deg", self._two_theta_max_spin)
        two_theta_form.addRow("Backlash / steps", self._two_theta_backlash_spin)
        controls_layout.addWidget(two_theta_group)

        operating_group = QGroupBox("Operating settings", self._settings_controls)
        operating_form = QFormLayout(operating_group)
        self._settings_motion_enabled = QCheckBox(
            "Confirmed safe for motion", operating_group
        )
        self._settings_offset_spin = _angle_spin(operating_group, -180.0, 180.0)
        self._settings_speed_spin = _angle_spin(operating_group, 0.01, 30.0)
        self._settings_timeout_spin = QDoubleSpinBox(operating_group)
        self._settings_timeout_spin.setRange(0.01, 300.0)
        self._settings_timeout_spin.setSuffix(" s")
        self._settings_polling_spin = QDoubleSpinBox(operating_group)
        self._settings_polling_spin.setRange(0.0, 10.0)
        self._settings_polling_spin.setSuffix(" Hz")
        self._settings_count_spin = QDoubleSpinBox(operating_group)
        self._settings_count_spin.setRange(0.01, 86_400.0)
        self._settings_count_spin.setSuffix(" s")
        operating_form.addRow(self._settings_motion_enabled)
        operating_form.addRow("2-theta datum offset / deg", self._settings_offset_spin)
        operating_form.addRow("Theta speed / deg min-1", self._settings_speed_spin)
        operating_form.addRow("Connection timeout", self._settings_timeout_spin)
        operating_form.addRow("Polling rate", self._settings_polling_spin)
        operating_form.addRow("Default count time", self._settings_count_spin)
        controls_layout.addWidget(operating_group)

        self._settings_code_reset = QGroupBox(
            "Reset settings unlock code", self._settings_controls
        )
        reset_form = QFormLayout(self._settings_code_reset)
        self._new_settings_code = QLineEdit(self._settings_code_reset)
        self._confirm_settings_code = QLineEdit(self._settings_code_reset)
        for edit in (self._new_settings_code, self._confirm_settings_code):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        reset_form.addRow("New code", self._new_settings_code)
        reset_form.addRow("Confirm code", self._confirm_settings_code)
        controls_layout.addWidget(self._settings_code_reset)

        self._settings_save_button = QPushButton(
            "Apply and save instrument settings", self._settings_controls
        )
        controls_layout.addWidget(self._settings_save_button)
        controls_layout.addStretch(1)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._settings_controls)
        layout.addWidget(scroll)
        self._set_settings_locked(True)
        return page

    def _build_motion_status_bar(self) -> QWidget:
        bar = QWidget(self)
        layout = QGridLayout(bar)
        layout.setContentsMargins(4, 2, 4, 2)
        self._synoptic_engine_label = QLabel("Engine: disconnected", bar)
        self._synoptic_motion_label = QLabel("Motion: idle", bar)
        self._synoptic_target_label = QLabel("Targets: --", bar)
        self._synoptic_speed_label = QLabel("Rates: --", bar)
        self._synoptic_at_target_label = QLabel("At target: --", bar)
        self._synoptic_updated_label = QLabel("Last updated: --", bar)
        layout.addWidget(self._synoptic_engine_label, 0, 0)
        layout.addWidget(self._synoptic_motion_label, 0, 1)
        layout.addWidget(self._synoptic_at_target_label, 0, 2)
        layout.addWidget(self._synoptic_target_label, 1, 0, 1, 2)
        layout.addWidget(self._synoptic_speed_label, 1, 2)
        layout.addWidget(self._synoptic_updated_label, 2, 0, 1, 3)
        return bar

    def _connect_signals(self) -> None:
        self._connect_button.clicked.connect(self._on_connect)
        self._instrument_combo.currentTextChanged.connect(self._on_instrument_changed)
        self._polling_rate_spin.valueChanged.connect(self._engine.set_polling_rate)
        self._duration_spin.valueChanged.connect(self._engine.set_count_duration)
        self._mode_combo.currentIndexChanged.connect(self._update_speed_label)
        self._disconnect_button.clicked.connect(self._engine.disconnect_instrument)
        self._save_button.clicked.connect(self._on_save)
        self._settings_lock_button.clicked.connect(self._toggle_settings_lock)
        self._settings_save_button.clicked.connect(self._on_settings_save)
        self._read_button.clicked.connect(self._engine.read_controller_state)
        self._move_button.clicked.connect(self._on_move)
        self._cancel_button.clicked.connect(self._engine.cancel_operation)
        self._count_button.clicked.connect(self._on_count)
        self._zero_theta_button.clicked.connect(lambda: self._confirm_zero("theta"))
        self._zero_two_button.clicked.connect(lambda: self._confirm_zero("2-theta"))
        self._reset_limit_button.clicked.connect(self._engine.reset_limit_latch)
        self._disable_button.clicked.connect(self._engine.disable_motors)
        self._engine.publisher.state_updated.connect(self._on_state_updated)
        self._engine.publisher.engine_status_changed.connect(self._on_engine_status_changed)
        self._engine.publisher.count_duration_changed.connect(self._on_count_duration_changed)
        self._engine.publisher.operation_failed.connect(self._on_operation_failed)
        self._engine.publisher.operation_finished.connect(self._on_operation_finished)

    def _load_preferences(self) -> None:
        instrument = self._engine.preferred_instrument_name
        index = self._instrument_combo.findText(instrument)
        self._wharfdale_address = self._engine.preferred_address or "index:0"
        self._instrument_combo.setCurrentIndex(max(0, index))
        self._on_instrument_changed(self._instrument_combo.currentText())
        state = self._engine.get_engine_state()
        self._motion_enabled.setChecked(state.motion_enabled)
        mode_index = self._mode_combo.findData(state.motion_mode)
        self._mode_combo.setCurrentIndex(max(0, mode_index))
        self._speed_spin.setValue(state.speed_deg_per_min)
        self._offset_spin.setValue(state.two_theta_offset_deg)
        self._duration_spin.setValue(self._engine.count_duration_s)
        self._load_instrument_settings()
        self._update_speed_label()

    def _load_instrument_settings(self) -> None:
        """Populate the safety page from the active engine configuration."""
        mechanics = self._engine.mechanics
        state = self._engine.get_engine_state()
        self._theta_steps_spin.setValue(mechanics.theta.steps_per_degree)
        self._theta_min_spin.setValue(mechanics.theta.minimum_deg)
        self._theta_max_spin.setValue(mechanics.theta.maximum_deg)
        self._theta_backlash_spin.setValue(mechanics.theta.backlash_steps)
        self._two_theta_steps_spin.setValue(mechanics.two_theta.steps_per_degree)
        self._two_theta_min_spin.setValue(mechanics.two_theta.minimum_deg)
        self._two_theta_max_spin.setValue(mechanics.two_theta.maximum_deg)
        self._two_theta_backlash_spin.setValue(mechanics.two_theta.backlash_steps)
        self._settings_motion_enabled.setChecked(mechanics.motion_enabled)
        self._settings_offset_spin.setValue(state.two_theta_offset_deg)
        self._settings_speed_spin.setValue(state.speed_deg_per_min)
        self._settings_timeout_spin.setValue(self._engine.connection_timeout_s)
        self._settings_polling_spin.setValue(self._engine.polling_rate_hz)
        self._settings_count_spin.setValue(self._engine.count_duration_s)

    def _set_settings_locked(self, locked: bool) -> None:
        """Apply the locked state and hide code-reset controls when locked."""
        self._settings_unlocked = not locked
        self._settings_controls.setEnabled(not locked)
        self._settings_code_reset.setVisible(not locked)
        self._settings_lock_button.setText(
            "Unlock settings" if locked else "Lock settings"
        )

    @pyqtSlot()
    def _toggle_settings_lock(self) -> None:
        if self._settings_unlocked:
            self._new_settings_code.clear()
            self._confirm_settings_code.clear()
            self._load_instrument_settings()
            self._set_settings_locked(True)
            return
        code, accepted = QInputDialog.getText(
            self,
            "Unlock instrument settings",
            "Settings unlock code:",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        if not self._engine.verify_settings_unlock_code(code):
            QMessageBox.warning(self, "Unlock failed", "The settings code is incorrect.")
            return
        self._set_settings_locked(False)

    @pyqtSlot()
    def _on_settings_save(self) -> None:
        """Validate, apply, and persist unlocked instrument settings."""
        if not self._settings_unlocked:
            return
        new_code = self._new_settings_code.text()
        confirmation = self._confirm_settings_code.text()
        if new_code or confirmation:
            if not new_code:
                QMessageBox.warning(self, "Invalid code", "The new code cannot be empty.")
                return
            if new_code != confirmation:
                QMessageBox.warning(self, "Invalid code", "The new codes do not match.")
                return
        try:
            self._engine.configure_instrument_settings(
                theta_steps_per_degree=self._theta_steps_spin.value(),
                theta_minimum_deg=self._theta_min_spin.value(),
                theta_maximum_deg=self._theta_max_spin.value(),
                theta_backlash_steps=self._theta_backlash_spin.value(),
                two_theta_steps_per_degree=self._two_theta_steps_spin.value(),
                two_theta_minimum_deg=self._two_theta_min_spin.value(),
                two_theta_maximum_deg=self._two_theta_max_spin.value(),
                two_theta_backlash_steps=self._two_theta_backlash_spin.value(),
                timeout_s=self._settings_timeout_spin.value(),
            )
            self._engine.configure_motion(
                enabled=self._settings_motion_enabled.isChecked(),
                mode=self._mode_combo.currentData(),
                speed_deg_per_min=self._settings_speed_spin.value(),
                two_theta_offset_deg=self._settings_offset_spin.value(),
            )
            self._engine.set_polling_rate(self._settings_polling_spin.value())
            self._engine.set_count_duration(self._settings_count_spin.value())
            if new_code:
                self._engine.set_settings_unlock_code(new_code)
            path = self._engine.save_configuration()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid instrument settings", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - report local persistence failures
            QMessageBox.critical(
                self, "Save Configuration", f"Failed to save configuration:\n{exc}"
            )
            return
        self._motion_enabled.setChecked(self._settings_motion_enabled.isChecked())
        self._offset_spin.setValue(self._settings_offset_spin.value())
        self._speed_spin.setValue(self._settings_speed_spin.value())
        self._polling_rate_spin.setValue(self._settings_polling_spin.value())
        self._duration_spin.setValue(self._settings_count_spin.value())
        self._new_settings_code.clear()
        self._confirm_settings_code.clear()
        self._error_label.setText(f"Saved {path.name}")
        QMessageBox.information(
            self, "Save Configuration", f"Configuration saved to:\n{path}"
        )

    @pyqtSlot(float)
    def _on_count_duration_changed(self, duration_s: float) -> None:
        """Track temporary sequence overrides of the shared count time."""
        previous = self._duration_spin.blockSignals(True)
        try:
            self._duration_spin.setValue(duration_s)
        finally:
            self._duration_spin.blockSignals(previous)

    @pyqtSlot(str)
    def _on_instrument_changed(self, instrument: str) -> None:
        simulated = instrument == "Simulated"
        self._address_edit.setReadOnly(simulated)
        self._address_edit.setText("Built-in simulator" if simulated else self._wharfdale_address)
        self._address_edit.set_status(VisaResourceStatus.DISCONNECTED)

    @pyqtSlot()
    def _update_speed_label(self) -> None:
        label = self._speed_spin.parent().layout().labelForField(self._speed_spin)
        if isinstance(label, QLabel):
            mode = self._mode_combo.currentData()
            axis = "2-theta" if mode is XrayMotionMode.TWO_THETA else "Theta"
            label.setText(f"{axis} speed / deg min-1")

    @pyqtSlot()
    def _on_connect(self) -> None:
        self._address_edit.set_status(VisaResourceStatus.CONNECTING)
        try:
            instrument = self._instrument_combo.currentText()
            address = "" if instrument == "Simulated" else self._address_edit.text()
            if instrument == "Wharfedale":
                self._wharfdale_address = address
            self._engine.connect_driver(instrument, address)
        except Exception as exc:  # noqa: BLE001 - show connection diagnostics
            self._address_edit.set_status(VisaResourceStatus.ERROR)
            QMessageBox.critical(self, "X-ray connection failed", str(exc))
        else:
            self._address_edit.set_status(VisaResourceStatus.CONNECTED)

    @pyqtSlot()
    def _on_save(self) -> None:
        try:
            self._apply_motion_configuration()
            path = self._engine.save_configuration()
        except Exception as exc:  # noqa: BLE001 - report local persistence failures
            QMessageBox.critical(
                self, "Save Configuration", f"Failed to save configuration:\n{exc}"
            )
            return
        self._error_label.setText(f"Saved {path.name}")
        QMessageBox.information(
            self, "Save Configuration", f"Configuration saved to:\n{path}"
        )

    @pyqtSlot()
    def _on_move(self) -> None:
        try:
            self._apply_motion_configuration()
            self._engine.start_move(
                self._target_spin.value(),
                self._mode_combo.currentData(),
                speed_deg_per_min=self._speed_spin.value(),
            )
        except Exception as exc:  # noqa: BLE001 - present validation errors
            QMessageBox.warning(self, "X-ray motion rejected", str(exc))

    @pyqtSlot()
    def _on_count(self) -> None:
        try:
            self._engine.start_count()
        except Exception as exc:  # noqa: BLE001 - present operation conflicts
            QMessageBox.warning(self, "X-ray count rejected", str(exc))

    def _apply_motion_configuration(self) -> None:
        self._engine.configure_motion(
            enabled=self._motion_enabled.isChecked(),
            mode=self._mode_combo.currentData(),
            speed_deg_per_min=self._speed_spin.value(),
            two_theta_offset_deg=self._offset_spin.value(),
        )

    def _confirm_zero(self, axis: str) -> None:
        answer = QMessageBox.question(
            self,
            f"Zero {axis}",
            f"This changes the hardware {axis} datum. Continue?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if axis == "theta":
            self._engine.zero_theta()
        else:
            self._engine.zero_two_theta()

    @pyqtSlot(XrayEngineState)
    def _on_state_updated(self, state: XrayEngineState) -> None:
        snapshot = state.snapshot
        if snapshot is not None:
            self._theta_label.setText(f"{snapshot.theta_deg:.4f} deg")
            self._two_theta_label.setText(f"{snapshot.two_theta_deg:.4f} deg")
            self._counts_label.setText(f"{snapshot.counts:d}")
            self._geometry.set_geometry(
                snapshot.theta_deg,
                snapshot.two_theta_deg,
                state.two_theta_offset_deg,
            )
        self._geometry.set_count_rate(state.count_rate_hz)
        if state.count_rate_hz is not None:
            self._rate_label.setText(f"{state.count_rate_hz:.3f} count/s")
        motion = "moving" if state.moving else "idle"
        self._synoptic_motion_label.setText(f"Motion: {motion}")
        self._synoptic_target_label.setText(
            "Targets: "
            f"theta={_angle_text(state.theta_target_deg)}, "
            f"2-theta={_angle_text(state.two_theta_target_deg)}"
        )
        self._synoptic_speed_label.setText(
            f"Rates: theta={state.theta_speed_deg_per_min:g}, "
            f"2-theta={state.two_theta_speed_deg_per_min:g} deg/min"
        )
        target_colour = "#44aa44" if state.at_target else "#cc4444"
        self._synoptic_at_target_label.setText(
            f"{_colour_dot(target_colour)} At target: {'yes' if state.at_target else 'no'}"
        )
        if state.updated_at is not None:
            self._synoptic_updated_label.setText(
                f"Last updated: {state.updated_at.astimezone():%H:%M:%S}"
            )
        self._error_label.clear()

    @pyqtSlot(XrayEngineStatus)
    def _on_engine_status_changed(self, status: XrayEngineStatus) -> None:
        self._status_label.setText(status.value.capitalize())
        status_colour = {
            XrayEngineStatus.STOPPED: "#888888",
            XrayEngineStatus.DISCONNECTED: "#cc4444",
            XrayEngineStatus.CONNECTED: "#cc8800",
            XrayEngineStatus.POLLING: "#44aa44",
            XrayEngineStatus.MOVING: "#cc8800",
            XrayEngineStatus.COUNTING: "#cc8800",
            XrayEngineStatus.ERROR: "#cc0000",
        }[status]
        self._synoptic_engine_label.setText(f"{_colour_dot(status_colour)} Engine: {status.value}")
        connected = status not in {
            XrayEngineStatus.DISCONNECTED,
            XrayEngineStatus.STOPPED,
        }
        busy = status in {XrayEngineStatus.MOVING, XrayEngineStatus.COUNTING}
        if status is XrayEngineStatus.ERROR:
            self._address_edit.set_status(VisaResourceStatus.ERROR)
        elif connected:
            self._address_edit.set_status(VisaResourceStatus.CONNECTED)
        else:
            self._address_edit.set_status(VisaResourceStatus.DISCONNECTED)
        self._connect_button.setEnabled(not connected)
        self._disconnect_button.setEnabled(connected and not busy)
        self._read_button.setEnabled(connected and not busy)
        self._move_button.setEnabled(connected and not busy)
        self._count_button.setEnabled(connected and not busy)
        self._cancel_button.setEnabled(busy)
        for button in (
            self._zero_theta_button,
            self._zero_two_button,
            self._reset_limit_button,
            self._disable_button,
        ):
            button.setEnabled(connected and not busy)

    @pyqtSlot(str)
    def _on_operation_failed(self, message: str) -> None:
        self._error_label.setText(message)

    @pyqtSlot()
    def _on_operation_finished(self) -> None:
        self._on_engine_status_changed(self._engine.status)


def _angle_spin(parent: QWidget, minimum: float, maximum: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox(parent)
    spin.setRange(minimum, maximum)
    spin.setDecimals(4)
    spin.setSingleStep(0.1)
    return spin


def _integer_spin(parent: QWidget, minimum: int, maximum: int) -> QSpinBox:
    spin = QSpinBox(parent)
    spin.setRange(minimum, maximum)
    return spin


def _angle_text(value: float | None) -> str:
    return "--" if value is None else f"{value:.3f} deg"


def _colour_dot(dot_colour: str, size: int = 12) -> str:
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'border-radius:{size // 2}px;background:{dot_colour};"></span>'
    )
