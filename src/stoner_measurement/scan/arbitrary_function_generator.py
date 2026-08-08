"""Arbitrary function scan generator and its configuration widget.

:class:`ArbitraryFunctionScanGenerator` evaluates user-supplied Python source
that defines ``scan(ix, omega)`` to generate a scan sequence.
:class:`ArbitraryFunctionScanWidget` exposes a syntax-highlighted editor and a
live preview plot.

Notes:
    User-supplied scan code is executed at runtime. Only trusted code should
    be loaded in measurement configurations.
"""

from __future__ import annotations

import ast
import json
import logging
import sys
import textwrap
from typing import Any

import numpy as np
import pyqtgraph as pg
from qtpy import QtGui
from qtpy.QtCore import QObject, QSettings, QSize, Qt
from qtpy.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.sequence_engine import SEQUENCE_LOGGER_NAME
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.scan.base import BaseScanGenerator
from stoner_measurement.ui.aspect_ratio_widget import MaximumAspectRatioWidget
from stoner_measurement.ui.editor_widget import EditorWidget
from stoner_measurement.ui.widgets import SISpinBox

_MAX_NUM_POINTS = 10_000
_PRESET_ICON_SIZE = QSize(54, 36)
_PRESET_BUTTON_SIZE = QSize(64, 44)
_PRESET_SETTINGS_PREFIX = "scan/arbitrary_function/user_preset_"
_DEFAULT_SCAN_CODE = textwrap.dedent("""\
    def scan(ix, omega):
        \"\"\"Example arbitrary scan: one sine period over the scan length.\"\"\"
        return np.sin(ix * omega)
    """)
_FIXED_PRESET_CODE = (
    "def scan(ix, omega):\n"
    '    """Example arbitrary scan: one sine period over the scan length."""\n'
    "    t=ix*omega\n"
    "    max_field=3\n"
    "    return max_field*np.sin(10*t)*(1-np.exp(-t**2/10))\n"
)
_FORBIDDEN_AST_NODES: tuple[type[ast.AST], ...] = (
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.Await,
    ast.ClassDef,
    ast.Global,
    ast.Lambda,
    ast.Nonlocal,
)


def _preset_settings() -> QSettings:
    """Return the persistent application store used for user function presets."""
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "University of Leeds",
        "Stoner Measurement",
    )


class _ArbitraryPresetButton(QPushButton):
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


class ArbitraryFunctionScanGenerator(BaseScanGenerator):
    """Scan generator that evaluates a user-defined ``scan(ix, omega)`` function.

    The execution namespace provides:

    * Python built-in functions (same set as the ``curve_fit`` plugin — i.e.
      the full :mod:`builtins` module).
    * ``np`` / ``numpy`` — NumPy.
    * ``log`` — the sequence-engine :class:`logging.Logger` (name
      ``"stoner_measurement.sequence"``).  Use ``log.debug(...)``,
      ``log.info(...)``, etc. to emit messages to the sequence log viewer.

    Notes:
        The generator executes user code with access to full Python built-ins,
        matching the behaviour of the ``curve_fit`` transform plugin.  This
        means functions like ``open()``, ``eval()``, and ``__import__()`` are
        available.  Only load configurations from trusted sources; do not run
        untrusted scan code in a production environment.
    """

    def __init__(
        self,
        *,
        num_points: int = 100,
        code: str = _DEFAULT_SCAN_CODE,
        parent: QObject | None = None,
    ) -> None:
        """Initialise the arbitrary-function scan generator."""
        super().__init__(parent)
        self._num_points = max(2, int(num_points))
        self._code = str(code)
        self._syntax_error_line: int | None = None
        self._syntax_error_message: str = ""
        self._update_syntax_state(self._code)

    @property
    def num_points(self) -> int:
        """Number of points in the sequence."""
        return self._num_points

    @num_points.setter
    def num_points(self, value: int) -> None:
        self._num_points = max(2, int(value))
        self._invalidate_cache()

    @property
    def code(self) -> str:
        """User-defined Python code containing ``scan(ix, omega)``."""
        return self._code

    @code.setter
    def code(self, value: str) -> None:
        self._code = str(value)
        self._update_syntax_state(self._code)
        self._invalidate_cache()

    @property
    def syntax_error_line(self) -> int | None:
        """1-based syntax error line number, if present."""
        return self._syntax_error_line

    @property
    def syntax_error_message(self) -> str:
        """Latest syntax error message, or an empty string."""
        return self._syntax_error_message

    def _update_syntax_state(self, code: str) -> None:
        """Update stored syntax error state for *code*."""
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            self._syntax_error_line = exc.lineno
            self._syntax_error_message = str(exc)
            return
        validation_error = self._validate_code_tree(tree)
        if validation_error is None:
            self._syntax_error_line = None
            self._syntax_error_message = ""
            return
        self._syntax_error_line, self._syntax_error_message = validation_error

    def _validate_code_tree(self, tree: ast.Module) -> tuple[int | None, str] | None:
        """Validate AST safety and required function shape."""
        for node in ast.walk(tree):
            if isinstance(node, _FORBIDDEN_AST_NODES):
                return getattr(node, "lineno", None), (
                    f"Unsupported statement in scan code: {type(node).__name__}."
                )
        scan_functions = [
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "scan"
        ]
        if len(scan_functions) != 1:
            return 1, "Code must define exactly one function named scan(ix, omega)."
        scan_function = scan_functions[0]
        if len(scan_function.args.args) != 2:
            return (
                getattr(scan_function, "lineno", None),
                "scan must accept exactly two arguments: ix and omega.",
            )
        arg_names = [arg.arg for arg in scan_function.args.args]
        if arg_names != ["ix", "omega"]:
            return (
                getattr(scan_function, "lineno", None),
                "scan arguments must be named ix and omega.",
            )
        return None

    def _compile_scan_function(self):
        """Compile and return the user-defined scan function, if available."""
        tree = ast.parse(self._code)
        validation_error = self._validate_code_tree(tree)
        if validation_error is not None:
            line, message = validation_error
            raise ValueError(f"{message} (line {line})")
        sequence_logger = logging.getLogger(SEQUENCE_LOGGER_NAME)
        if sequence_logger.level == logging.NOTSET:
            sequence_logger.setLevel(logging.INFO)
        namespace: dict[str, Any] = {
            "__builtins__": __builtins__,
            "np": np,
            "numpy": np,
            "log": sequence_logger,
        }
        # pylint: disable=exec-used
        compiled_code = compile(self._code, "<scan_code>", "exec")
        # Full builtins are intentional and match the curve_fit plugin contract.
        exec(compiled_code, namespace)  # noqa: S102
        scan = namespace.get("scan")
        return scan if callable(scan) else None

    def _report_scan_exception(self, context: str, exc: Exception) -> None:
        """Report scan-function execution failures to logs and stderr.

        Args:
            context (str):
                Human-readable context describing where evaluation failed.
            exc (Exception):
                Exception instance raised by compile/evaluation logic.
        """
        logger = logging.getLogger(SEQUENCE_LOGGER_NAME)
        logger.exception(context)
        print(f"{context}: {exc}", file=sys.stderr)

    def generate(self) -> np.ndarray:
        """Compute the sequence by evaluating ``scan(ix, omega)``."""
        try:
            scan_function = self._compile_scan_function()
        except Exception as exc:
            self._report_scan_exception("Failed to compile arbitrary scan function", exc)
            return np.full(self._num_points, np.nan, dtype=float)
        if scan_function is None:
            return np.full(self._num_points, np.nan, dtype=float)

        omega = (2.0 * np.pi) / float(self._num_points)
        values = np.empty(self._num_points, dtype=float)
        for ix in range(self._num_points):
            try:
                values[ix] = float(scan_function(ix, omega))
            except Exception as exc:
                self._report_scan_exception(
                    f"Error evaluating arbitrary scan function at ix={ix}", exc
                )
                values[ix] = np.nan
        return values

    def measure_flags(self) -> np.ndarray:
        """Return per-point measure flags (all ``True``)."""
        return np.ones(self._num_points, dtype=bool)

    def _representation_details(self) -> str:
        """Return the function signature, validation state, and point count."""
        status = "valid" if self._syntax_error_line is None else "invalid"
        return f"scan(ix, omega), {status}, {self._num_points} points"

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return an :class:`ArbitraryFunctionScanWidget` configured for this generator."""
        return ArbitraryFunctionScanWidget(generator=self, parent=parent)

    def to_json(self) -> dict:
        """Serialise this generator's configuration."""
        return {
            "type": "ArbitraryFunctionScanGenerator",
            "num_points": self._num_points,
            "code": self._code,
            "units": self._units,
        }

    @classmethod
    def _from_json_data(cls, data: dict, parent=None) -> ArbitraryFunctionScanGenerator:
        """Reconstruct an :class:`ArbitraryFunctionScanGenerator` from serialised *data*."""
        instance = cls(
            num_points=int(data.get("num_points", 100)),
            code=str(data.get("code", _DEFAULT_SCAN_CODE)),
            parent=parent,
        )
        instance.units = str(data.get("units", ""))
        return instance


class ArbitraryFunctionScanWidget(QWidget):
    """Configuration and live-preview widget for :class:`ArbitraryFunctionScanGenerator`."""

    def __init__(
        self,
        generator: ArbitraryFunctionScanGenerator,
        parent: QWidget | None = None,
    ) -> None:
        """Initialise the widget and bind it to *generator*."""
        super().__init__(parent)
        self._generator = generator
        self._build_ui()
        self._connect_signals()
        self._refresh_plot()

    def _build_ui(self) -> None:
        """Build controls, editor, and preview plot."""
        root_layout = QVBoxLayout(self)

        controls_box = QGroupBox("Parameters")
        controls_form = QFormLayout(controls_box)
        self._points_spin = SISpinBox(int=True)
        self._points_spin.setOpts(bounds=(2, _MAX_NUM_POINTS))
        self._points_spin.setValue(self._generator.num_points)
        controls_form.addRow("Points:", self._points_spin)
        root_layout.addWidget(controls_box)

        self._editor = EditorWidget(self)
        self._editor.set_text(self._generator.code)
        editor_frame = 2 * self._editor.frameWidth()
        editor_margins = self._editor.contentsMargins()
        five_lines = 5 * self._editor.fontMetrics().lineSpacing()
        self._editor.setMinimumHeight(
            five_lines + editor_frame + editor_margins.top() + editor_margins.bottom()
        )
        if self._generator.syntax_error_line is not None and self._generator.syntax_error_message:
            self._editor.set_syntax_error(
                self._generator.syntax_error_line,
                self._generator.syntax_error_message,
            )
        namespace_label = QLabel(
            "<i>Runtime namespace includes Python built-ins, "
            "<code>numpy</code> as <code>np</code> and <code>numpy</code>, "
            "and <code>log</code> for sequence log messages.</i>"
        )
        namespace_label.setWordWrap(True)
        root_layout.addWidget(namespace_label)
        root_layout.addWidget(self._editor)

        # --- Fixed and user presets ---
        preset_layout = QHBoxLayout()
        preset_layout.setContentsMargins(0, 0, 0, 0)
        self._preset_buttons: list[_ArbitraryPresetButton] = []
        self._user_preset_buttons: dict[int, _ArbitraryPresetButton] = {}

        fixed_button = _ArbitraryPresetButton()
        fixed_button.setIcon(self._fixed_preset_icon())
        fixed_button.setIconSize(_PRESET_ICON_SIZE)
        fixed_button.setToolTip("Apply damped oscillation example (1000 points)")
        fixed_button.clicked.connect(lambda: self._apply_preset(_FIXED_PRESET_CODE, 1000))
        self._add_preset_button(preset_layout, fixed_button)

        for slot in range(1, 6):
            button = _ArbitraryPresetButton(str(slot))
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

    def _add_preset_button(
        self,
        layout: QHBoxLayout,
        button: _ArbitraryPresetButton,
    ) -> None:
        """Add one consistently sized button to the preset row."""
        button.setFixedSize(_PRESET_BUTTON_SIZE)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(button)
        self._preset_buttons.append(button)

    @staticmethod
    def _fixed_preset_icon() -> QtGui.QIcon:
        """Render a clear five-oscillation version of the fixed waveform."""
        t_values = np.linspace(0.0, 2.0 * np.pi, 1000)
        values = 3.0 * np.sin(5.0 * t_values) * (1.0 - np.exp(-(t_values**2) / 10.0))
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

    def _apply_preset(self, code: str, num_points: int) -> None:
        """Apply preset source and point count, then refresh editor and preview."""
        self._generator.num_points = num_points
        self._generator.code = code
        self.refresh()

    def _store_user_preset(self, slot: int) -> None:
        """Persist the current source and point count in user *slot*."""
        settings = _preset_settings()
        settings.setValue(
            f"{_PRESET_SETTINGS_PREFIX}{slot}",
            json.dumps(
                {
                    "code": self._generator.code,
                    "num_points": self._generator.num_points,
                },
                sort_keys=True,
            ),
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
            if not isinstance(preset, dict) or not {"code", "num_points"} <= preset.keys():
                return None
            return {
                "code": str(preset["code"]),
                "num_points": int(preset["num_points"]),
            }
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _scan_code_summary(code: str) -> str:
        """Summarise scan source using its docstring or first body statement."""
        try:
            tree = ast.parse(code)
            scan_function = next(
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "scan"
            )
            docstring = ast.get_docstring(scan_function)
            if docstring:
                summary = docstring.splitlines()[0].strip()
            elif scan_function.body:
                summary = ast.unparse(scan_function.body[0])
            else:
                summary = "empty scan function"
        except (SyntaxError, StopIteration):
            summary = next(
                (line.strip() for line in code.splitlines() if line.strip()),
                "empty scan function",
            )
        summary = " ".join(summary.split())
        return f"{summary[:77]}..." if len(summary) > 80 else summary

    def _update_user_preset_tooltip(self, slot: int) -> None:
        """Show storage instructions or a summary for user *slot*."""
        button = self._user_preset_buttons[slot]
        preset = self._load_user_preset(slot)
        if preset is None:
            button.setToolTip(f"User preset {slot}: empty; Ctrl-click to store code and points")
            return
        summary = self._scan_code_summary(str(preset["code"]))
        button.setToolTip(
            f"User preset {slot}: {int(preset['num_points'])} points; {summary}. "
            "Click to recall; Ctrl-click to replace"
        )

    def _recall_user_preset(self, slot: int) -> None:
        """Recall user *slot* when it contains valid source and point data."""
        preset = self._load_user_preset(slot)
        if preset is not None:
            self._apply_preset(str(preset["code"]), int(preset["num_points"]))

    def _connect_signals(self) -> None:
        """Wire control signals to generator updates and plot refresh."""
        self._points_spin.valueChanged.connect(self._on_points_changed)
        self._editor.textChanged.connect(self._on_code_changed)
        self._generator.values_changed.connect(self._refresh_plot)
        self._generator.current_point_changed.connect(self._on_current_point_changed)

    def _on_points_changed(self, value: int) -> None:
        """Update generator point count."""
        self._generator.num_points = value

    def _on_code_changed(self) -> None:
        """Update generator code and syntax marker from editor text."""
        self._generator.code = self._editor.text()
        if self._generator.syntax_error_line is not None and self._generator.syntax_error_message:
            self._editor.set_syntax_error(
                self._generator.syntax_error_line,
                self._generator.syntax_error_message,
            )
        else:
            self._editor.clear_syntax_error()

    def _refresh_plot(self) -> None:
        """Re-render the preview curve."""
        values = self._generator.values
        x_vals = np.arange(len(values), dtype=float)
        self._curve.setData(x_vals, values)
        self._clear_current_marker()

    def _clear_current_marker(self) -> None:
        """Clear the current-point marker from the preview."""
        self._current_marker.setData(x=np.array([], dtype=float), y=np.array([], dtype=float))

    def _on_current_point_changed(self, index: int, value: float) -> None:
        """Move the current-point marker to *(index, value)*."""
        if index < 0:
            self._clear_current_marker()
            return
        self._current_marker.setData(x=np.array([float(index)]), y=np.array([float(value)]))

    def get_generator(self) -> ArbitraryFunctionScanGenerator:
        """Return the :class:`ArbitraryFunctionScanGenerator` bound to this widget."""
        return self._generator

    def refresh(self) -> None:
        """Reload widget state from the generator."""
        self._points_spin.setValue(self._generator.num_points)
        self._editor.set_text(self._generator.code)
        if self._generator.syntax_error_line is not None and self._generator.syntax_error_message:
            self._editor.set_syntax_error(
                self._generator.syntax_error_line,
                self._generator.syntax_error_message,
            )
        else:
            self._editor.clear_syntax_error()
        self._refresh_plot()
        self.update()
