"""Locate a broad maximum or minimum in noisy x/y trace data."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLineEdit, QSpinBox, QWidget

from stoner_measurement.plugins.transform._branch_splitting import _valid_savgol_window
from stoner_measurement.plugins.transform._trace_selection import TraceChannelSelectionMixin
from stoner_measurement.plugins.transform.base import TransformPlugin
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.widgets import SISpinBox

if TYPE_CHECKING:
    from stoner_measurement.core.sequence_engine import SequenceEngine

MODE_MAXIMUM = "maximum"
MODE_MINIMUM = "minimum"
_MODE_LABELS = {MODE_MAXIMUM: "Maximum", MODE_MINIMUM: "Minimum"}

_X_OUTPUT = "extremum_x"
_Y_OUTPUT = "extremum_y"
DEFAULT_SMOOTHING_WINDOW = 11
DEFAULT_SMOOTHING_POLYORDER = 2
DEFAULT_FIT_WINDOW = 21
DEFAULT_TURNING_PROMINENCE = 0.01


class ExtremumLocatorPlugin(TraceChannelSelectionMixin, TransformPlugin):
    """Locate the x coordinate of a broad maximum or minimum in a trace.

    The selected y data are first smoothed with a Savitzky-Golay filter. The
    global maximum or minimum of that curve identifies the neighbourhood of
    interest, and a quadratic least-squares fit within that neighbourhood
    refines the x and y coordinates. This is more stable than selecting the
    largest raw sample for noisy parabolic or sinusoidal peaks and troughs.

    The **General** tab selects whether to locate a maximum or minimum, an
    optional inclusive x search interval, the source trace, and the y column
    to inspect. It can also add a labelled data marker to the main plot at each
    successful result. Advanced data-source mode allows
    the calculation arrays to come from arbitrary x and y expressions in the
    sequence-engine namespace while the selected trace continues to supply the
    result units.

    The **Advanced** tab controls two stages of noise rejection and refinement:

    * **S-G window** is the number of neighbouring y samples used for
      Savitzky-Golay smoothing. It is coerced to an odd value that fits the
      input. A wider window rejects more point-to-point noise but can flatten
      narrow extrema or blend nearby features.
    * **S-G polynomial** is the polynomial order within each smoothing window.
      It is limited to less than the effective window length. Order 2 is a good
      default for broad parabolic and sinusoidal extrema.
    * **Turning-point prominence** is the minimum peak or trough prominence as
      a fraction of the robust y span inside the selected x interval. Increase
      it to reject small noise features; reduce it for shallow extrema.
    * **Quadratic fit window** is the number of smoothed samples around the
      strongest candidate used for the final parabolic fit. Increase it for a
      broad noisy extremum and decrease it when neighbouring structure would
      bias the fit. It too is coerced to a valid odd window.

    A successful run publishes ``extremum_x`` and ``extremum_y`` as scalar
    outputs in the values catalogue, using the source x and y units. The same
    results are available from the read-only :attr:`extremum_x` and
    :attr:`extremum_y` properties, or together as the read-only
    :attr:`extremum` ``(x, y)`` tuple. Before the first successful run, and
    after a failed run, these properties are ``None``. Invalid, non-finite,
    mismatched, or shorter-than-three-point inputs are logged and produce no
    outputs.

    Attributes:
        trace_key (str):
            Catalogue key of the source trace.
        column_key (str):
            Selected y-data column in the source trace.
        advanced_mode (bool):
            When ``True``, evaluate :attr:`x_expr` and :attr:`y_expr` instead
            of reading the selected trace arrays directly.
        x_expr (str):
            Runtime expression providing x data in advanced mode.
        y_expr (str):
            Runtime expression providing y data in advanced mode.
        mode (str):
            ``"maximum"`` or ``"minimum"``.
        x_min_expr (str):
            Optional inclusive lower x bound, expressed in engine-namespace
            units. Blank searches to the start of the trace.
        x_max_expr (str):
            Optional inclusive upper x bound. Blank searches to the end.
        add_marker (bool):
            Add the successful result to the main plot as a data marker.
        smoothing_window (int):
            Requested Savitzky-Golay smoothing-window length.
        smoothing_polyorder (int):
            Requested Savitzky-Golay local polynomial order.
        turning_point_prominence (float):
            Minimum prominence as a fraction of the robust selected y span.
        fit_window (int):
            Requested local quadratic-fit window length.
        extremum_x (float | None):
            Read-only fitted x coordinate from the latest successful run.
        extremum_y (float | None):
            Read-only fitted y coordinate from the latest successful run.
        extremum (tuple[float, float] | None):
            Read-only fitted ``(x, y)`` coordinate pair.

    Notes:
        The candidate is the highest or lowest qualifying prominent turning
        point in the smoothed, range-limited y data. If the
        local quadratic has the wrong curvature or places its vertex outside
        the fit neighbourhood, the plugin safely falls back to the smoothed
        candidate sample rather than extrapolating.
    """

    add_plot_marker = pyqtSignal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.trace_key = ""
        self.column_key = ""
        self.advanced_mode = False
        self.x_expr = ""
        self.y_expr = ""
        self.mode = MODE_MAXIMUM
        self.x_min_expr = ""
        self.x_max_expr = ""
        self.add_marker = False
        self.smoothing_window = DEFAULT_SMOOTHING_WINDOW
        self.smoothing_polyorder = DEFAULT_SMOOTHING_POLYORDER
        self.turning_point_prominence = DEFAULT_TURNING_PROMINENCE
        self.fit_window = DEFAULT_FIT_WINDOW
        self._extremum: tuple[float, float] | None = None
        self._result_units = {_X_OUTPUT: "", _Y_OUTPUT: ""}
        self._sequence_engine_ref: SequenceEngine | None = None

    @property  # type: ignore[override]
    def sequence_engine(self) -> SequenceEngine | None:
        """Return the owning engine used to wire optional plot markers."""
        return self._sequence_engine_ref

    @sequence_engine.setter
    def sequence_engine(self, engine: SequenceEngine | None) -> None:
        """Attach to an engine and connect the marker signal to its plot."""
        old_plot = getattr(self._sequence_engine_ref, "plot_widget", None)
        if old_plot is not None and hasattr(old_plot, "add_data_marker"):
            try:
                self.add_plot_marker.disconnect(old_plot.add_data_marker)
            except (TypeError, RuntimeError):
                pass
        self._sequence_engine_ref = engine
        new_plot = getattr(engine, "plot_widget", None)
        if new_plot is not None and hasattr(new_plot, "add_data_marker"):
            self.add_plot_marker.connect(new_plot.add_data_marker)

    @property
    def name(self) -> str:
        return "Extremum Locator"

    @property
    def required_inputs(self) -> list[str]:
        return []

    @property
    def output_names(self) -> list[str]:
        return [_X_OUTPUT, _Y_OUTPUT]

    @property
    def extremum(self) -> tuple[float, float] | None:
        """Read-only ``(x, y)`` coordinates from the latest successful run."""
        return self._extremum

    @property
    def extremum_x(self) -> float | None:
        """Read-only x coordinate from the latest successful run."""
        return None if self._extremum is None else self._extremum[0]

    @property
    def extremum_y(self) -> float | None:
        """Read-only y coordinate from the latest successful run."""
        return None if self._extremum is None else self._extremum[1]

    def reported_values(self) -> dict[str, str]:
        """Publish property-based expressions for both result coordinates."""
        var = self.instance_name
        return {
            f"{var}:{_X_OUTPUT}": f"{var}.extremum_x",
            f"{var}:{_Y_OUTPUT}": f"{var}.extremum_y",
        }

    def reported_value_units(self) -> dict[str, str]:
        """Return source x/y units for the reported coordinates."""
        var = self.instance_name
        return {
            f"{var}:{_X_OUTPUT}": self._result_units[_X_OUTPUT],
            f"{var}:{_Y_OUTPUT}": self._result_units[_Y_OUTPUT],
        }

    def transform(self, data: dict[str, Any]) -> dict[str, Any]:
        """Locate and return the configured extremum."""
        del data
        self._extremum = None
        try:
            x, y, column, _names, units, _source = self._get_selected_data_arrays()
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            if x.ndim != 1 or y.ndim != 1 or x.shape != y.shape:
                raise ValueError("x and y data must be matching one-dimensional arrays")
            if len(x) < 3 or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
                raise ValueError("x and y require at least three finite values")
            lower, upper = self._search_bounds()
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("The minimum x search bound cannot exceed the maximum.")
            selected = np.ones(len(x), dtype=bool)
            if lower is not None:
                selected &= x >= lower
            if upper is not None:
                selected &= x <= upper
            if np.count_nonzero(selected) < 3:
                raise ValueError("The selected x range must contain at least three points.")
            result = locate_extremum(
                x[selected],
                y[selected],
                mode=self.mode,
                smoothing_window=self.smoothing_window,
                smoothing_polyorder=self.smoothing_polyorder,
                fit_window=self.fit_window,
                prominence_fraction=self.turning_point_prominence,
            )
            self._extremum = result
            x_columns = _source.get_columns_by_role("x")
            x_unit = units.get(x_columns[0], "") if x_columns else ""
            self._result_units = {_X_OUTPUT: x_unit, _Y_OUTPUT: units.get(column, "")}
            if self.add_marker:
                self.add_plot_marker.emit(*result)
            return {_X_OUTPUT: result[0], _Y_OUTPUT: result[1]}
        except Exception as exc:
            self.log.error("ExtremumLocator: locating extremum failed — %s", exc)
            return {}

    def _search_bounds(self) -> tuple[float | None, float | None]:
        """Evaluate the optional x search bounds."""
        return self._optional_float(self.x_min_expr), self._optional_float(self.x_max_expr)

    def _optional_float(self, expression: str) -> float | None:
        """Evaluate a blank-or-floating-point configuration expression."""
        if not expression.strip():
            return None
        try:
            return self.eval_float(expression)
        except RuntimeError:
            return float(expression)

    def _build_data_tab(self, parent: QWidget | None = None) -> QWidget:
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        mode = QComboBox(widget)
        mode.setObjectName("extremum_mode")
        for value, label in _MODE_LABELS.items():
            mode.addItem(label, value)
        mode.setCurrentIndex(max(0, mode.findData(self.mode)))
        layout.addRow("Locate:", mode)
        x_min = QLineEdit(self.x_min_expr, widget)
        x_min.setObjectName("extremum_x_min")
        x_min.setPlaceholderText("No lower limit")
        x_max = QLineEdit(self.x_max_expr, widget)
        x_max.setObjectName("extremum_x_max")
        x_max.setPlaceholderText("No upper limit")
        marker = QCheckBox(widget)
        marker.setObjectName("extremum_add_marker")
        marker.setChecked(self.add_marker)
        layout.addRow("Minimum x:", x_min)
        layout.addRow("Maximum x:", x_max)
        layout.addRow("Add data marker:", marker)
        controls = self._create_data_source_widgets(
            widget, self.engine_namespace.get("_traces", {})
        )
        self._add_data_selection_rows(layout, controls)
        mode.currentIndexChanged.connect(
            lambda _index: setattr(self, "mode", str(mode.currentData()))
        )
        x_min.editingFinished.connect(lambda: setattr(self, "x_min_expr", x_min.text().strip()))
        x_max.editingFinished.connect(lambda: setattr(self, "x_max_expr", x_max.text().strip()))
        marker.toggled.connect(lambda checked: setattr(self, "add_marker", bool(checked)))
        self._wire_data_source_widgets(controls)
        return widget

    def _build_advanced_tab(self, parent: QWidget | None = None) -> QWidget:
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        smoothing = QSpinBox(widget)
        smoothing.setRange(3, 1_000_001)
        smoothing.setSingleStep(2)
        smoothing.setValue(self.smoothing_window)
        polynomial = QSpinBox(widget)
        polynomial.setRange(0, 100)
        polynomial.setValue(self.smoothing_polyorder)
        prominence = SISpinBox(widget)
        prominence.setObjectName("extremum_prominence")
        prominence.setOpts(bounds=(0.0, 1.0), decimals=6, step=0.01)
        prominence.setValue(self.turning_point_prominence)
        fit = QSpinBox(widget)
        fit.setRange(3, 1_000_001)
        fit.setSingleStep(2)
        fit.setValue(self.fit_window)
        layout.addRow("S-G window:", smoothing)
        layout.addRow("S-G polynomial:", polynomial)
        layout.addRow("Turning-point prominence:", prominence)
        layout.addRow("Quadratic fit window:", fit)
        smoothing.valueChanged.connect(lambda value: setattr(self, "smoothing_window", int(value)))
        polynomial.valueChanged.connect(
            lambda value: setattr(self, "smoothing_polyorder", int(value))
        )
        prominence.sigValueChanged.connect(
            lambda spin: setattr(self, "turning_point_prominence", float(spin.value()))
        )
        fit.valueChanged.connect(lambda value: setattr(self, "fit_window", int(value)))
        return widget

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        def build_tabs() -> list[tuple[str, QWidget]]:
            tabs = super(ExtremumLocatorPlugin, self).config_tabs(parent)
            tabs[0] = ("General", tabs[0][1])
            tabs.insert(1, ("Advanced", self._build_advanced_tab(parent)))
            return tabs

        return self._get_cached_config_tabs(build_tabs)

    def to_json(self) -> dict[str, Any]:
        result = super().to_json()
        result.update(
            {
                "trace_key": self.trace_key,
                "column_key": self.column_key,
                "advanced_mode": self.advanced_mode,
                "x_expr": self.x_expr,
                "y_expr": self.y_expr,
                "mode": self.mode,
                "x_min_expr": self.x_min_expr,
                "x_max_expr": self.x_max_expr,
                "add_marker": self.add_marker,
            }
        )
        for key, default in (
            ("smoothing_window", DEFAULT_SMOOTHING_WINDOW),
            ("smoothing_polyorder", DEFAULT_SMOOTHING_POLYORDER),
            ("turning_point_prominence", DEFAULT_TURNING_PROMINENCE),
            ("fit_window", DEFAULT_FIT_WINDOW),
        ):
            if getattr(self, key) != default:
                result[key] = getattr(self, key)
        return result

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        self.trace_key = str(data.get("trace_key", ""))
        self.column_key = str(data.get("column_key", ""))
        self.advanced_mode = bool(data.get("advanced_mode", False))
        self.x_expr = str(data.get("x_expr", ""))
        self.y_expr = str(data.get("y_expr", ""))
        mode = str(data.get("mode", MODE_MAXIMUM))
        self.mode = mode if mode in _MODE_LABELS else MODE_MAXIMUM
        self.x_min_expr = str(data.get("x_min_expr", ""))
        self.x_max_expr = str(data.get("x_max_expr", ""))
        self.add_marker = bool(data.get("add_marker", False))
        self.smoothing_window = int(data.get("smoothing_window", DEFAULT_SMOOTHING_WINDOW))
        self.smoothing_polyorder = int(data.get("smoothing_polyorder", DEFAULT_SMOOTHING_POLYORDER))
        self.turning_point_prominence = float(
            data.get("turning_point_prominence", DEFAULT_TURNING_PROMINENCE)
        )
        self.fit_window = int(data.get("fit_window", DEFAULT_FIT_WINDOW))


def locate_extremum(
    x: np.ndarray,
    y: np.ndarray,
    *,
    mode: str,
    smoothing_window: int,
    smoothing_polyorder: int,
    fit_window: int,
    prominence_fraction: float = DEFAULT_TURNING_PROMINENCE,
) -> tuple[float, float]:
    """Return a smoothed, locally quadratic extremum coordinate."""
    from scipy.signal import (  # type: ignore[import-untyped]  # noqa: PLC0415
        find_peaks,
        savgol_filter,
    )

    if mode not in _MODE_LABELS:
        raise ValueError(f"unknown extremum mode {mode!r}")
    smooth_window = _valid_savgol_window(smoothing_window, len(y))
    polyorder = min(max(0, int(smoothing_polyorder)), smooth_window - 1)
    smoothed = savgol_filter(y, smooth_window, polyorder, mode="interp")
    robust_span = float(np.percentile(smoothed, 95) - np.percentile(smoothed, 5))
    span = robust_span if robust_span > 0.0 else float(np.ptp(smoothed))
    prominence = max(0.0, float(prominence_fraction)) * span
    candidates, _properties = find_peaks(
        smoothed if mode == MODE_MAXIMUM else -smoothed,
        prominence=prominence,
    )
    if not len(candidates):
        raise ValueError("No turning point satisfies the configured prominence.")
    values = smoothed[candidates]
    candidate_index = np.argmax(values) if mode == MODE_MAXIMUM else np.argmin(values)
    centre = int(candidates[candidate_index])

    window = _valid_savgol_window(fit_window, len(y))
    half = window // 2
    start = max(0, min(centre - half, len(y) - window))
    stop = start + window
    local_x = x[start:stop]
    local_y = smoothed[start:stop]
    if len(np.unique(local_x)) < 3:
        return float(x[centre]), float(smoothed[centre])
    quadratic = np.polynomial.Polynomial.fit(local_x, local_y, 2).convert()
    constant, linear, curvature = (float(value) for value in quadratic.coef)
    expected_curvature = curvature < 0.0 if mode == MODE_MAXIMUM else curvature > 0.0
    if curvature == 0.0 or not expected_curvature:
        return float(x[centre]), float(smoothed[centre])
    vertex_x = -linear / (2.0 * curvature)
    if not min(local_x) <= vertex_x <= max(local_x):
        return float(x[centre]), float(smoothed[centre])
    vertex_y = constant + linear * vertex_x + curvature * vertex_x**2
    return float(vertex_x), float(vertex_y)
