"""Function-based scan generator and its configuration widget.

:class:`FunctionScanGenerator` generates a sequence of values based on
standard waveform functions (sine, triangle, square, sawtooth).
:class:`FunctionScanWidget` provides a live-preview Qt widget for adjusting
the generator parameters.
"""

from __future__ import annotations

import enum

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtGui
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.scan.base import BaseScanGenerator

# Shared spin-box limits used across the widget controls.
_SPINBOX_MAX_ABS = 1e6
_MAX_NUM_POINTS = 10_000


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
        >>> from PyQt6.QtWidgets import QApplication
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

    def __init__(
        self,
        *,
        waveform: WaveformType = WaveformType.SINE,
        amplitude: float = 1.0,
        offset: float = 0.0,
        phase: float = 0.0,
        exponent: float = 1.0,
        periods: float = 1.0,
        num_points: int = 100,
        parent: QObject | None = None,
    ) -> None:
        """Initialise the function scan generator with the given parameters."""
        super().__init__(parent)
        self._waveform = WaveformType(waveform)
        self._amplitude = float(amplitude)
        self._offset = float(offset)
        self._phase = float(phase)
        self._exponent = float(exponent)
        self._periods = max(1e-9, float(periods))
        self._num_points = max(2, int(num_points))

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
    def amplitude(self) -> float:
        """Peak-to-centre amplitude of the waveform."""
        return self._amplitude

    @amplitude.setter
    def amplitude(self, value: float) -> None:
        self._amplitude = float(value)
        self._invalidate_cache()

    @property
    def offset(self) -> float:
        """DC offset added to the waveform."""
        return self._offset

    @offset.setter
    def offset(self, value: float) -> None:
        self._offset = float(value)
        self._invalidate_cache()

    @property
    def phase(self) -> float:
        """Phase shift in degrees."""
        return self._phase

    @phase.setter
    def phase(self, value: float) -> None:
        self._phase = float(value)
        self._invalidate_cache()

    @property
    def exponent(self) -> float:
        """Power-law exponent applied before amplitude/offset scaling."""
        return self._exponent

    @exponent.setter
    def exponent(self, value: float) -> None:
        self._exponent = float(value)
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
    def periods(self) -> float:
        """Number of complete periods spanned by the sequence (> 0)."""
        return self._periods

    @periods.setter
    def periods(self, value: float) -> None:
        self._periods = max(1e-9, float(value))
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> import numpy as np
            >>> gen = FunctionScanGenerator(num_points=4, amplitude=1.0, offset=0.0, phase=0.0)
            >>> arr = gen.generate()
            >>> arr.shape
            (4,)
            >>> abs(arr[0]) < 1e-9  # sine starts at 0
            True
        """
        phase_rad = np.deg2rad(self._phase)
        x = np.linspace(0.0, 2.0 * np.pi * self._periods, self._num_points) + phase_rad
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
        wave = np.sign(wave) * np.abs(wave) ** self._exponent
        return self._amplitude * wave + self._offset

    def measure_flags(self) -> np.ndarray:
        """Return per-point measure flags for the waveform sequence.

        The function scan generator always records every point as a
        measurement, so all flags are ``True``.

        Returns:
            (np.ndarray):
                A 1-D boolean array of length :attr:`num_points`, all
                ``True``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = FunctionScanGenerator(num_points=5)
            >>> gen.measure_flags().tolist()
            [True, True, True, True, True]
        """
        return np.ones(self._num_points, dtype=bool)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a :class:`FunctionScanWidget` configured for this generator.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                A :class:`FunctionScanWidget` bound to this generator.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
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
        return cls(
            waveform=waveform,
            amplitude=float(data.get("amplitude", 1.0)),
            offset=float(data.get("offset", 0.0)),
            phase=float(data.get("phase", 0.0)),
            exponent=float(data.get("exponent", 1.0)),
            periods=float(data.get("periods", 1.0)),
            num_points=int(data.get("num_points", 100)),
            parent=parent,
        )


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
        >>> from PyQt6.QtWidgets import QApplication
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
        form = QFormLayout(controls_box)

        self._waveform_combo = QComboBox()
        for wt in WaveformType:
            self._waveform_combo.addItem(wt.value, wt)
        self._waveform_combo.setCurrentIndex(list(WaveformType).index(self._generator.waveform))
        form.addRow("Waveform:", self._waveform_combo)

        self._amplitude_spin = pg.SpinBox()
        self._amplitude_spin.setOpts(bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), step=0.1, decimals=4, siPrefix=True)
        self._amplitude_spin.setValue(self._generator.amplitude)
        self._amplitude_spin.setToolTip("Peak-to-centre amplitude")
        form.addRow("Amplitude:", self._amplitude_spin)

        self._offset_spin = pg.SpinBox()
        self._offset_spin.setOpts(bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), step=0.1, decimals=4, siPrefix=True)
        self._offset_spin.setValue(self._generator.offset)
        self._offset_spin.setToolTip("DC offset")
        form.addRow("Offset:", self._offset_spin)

        self._phase_spin = pg.SpinBox()
        self._phase_spin.setOpts(bounds=(-360.0, 360.0), step=1.0, decimals=2)
        self._phase_spin.setValue(self._generator.phase)
        self._phase_spin.setToolTip("Phase shift in degrees")
        form.addRow("Phase (°):", self._phase_spin)

        self._exponent_spin = pg.SpinBox()
        self._exponent_spin.setOpts(bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), step=0.1, decimals=4)
        self._exponent_spin.setValue(self._generator.exponent)
        self._exponent_spin.setToolTip("Power-law exponent before scaling")
        form.addRow("Exponent:", self._exponent_spin)

        self._points_spin = pg.SpinBox(int=True)
        self._points_spin.setOpts(bounds=(2, _MAX_NUM_POINTS))
        self._points_spin.setValue(self._generator.num_points)
        self._points_spin.setToolTip("Number of points in the sequence")
        form.addRow("Points:", self._points_spin)

        self._periods_spin = pg.SpinBox()
        self._periods_spin.setOpts(bounds=(0.01, 1000.0), step=0.5, decimals=2)
        self._periods_spin.setValue(self._generator.periods)
        self._periods_spin.setToolTip("Number of complete periods in the scan")
        form.addRow("Periods:", self._periods_spin)

        root_layout.addWidget(controls_box)

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
                label, **{"font-size": "11pt", "font-family": "Arial", "font-weight": "bold", "color": "white"}
            )
            axis.setPen(axis_pen)
        self._curve = self._plot_widget.plot(pen=pg.mkPen(color="yellow", width=2.5))
        root_layout.addWidget(self._plot_widget)

        self.setLayout(root_layout)

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

    def _on_waveform_changed(self, index: int) -> None:
        """Update generator waveform from combo box selection."""
        self._generator.waveform = self._waveform_combo.itemData(index)

    def _on_amplitude_changed(self, value: float) -> None:
        """Update generator amplitude."""
        self._generator.amplitude = value

    def _on_offset_changed(self, value: float) -> None:
        """Update generator offset."""
        self._generator.offset = value

    def _on_phase_changed(self, value: float) -> None:
        """Update generator phase."""
        self._generator.phase = value

    def _on_exponent_changed(self, value: float) -> None:
        """Update generator exponent."""
        self._generator.exponent = value

    def _on_points_changed(self, value: int) -> None:
        """Update generator num_points."""
        self._generator.num_points = value

    def _on_periods_changed(self, value: float) -> None:
        """Update generator periods."""
        self._generator.periods = value

    def _refresh_plot(self) -> None:
        """Re-render the preview curve from the current generator values."""
        values = self._generator.values
        x = np.arange(len(values), dtype=float)
        self._curve.setData(x, values)

    def get_generator(self) -> FunctionScanGenerator:
        """Return the :class:`FunctionScanGenerator` bound to this widget.

        Returns:
            (FunctionScanGenerator):
                The generator instance being configured.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> gen = FunctionScanGenerator()
            >>> widget = FunctionScanWidget(generator=gen)
            >>> widget.get_generator() is gen
            True
        """
        return self._generator
