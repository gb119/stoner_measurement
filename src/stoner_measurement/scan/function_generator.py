"""Function-based scan generator and its configuration widget.

:class:`FunctionScanGenerator` generates a sequence of values based on
standard waveform functions (sine, triangle, square, sawtooth).
:class:`FunctionScanWidget` provides a live-preview Qt widget for adjusting
the generator parameters.
"""

from __future__ import annotations

import enum
import json
import logging

import numpy as np
import pyqtgraph as pg
from qtpy import QtGui
from qtpy.QtCore import QObject, QSettings, QSize, Qt
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.scan.base import BaseScanGenerator
from stoner_measurement.ui.aspect_ratio_widget import MaximumAspectRatioWidget
from stoner_measurement.ui.widgets import SISpinBox

# Shared spin-box limits used across the widget controls.
_SPINBOX_MAX_ABS = 1e6
_MAX_NUM_POINTS = 10_000
_PRESET_ICON_SIZE = QSize(54, 36)
_PRESET_BUTTON_SIZE = QSize(64, 44)
_PRESET_SETTINGS_PREFIX = "scan/function_generator/user_preset_"
_PRESET_PARAMETER_KEYS = (
    "waveform",
    "amplitude",
    "offset",
    "phase",
    "exponent",
    "periods",
    "num_points",
)

logger = logging.getLogger(__name__)


def _preset_settings() -> QSettings:
    """Return the persistent application store used for user waveform presets."""
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "University of Leeds",
        "Stoner Measurement",
    )


class _PresetButton(QPushButton):
    """Push button that reports Ctrl-click separately from an ordinary click."""

    control_clicked = pyqtSignal()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        """Store a preset on Ctrl-left-release without also recalling it."""
        is_control_click = (
            event.button() == Qt.MouseButton.LeftButton
            and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            and self.rect().contains(event.pos())
        )
        if is_control_click:
            self.setDown(False)
            self.control_clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class WaveformType(enum.Enum):
    """Supported waveform shapes for :class:`FunctionScanGenerator`.

    Note:
        Cosine is not a separate waveform type.  It is equivalent to
        :attr:`SINE` with a phase shift of 90°.
    """

    SINE = "Sine"
    TRIANGLE = "Triangle"
    SQUARE = "Square"
    SAWTOOTH = "Sawtooth"


class FunctionScanGenerator(BaseScanGenerator):
    """Scan generator that produces values from a standard waveform function.

    The output sequence spans *periods* complete periods of the selected
    waveform, transformed by *exponent*, scaled by *amplitude*, offset by
    *offset*, and phase-shifted by *phase*.

    A cosine waveform is equivalent to :attr:`WaveformType.SINE` with
    ``phase=90.0``.

    Attributes:
        waveform (WaveformType):
            The waveform shape used to compute the sequence.
        amplitude (float):
            Peak-to-centre amplitude.
        offset (float):
            DC offset added to the waveform.
        phase (float):
            Phase shift in degrees.
        exponent (float):
            Power-law exponent applied to the waveform before scaling.
        periods (float):
            Number of complete periods spanned by the sequence (> 0).
        num_points (int):
            Number of points in the sequence (≥ 2).

    Keyword Parameters:
        waveform (WaveformType):
            Initial waveform type. Defaults to :attr:`WaveformType.SINE`.
        amplitude (float):
            Initial amplitude. Defaults to ``1.0``.
        offset (float):
            Initial DC offset. Defaults to ``0.0``.
        phase (float):
            Initial phase shift in degrees. Defaults to ``0.0``.
        exponent (float):
            Initial power-law exponent. Defaults to ``1.0``.
        periods (float):
            Initial number of complete periods. Defaults to ``1.0``.
        num_points (int):
            Initial number of points. Defaults to ``100``.
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> import numpy as np
        >>> gen = FunctionScanGenerator(num_points=10)
        >>> len(gen.generate())
        10
        >>> gen.phase = 90.0  # cosine behaviour
        >>> values = list(gen)
        >>> len(values)
        10
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        waveform: WaveformType = WaveformType.SINE,
        amplitude: float | str = 1.0,
        offset: float | str = 0.0,
        phase: float | str = 0.0,
        exponent: float | str = 1.0,
        periods: float | str = 1.0,
        num_points: int = 100,
        parent: QObject | None = None,
    ) -> None:
        """Initialise the function scan generator with the given parameters."""
        super().__init__(parent)
        self._waveform = WaveformType(waveform)
        self._amplitude = amplitude
        self._offset = offset
        self._phase = phase
        self._exponent = exponent
        self._periods = periods if isinstance(periods, str) else max(1e-9, float(periods))
        self._num_points = max(2, int(num_points))
        self._generation_failed = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def waveform(self) -> WaveformType:
        """The waveform shape used to compute the sequence."""
        return self._waveform

    @waveform.setter
    def waveform(self, value: WaveformType) -> None:
        self._waveform = WaveformType(value)
        self._invalidate_cache()

    @property
    def amplitude(self) -> float | str:
        """Peak-to-centre amplitude of the waveform."""
        return self._amplitude

    @amplitude.setter
    def amplitude(self, value: float | str) -> None:
        self._amplitude = value
        self._invalidate_cache()

    @property
    def offset(self) -> float | str:
        """DC offset added to the waveform."""
        return self._offset

    @offset.setter
    def offset(self, value: float | str) -> None:
        self._offset = value
        self._invalidate_cache()

    @property
    def phase(self) -> float | str:
        """Phase shift in degrees."""
        return self._phase

    @phase.setter
    def phase(self, value: float | str) -> None:
        self._phase = value
        self._invalidate_cache()

    @property
    def exponent(self) -> float | str:
        """Power-law exponent applied before amplitude/offset scaling."""
        return self._exponent

    @exponent.setter
    def exponent(self, value: float | str) -> None:
        self._exponent = value
        self._invalidate_cache()

    @property
    def num_points(self) -> int:
        """Number of points in the sequence (≥ 2)."""
        return self._num_points

    @num_points.setter
    def num_points(self, value: int) -> None:
        self._num_points = max(2, int(value))
        self._invalidate_cache()

    @property
    def periods(self) -> float | str:
        """Number of complete periods spanned by the sequence (> 0)."""
        return self._periods

    @periods.setter
    def periods(self, value: float | str) -> None:
        self._periods = value if isinstance(value, str) else max(1e-9, float(value))
        self._invalidate_cache()

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def generate(self) -> np.ndarray:
        """Compute the waveform sequence.

        Builds an array of *num_points* values spanning *periods* complete
        periods of the selected waveform, transformed by :attr:`exponent`,
        scaled by :attr:`amplitude`, and shifted by :attr:`offset`. The
        waveform is phase-shifted by :attr:`phase` degrees.

        Returns:
            (np.ndarray):
                A 1-D array of *num_points* float values.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> import numpy as np
            >>> gen = FunctionScanGenerator(num_points=4, amplitude=1.0, offset=0.0, phase=0.0)
            >>> arr = gen.generate()
            >>> arr.shape
            (4,)
            >>> abs(arr[0]) < 1e-9  # sine starts at 0
            True
        """
        self._generation_failed = False
        try:
            amplitude = self.eval_float(self._amplitude)
            offset = self.eval_float(self._offset)
            phase = self.eval_float(self._phase)
            exponent = self.eval_float(self._exponent)
            periods = max(1e-9, self.eval_float(self._periods))
        except Exception as exc:  # noqa: BLE001 - an unresolved waveform is representable
            self._generation_failed = True
            logger.warning(
                "Function scan waveform could not be generated; using NaNs until its runtime "
                "expression can be evaluated: %s",
                exc,
            )
            return np.full(self._num_points, np.nan, dtype=float)
        phase_rad = np.deg2rad(phase)
        x = np.linspace(0.0, 2.0 * np.pi * periods, self._num_points) + phase_rad
        wf = self._waveform
        if wf is WaveformType.SINE:
            wave = np.sin(x)
        elif wf is WaveformType.TRIANGLE:
            # Produce a triangle wave via the arcsin-of-sin identity,
            # which gives a smooth, exact triangle with amplitude 1.
            wave = (2.0 / np.pi) * np.arcsin(np.sin(x))
        elif wf is WaveformType.SQUARE:
            # Use np.where to ensure values are strictly ±1 with no zero crossings.
            wave = np.where(np.sin(x) >= 0, 1.0, -1.0)
        elif wf is WaveformType.SAWTOOTH:
            # Rising sawtooth: -1 at the start, +1 just before the period ends.
            wave = 2.0 * ((x / (2.0 * np.pi)) % 1.0) - 1.0
        else:
            wave = np.zeros(self._num_points)
        wave = np.sign(wave) * np.abs(wave) ** exponent
        return amplitude * wave + offset

    @property
    def values(self) -> np.ndarray:
        """Return waveform values without caching a failed NaN placeholder."""
        values = super().values
        if self._generation_failed:
            self._cache = None
        return values

    def measure_flags(self) -> np.ndarray:
        """Return per-point measure flags for the waveform sequence.

        The function scan generator always records every point as a
        measurement, so all flags are ``True``.

        Returns:
            (np.ndarray):
                A 1-D boolean array of length :attr:`num_points`, all
                ``True``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = FunctionScanGenerator(num_points=5)
            >>> gen.measure_flags().tolist()
            [True, True, True, True, True]
        """
        return np.ones(self._num_points, dtype=bool)

    def _representation_details(self) -> str:
        """Return the main waveform parameters and point count."""
        def display(value: float | str) -> str:
            return value if isinstance(value, str) else f"{value:g}"

        return (
            f"{self._waveform.value}, amplitude={display(self._amplitude)}, "
            f"offset={display(self._offset)}, phase={display(self._phase)} degrees, "
            f"periods={display(self._periods)}, exponent={display(self._exponent)}, "
            f"{self._num_points} points"
        )

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a :class:`FunctionScanWidget` configured for this generator.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                A :class:`FunctionScanWidget` bound to this generator.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = FunctionScanGenerator()
            >>> widget = gen.config_widget()
            >>> widget is not None
            True
        """
        return FunctionScanWidget(generator=self, parent=parent)

    def to_json(self) -> dict:
        """Serialise this generator's configuration to a JSON-compatible dict.

        Returns:
            (dict):
                A dict with keys ``"type"``, ``"waveform"``, ``"amplitude"``,
                ``"offset"``, ``"phase"``, ``"exponent"``, ``"periods"``, and
                ``"num_points"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = FunctionScanGenerator(amplitude=2.0, num_points=50)
            >>> d = gen.to_json()
            >>> d["type"]
            'FunctionScanGenerator'
            >>> d["amplitude"]
            2.0
            >>> d["num_points"]
            50
        """
        return {
            "type": "FunctionScanGenerator",
            "waveform": self._waveform.value,
            "amplitude": self._amplitude,
            "offset": self._offset,
            "phase": self._phase,
            "exponent": self._exponent,
            "periods": self._periods,
            "num_points": self._num_points,
            "units": self._units,
        }

    @classmethod
    def _from_json_data(cls, data: dict, parent=None) -> FunctionScanGenerator:
        """Reconstruct a :class:`FunctionScanGenerator` from serialised *data*.

        Args:
            data (dict):
                Dict as produced by :meth:`to_json`.

        Keyword Parameters:
            parent (QObject | None):
                Optional Qt parent object.

        Returns:
            (FunctionScanGenerator):
                A fully configured instance.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = FunctionScanGenerator(amplitude=3.0, offset=1.0, num_points=20)
            >>> restored = FunctionScanGenerator._from_json_data(gen.to_json())
            >>> restored.amplitude
            3.0
            >>> restored.offset
            1.0
            >>> restored.num_points
            20
        """
        waveform = WaveformType(data.get("waveform", WaveformType.SINE.value))
        instance = cls(
            waveform=waveform,
            amplitude=data.get("amplitude", 1.0),
            offset=data.get("offset", 0.0),
            phase=data.get("phase", 0.0),
            exponent=data.get("exponent", 1.0),
            periods=data.get("periods", 1.0),
            num_points=int(data.get("num_points", 100)),
            parent=parent,
        )
        instance.units = str(data.get("units", ""))
        return instance


class FunctionScanWidget(QWidget):
    """Configuration and live-preview widget for :class:`FunctionScanGenerator`.

    The widget is divided into two regions:

    * **Controls** (top) — a group box containing a form with spin boxes and
      a combo box for each generator parameter.
    * **Preview plot** (bottom) — a :class:`pyqtgraph.PlotWidget` that
      updates in real time as the user adjusts the controls.

    Args:
        generator (FunctionScanGenerator):
            The generator instance to configure and preview.

    Keyword Parameters:
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> gen = FunctionScanGenerator(num_points=50)
        >>> widget = FunctionScanWidget(generator=gen)
        >>> widget.get_generator() is gen
        True
    """

    def __init__(
        self,
        generator: FunctionScanGenerator,
        parent: QWidget | None = None,
    ) -> None:
        """Initialise the widget and bind it to *generator*."""
        super().__init__(parent)
        self._generator = generator
        self._build_ui()
        self._connect_signals()
        self._refresh_plot()

    def _build_ui(self) -> None:
        """Build the controls group box and preview plot."""
        root_layout = QVBoxLayout(self)

        # --- Controls group box ---
        controls_box = QGroupBox("Parameters")
        controls_layout = QVBoxLayout(controls_box)
        waveform_form = QFormLayout()

        self._waveform_combo = QComboBox()
        for wt in WaveformType:
            self._waveform_combo.addItem(wt.value, wt)
        self._waveform_combo.setCurrentIndex(list(WaveformType).index(self._generator.waveform))
        waveform_form.addRow("Waveform:", self._waveform_combo)
        controls_layout.addLayout(waveform_form)

        self._parameter_grid = QGridLayout()
        self._parameter_grid.setColumnStretch(1, 1)
        self._parameter_grid.setColumnStretch(3, 1)
        controls_layout.addLayout(self._parameter_grid)

        self._amplitude_spin = SISpinBox(allow_expressions=True)
        self._amplitude_spin.setOpts(
            bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), step=0.1, decimals=4, siPrefix=True
        )
        self._amplitude_spin.setValue(self._generator.amplitude)
        self._amplitude_spin.setToolTip("Peak-to-centre amplitude")
        self._parameter_grid.addWidget(QLabel("Amplitude:"), 0, 0)
        self._parameter_grid.addWidget(self._amplitude_spin, 0, 1)

        self._offset_spin = SISpinBox(allow_expressions=True)
        self._offset_spin.setOpts(
            bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), step=0.1, decimals=4, siPrefix=True
        )
        self._offset_spin.setValue(self._generator.offset)
        self._offset_spin.setToolTip("DC offset")
        self._parameter_grid.addWidget(QLabel("Offset:"), 0, 2)
        self._parameter_grid.addWidget(self._offset_spin, 0, 3)

        self._phase_spin = SISpinBox(allow_expressions=True)
        self._phase_spin.setOpts(bounds=(-360.0, 360.0), step=1.0, decimals=2)
        self._phase_spin.setValue(self._generator.phase)
        self._phase_spin.setToolTip("Phase shift in degrees")
        self._parameter_grid.addWidget(QLabel("Phase (°):"), 2, 0)
        self._parameter_grid.addWidget(self._phase_spin, 2, 1)

        self._exponent_spin = SISpinBox(allow_expressions=True)
        self._exponent_spin.setOpts(
            bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), step=0.1, decimals=4
        )
        self._exponent_spin.setValue(self._generator.exponent)
        self._exponent_spin.setToolTip("Power-law exponent before scaling")
        self._parameter_grid.addWidget(QLabel("Exponent:"), 2, 2)
        self._parameter_grid.addWidget(self._exponent_spin, 2, 3)

        self._points_spin = SISpinBox(int=True)
        self._points_spin.setOpts(bounds=(2, _MAX_NUM_POINTS))
        self._points_spin.setValue(self._generator.num_points)
        self._points_spin.setToolTip("Number of points in the sequence")
        self._parameter_grid.addWidget(QLabel("Points:"), 1, 0)
        self._parameter_grid.addWidget(self._points_spin, 1, 1)

        self._periods_spin = SISpinBox(allow_expressions=True)
        self._periods_spin.setOpts(bounds=(0.01, 1000.0), step=0.5, decimals=2)
        self._periods_spin.setValue(self._generator.periods)
        self._periods_spin.setToolTip("Number of complete periods in the scan")
        self._parameter_grid.addWidget(QLabel("Periods:"), 1, 2)
        self._parameter_grid.addWidget(self._periods_spin, 1, 3)

        root_layout.addWidget(controls_box)

        # --- Built-in and user presets ---
        preset_layout = QHBoxLayout()
        preset_layout.setContentsMargins(0, 0, 0, 0)
        self._preset_buttons: list[_PresetButton] = []
        self._user_preset_buttons: dict[int, _PresetButton] = {}
        built_in_presets = (
            {
                "waveform": WaveformType.SQUARE.value,
                "amplitude": 1e-3,
                "offset": 0.0,
                "phase": 0.0,
                "exponent": 1.0,
                "periods": 4.0,
                "num_points": 8,
            },
            {
                "waveform": WaveformType.TRIANGLE.value,
                "amplitude": 1e-3,
                "offset": 0.0,
                "phase": 0.0,
                "exponent": 1.0,
                "periods": 1.0,
                "num_points": 101,
            },
            {
                "waveform": WaveformType.SINE.value,
                "amplitude": 1e-3,
                "offset": 0.0,
                "phase": 0.0,
                "exponent": 1.0,
                "periods": 1.0,
                "num_points": 101,
            },
        )
        for preset in built_in_presets:
            waveform = WaveformType(preset["waveform"])
            button = _PresetButton()
            button.setIcon(self._waveform_preset_icon(preset))
            button.setIconSize(_PRESET_ICON_SIZE)
            button.setToolTip(f"Apply {waveform.value.lower()} wave preset")
            button.clicked.connect(lambda _checked=False, values=preset: self._apply_preset(values))
            self._add_preset_button(preset_layout, button)

        for slot in range(1, 4):
            button = _PresetButton(str(slot))
            button.clicked.connect(
                lambda _checked=False, user_slot=slot: self._recall_user_preset(user_slot)
            )
            button.control_clicked.connect(
                lambda user_slot=slot: self._store_user_preset(user_slot)
            )
            self._add_preset_button(preset_layout, button)
            self._user_preset_buttons[slot] = button
            self._update_user_preset_tooltip(slot)
        preset_layout.addStretch(1)
        root_layout.addLayout(preset_layout)

        # --- Preview plot ---
        self._plot_widget = pg.PlotWidget()

        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(True)
        font.setFamily("Arial")

        axis_pen = pg.mkPen(color="white", width=2)
        for axis, label in zip(["left", "bottom"], ["Value", "Index"]):
            axis = self._plot_widget.getAxis(axis)
            axis.setTextPen(pg.mkPen("white"))
            axis.setTickFont(font)
            axis.setLabel(
                label,
                **{
                    "font-size": "11pt",
                    "font-family": "Arial",
                    "font-weight": "bold",
                    "color": "white",
                },
            )
            axis.setPen(axis_pen)
        self._curve = self._plot_widget.plot(pen=pg.mkPen(color="yellow", width=2.5))
        self._current_marker = pg.ScatterPlotItem(
            pen=pg.mkPen(color=(255, 220, 0), width=2),
            brush=pg.mkBrush(0, 0, 0, 0),
            symbol="o",
            size=12,
        )
        self._plot_widget.addItem(self._current_marker)
        self._plot_container = MaximumAspectRatioWidget(self._plot_widget)
        root_layout.addWidget(self._plot_container, 1)

        self.setLayout(root_layout)

    def _add_preset_button(self, layout: QHBoxLayout, button: _PresetButton) -> None:
        """Add one consistently sized button to the preset row."""
        button.setMinimumSize(_PRESET_BUTTON_SIZE)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(button)
        self._preset_buttons.append(button)

    @staticmethod
    def _waveform_preset_icon(preset: dict[str, object]) -> QtGui.QIcon:
        """Render a label-free yellow-on-black waveform thumbnail."""
        generator = FunctionScanGenerator(
            waveform=WaveformType(str(preset["waveform"])),
            amplitude=float(preset["amplitude"]),
            offset=float(preset["offset"]),
            phase=float(preset["phase"]),
            exponent=float(preset["exponent"]),
            periods=float(preset["periods"]),
            num_points=int(preset["num_points"]),
        )
        values = generator.generate()
        pixmap = QtGui.QPixmap(_PRESET_ICON_SIZE)
        pixmap.fill(QtGui.QColor("black"))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor("yellow"), 2.0))
        width = float(pixmap.width() - 8)
        height = float(pixmap.height() - 8)
        value_min = float(np.min(values))
        value_range = max(float(np.max(values)) - value_min, 1e-15)
        path = QtGui.QPainterPath()
        for index, value in enumerate(values):
            x = 4.0 + width * index / max(len(values) - 1, 1)
            y = 4.0 + height * (1.0 - (float(value) - value_min) / value_range)
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.drawPath(path)
        painter.end()
        return QtGui.QIcon(pixmap)

    def _current_preset(self) -> dict[str, object]:
        """Return the current waveform parameters in persistent form."""
        data = self._generator.to_json()
        return {key: data[key] for key in _PRESET_PARAMETER_KEYS}

    def _apply_preset(self, preset: dict[str, object]) -> None:
        """Apply all waveform parameters from *preset* and refresh the controls."""
        self._generator.waveform = WaveformType(str(preset["waveform"]))
        self._generator.amplitude = float(preset["amplitude"])
        self._generator.offset = float(preset["offset"])
        self._generator.phase = float(preset["phase"])
        self._generator.exponent = float(preset["exponent"])
        self._generator.periods = float(preset["periods"])
        self._generator.num_points = int(preset["num_points"])
        self.refresh()

    def _store_user_preset(self, slot: int) -> None:
        """Persist the current waveform parameters in user *slot*."""
        settings = _preset_settings()
        settings.setValue(
            f"{_PRESET_SETTINGS_PREFIX}{slot}",
            json.dumps(self._current_preset(), sort_keys=True),
        )
        settings.sync()
        self._update_user_preset_tooltip(slot)

    def _load_user_preset(self, slot: int) -> dict[str, object] | None:
        """Return a validated user preset from persistent storage."""
        raw_value = _preset_settings().value(f"{_PRESET_SETTINGS_PREFIX}{slot}")
        if not isinstance(raw_value, str):
            return None
        try:
            preset = json.loads(raw_value)
            if not isinstance(preset, dict) or not all(
                key in preset for key in _PRESET_PARAMETER_KEYS
            ):
                return None
            return {
                "waveform": WaveformType(str(preset["waveform"])).value,
                "amplitude": float(preset["amplitude"]),
                "offset": float(preset["offset"]),
                "phase": float(preset["phase"]),
                "exponent": float(preset["exponent"]),
                "periods": float(preset["periods"]),
                "num_points": int(preset["num_points"]),
            }
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _user_preset_summary(preset: dict[str, object]) -> str:
        """Return a concise human-readable waveform preset summary."""
        return (
            f"{preset['waveform']}; {int(preset['num_points'])} points; "
            f"{float(preset['periods']):g} periods; "
            f"amplitude {float(preset['amplitude']):g}; "
            f"offset {float(preset['offset']):g}; "
            f"phase {float(preset['phase']):g}°; "
            f"exponent {float(preset['exponent']):g}"
        )

    def _update_user_preset_tooltip(self, slot: int) -> None:
        """Show storage instructions or a summary for user *slot*."""
        button = self._user_preset_buttons[slot]
        preset = self._load_user_preset(slot)
        if preset is None:
            button.setToolTip(f"User preset {slot}: empty; Ctrl-click to store current settings")
            return
        button.setToolTip(
            f"User preset {slot}: {self._user_preset_summary(preset)}. "
            "Click to recall; Ctrl-click to replace"
        )

    def _recall_user_preset(self, slot: int) -> None:
        """Recall user *slot* when it contains a complete, valid preset."""
        preset = self._load_user_preset(slot)
        if preset is not None:
            self._apply_preset(preset)

    def _connect_signals(self) -> None:
        """Wire control signals to parameter setters and plot refresh."""
        self._waveform_combo.currentIndexChanged.connect(self._on_waveform_changed)
        self._amplitude_spin.valueChanged.connect(self._on_amplitude_changed)
        self._offset_spin.valueChanged.connect(self._on_offset_changed)
        self._phase_spin.valueChanged.connect(self._on_phase_changed)
        self._exponent_spin.valueChanged.connect(self._on_exponent_changed)
        self._points_spin.valueChanged.connect(self._on_points_changed)
        self._periods_spin.valueChanged.connect(self._on_periods_changed)
        self._generator.values_changed.connect(self._refresh_plot)
        self._generator.current_point_changed.connect(self._on_current_point_changed)
        self._generator.units_changed.connect(self._update_units)
        self._update_units(self._generator.units)

    def _update_units(self, units: str) -> None:
        """Update the suffix of value spinboxes to match *units*."""
        for spin in (self._amplitude_spin, self._offset_spin):
            spin.setOpts(suffix=units)

    def _on_waveform_changed(self, index: int) -> None:
        """Update generator waveform from combo box selection."""
        self._generator.waveform = self._waveform_combo.itemData(index)

    def _on_amplitude_changed(self, value: float | str) -> None:
        """Update generator amplitude."""
        self._generator.amplitude = value

    def _on_offset_changed(self, value: float | str) -> None:
        """Update generator offset."""
        self._generator.offset = value

    def _on_phase_changed(self, value: float | str) -> None:
        """Update generator phase."""
        self._generator.phase = value

    def _on_exponent_changed(self, value: float | str) -> None:
        """Update generator exponent."""
        self._generator.exponent = value

    def _on_points_changed(self, value: int) -> None:
        """Update generator num_points."""
        self._generator.num_points = value

    def _on_periods_changed(self, value: float | str) -> None:
        """Update generator periods."""
        self._generator.periods = value

    def _refresh_plot(self) -> None:
        """Re-render the preview curve from the current generator values."""
        values = self._generator.values
        x = np.arange(len(values), dtype=float)
        self._curve.setData(x, values)
        self._clear_current_marker()

    def refresh(self) -> None:
        """Reload widget state from the bound generator."""
        self._waveform_combo.setCurrentIndex(list(WaveformType).index(self._generator.waveform))
        self._amplitude_spin.setValue(self._generator.amplitude)
        self._offset_spin.setValue(self._generator.offset)
        self._phase_spin.setValue(self._generator.phase)
        self._exponent_spin.setValue(self._generator.exponent)
        self._points_spin.setValue(self._generator.num_points)
        self._periods_spin.setValue(self._generator.periods)
        self._update_units(self._generator.units)
        self._refresh_plot()
        self.update()

    def _clear_current_marker(self) -> None:
        """Clear the current-point marker from the preview."""
        self._current_marker.setData(x=np.array([], dtype=float), y=np.array([], dtype=float))

    def _on_current_point_changed(self, index: int, value: float) -> None:
        """Move the current-point marker to *(index, value)*."""
        if index < 0:
            self._clear_current_marker()
            return
        self._current_marker.setData(x=np.array([float(index)]), y=np.array([float(value)]))

    def get_generator(self) -> FunctionScanGenerator:
        """Return the :class:`FunctionScanGenerator` bound to this widget.

        Returns:
            (FunctionScanGenerator):
                The generator instance being configured.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = FunctionScanGenerator()
            >>> widget = FunctionScanWidget(generator=gen)
            >>> widget.get_generator() is gen
            True
        """
        return self._generator
