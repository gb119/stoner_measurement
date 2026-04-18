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
import logging
import textwrap
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtGui
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.sequence_engine import SEQUENCE_LOGGER_NAME
from stoner_measurement.scan.base import BaseScanGenerator
from stoner_measurement.ui.editor_widget import EditorWidget

_MAX_NUM_POINTS = 10_000
_DEFAULT_SCAN_CODE = textwrap.dedent("""\
    def scan(ix, omega):
        \"\"\"Example arbitrary scan: one sine period over the scan length.\"\"\"
        return np.sin(ix * omega)
    """)
_FORBIDDEN_AST_NODES: tuple[type[ast.AST], ...] = (
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.Await,
    ast.ClassDef,
    ast.Global,
    ast.Lambda,
    ast.Nonlocal,
)


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
                return getattr(node, "lineno", None), (f"Unsupported statement in scan code: {type(node).__name__}.")
        scan_functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "scan"]
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
        exec(
            compile(self._code, "<scan_code>", "exec"), namespace
        )  # noqa: S102 – full builtins intentional; matches curve_fit plugin contract
        scan = namespace.get("scan")
        return scan if callable(scan) else None

    def generate(self) -> np.ndarray:
        """Compute the sequence by evaluating ``scan(ix, omega)``."""
        try:
            scan_function = self._compile_scan_function()
        except Exception:
            return np.full(self._num_points, np.nan, dtype=float)
        if scan_function is None:
            return np.full(self._num_points, np.nan, dtype=float)

        omega = (2.0 * np.pi) / float(self._num_points)
        values = np.empty(self._num_points, dtype=float)
        for ix in range(self._num_points):
            try:
                values[ix] = float(scan_function(ix, omega))
            except Exception:
                values[ix] = np.nan
        return values

    def measure_flags(self) -> np.ndarray:
        """Return per-point measure flags (all ``True``)."""
        return np.ones(self._num_points, dtype=bool)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return an :class:`ArbitraryFunctionScanWidget` configured for this generator."""
        return ArbitraryFunctionScanWidget(generator=self, parent=parent)

    def to_json(self) -> dict:
        """Serialise this generator's configuration."""
        return {
            "type": "ArbitraryFunctionScanGenerator",
            "num_points": self._num_points,
            "code": self._code,
        }

    @classmethod
    def _from_json_data(cls, data: dict, parent=None) -> ArbitraryFunctionScanGenerator:
        """Reconstruct an :class:`ArbitraryFunctionScanGenerator` from serialised *data*."""
        return cls(
            num_points=int(data.get("num_points", 100)),
            code=str(data.get("code", _DEFAULT_SCAN_CODE)),
            parent=parent,
        )


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
        self._points_spin = pg.SpinBox(int=True)
        self._points_spin.setOpts(bounds=(2, _MAX_NUM_POINTS))
        self._points_spin.setValue(self._generator.num_points)
        controls_form.addRow("Points:", self._points_spin)
        root_layout.addWidget(controls_box)

        self._editor = EditorWidget(self)
        self._editor.set_text(self._generator.code)
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
        """Wire control signals to generator updates and plot refresh."""
        self._points_spin.valueChanged.connect(self._on_points_changed)
        self._editor.textChanged.connect(self._on_code_changed)
        self._generator.values_changed.connect(self._refresh_plot)

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

    def get_generator(self) -> ArbitraryFunctionScanGenerator:
        """Return the :class:`ArbitraryFunctionScanGenerator` bound to this widget."""
        return self._generator
