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
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
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
    waveform, scaled by *amplitude*, offset by *offset*, and phase-shifted
    by *phase*.

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
        periods of the selected waveform, scaled by :attr:`amplitude` and
        shifted by :attr:`offset`.  The waveform is phase-shifted by
        :attr:`phase` degrees.

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
        return self._amplitude * wave + self._offset

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

        self._amplitude_spin = QDoubleSpinBox()
        self._amplitude_spin.setRange(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS)
        self._amplitude_spin.setSingleStep(0.1)
        self._amplitude_spin.setDecimals(4)
        self._amplitude_spin.setValue(self._generator.amplitude)
        self._amplitude_spin.setToolTip("Peak-to-centre amplitude")
        form.addRow("Amplitude:", self._amplitude_spin)

        self._offset_spin = QDoubleSpinBox()
        self._offset_spin.setRange(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS)
        self._offset_spin.setSingleStep(0.1)
        self._offset_spin.setDecimals(4)
        self._offset_spin.setValue(self._generator.offset)
        self._offset_spin.setToolTip("DC offset")
        form.addRow("Offset:", self._offset_spin)

        self._phase_spin = QDoubleSpinBox()
        self._phase_spin.setRange(-360.0, 360.0)
        self._phase_spin.setSingleStep(1.0)
        self._phase_spin.setDecimals(2)
        self._phase_spin.setValue(self._generator.phase)
        self._phase_spin.setToolTip("Phase shift in degrees")
        form.addRow("Phase (°):", self._phase_spin)

        self._points_spin = QSpinBox()
        self._points_spin.setRange(2, _MAX_NUM_POINTS)
        self._points_spin.setValue(self._generator.num_points)
        self._points_spin.setToolTip("Number of points in the sequence")
        form.addRow("Points:", self._points_spin)

        self._periods_spin = QDoubleSpinBox()
        self._periods_spin.setRange(0.01, 1000.0)
        self._periods_spin.setSingleStep(0.5)
        self._periods_spin.setDecimals(2)
        self._periods_spin.setValue(self._generator.periods)
        self._periods_spin.setToolTip("Number of complete periods in the scan")
        form.addRow("Periods:", self._periods_spin)

        root_layout.addWidget(controls_box)

        # --- Preview plot ---
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setLabel("bottom", "Point index")
        self._plot_widget.setLabel("left", "Value")
        self._curve = self._plot_widget.plot(pen=pg.mkPen(color="#1f77b4", width=1.5))
        root_layout.addWidget(self._plot_widget)

        self.setLayout(root_layout)

    def _connect_signals(self) -> None:
        """Wire control signals to parameter setters and plot refresh."""
        self._waveform_combo.currentIndexChanged.connect(self._on_waveform_changed)
        self._amplitude_spin.valueChanged.connect(self._on_amplitude_changed)
        self._offset_spin.valueChanged.connect(self._on_offset_changed)
        self._phase_spin.valueChanged.connect(self._on_phase_changed)
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
