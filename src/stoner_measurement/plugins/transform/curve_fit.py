"""CurveFitPlugin — transform plugin that fits data to a user-defined function.

Performs scipy.optimize.curve_fit on a selected data trace using a fitting
function supplied as Python source code.  Parameter names, bounds, and initial
values are configured via the UI.  Fitted parameter values and their
uncertainties (sqrt of covariance matrix diagonal) are reported as plugin
outputs.

Notes:
    The fit-function code entered by the user is executed with Python's built-in
    :func:`exec`.  Only load and run configuration files from trusted sources.
"""

from __future__ import annotations

import ast
import functools
import logging
import math
import textwrap
from collections.abc import Callable
from contextlib import redirect_stdout
from io import StringIO
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.sequence_engine import SEQUENCE_LOGGER_NAME
from stoner_measurement.plugins.trace.base import COLUMN_ROLE_E, COLUMN_ROLE_Y, TraceData
from stoner_measurement.plugins.transform.base import TransformPlugin
from stoner_measurement.ui.editor_widget import EditorWidget

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Default fit-function source code shown in a new plugin instance
# ---------------------------------------------------------------------------

_DEFAULT_FIT_CODE = textwrap.dedent("""\
    def fit(x, a, b):
        \"\"\"Linear fit: y = a*x + b.\"\"\"
        return a * x + b


    # Optional: define p0(x, y) to compute initial parameter estimates.
    # def p0(x, y):
    #     return (1.0, 0.0)
    """)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_fit_params(code: str) -> list[str]:
    """Return parameter names from the ``fit`` function in *code*.

    Parses *code* with :mod:`ast` and locates the function definition named
    ``fit``.  Returns the names of all arguments after the first (the ``x``
    argument), preserving their source order.  Returns an empty list if no
    ``fit`` function is found or if *code* contains a syntax error.

    Args:
        code (str):
            Python source code that may contain a ``fit(x, ...)`` function.

    Returns:
        (list[str]):
            Ordered parameter names, e.g. ``["a", "b"]`` for
            ``def fit(x, a, b): ...``.

    Examples:
        >>> _parse_fit_params("def fit(x, a, b): return a*x + b")
        ['a', 'b']
        >>> _parse_fit_params("def fit(x): return x")
        []
        >>> _parse_fit_params("not valid python !!!")
        []
    """
    tree, _ = _parse_fit_tree(code)
    if tree is None:
        return []
    return _fit_param_names_from_tree(tree)


def _parse_fit_tree(code: str) -> tuple[ast.AST | None, SyntaxError | None]:
    """Parse fit source code into an AST tree.

    Args:
        code (str):
            Python source code entered for the fit function.

    Returns:
        (tuple[ast.AST | None, SyntaxError | None]):
            ``(tree, None)`` when parsing succeeds, or
            ``(None, syntax_error)`` when parsing fails.
    """
    try:
        return ast.parse(code), None
    except SyntaxError as exc:
        return None, exc


def _fit_param_names_from_tree(tree: ast.AST) -> list[str]:
    """Return parameter names from a parsed AST defining ``fit(x, ...)``.

    Args:
        tree (ast.AST):
            Parsed Python AST to inspect.

    Returns:
        (list[str]):
            Ordered parameter names after ``x`` from ``fit(x, ...)``.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "fit":
            return [arg.arg for arg in node.args.args[1:]]
    return []


def _has_p0_function(code: str) -> bool:
    """Return ``True`` if *code* defines a function named ``p0``.

    Args:
        code (str):
            Python source code to inspect.

    Returns:
        (bool):
            ``True`` if a ``def p0(...)`` statement is present and not inside
            a comment block.

    Examples:
        >>> _has_p0_function("def p0(x, y): return (1.0,)")
        True
        >>> _has_p0_function("def fit(x, a): return a * x")
        False
    """
    tree, _ = _parse_fit_tree(code)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "p0":
            return True
    return False


# ---------------------------------------------------------------------------
# Parameter table widget
# ---------------------------------------------------------------------------

_INF = float("inf")
_DEFAULT_COLUMN_OPTION = "(default)"
_NAN = float("nan")
_PARAM_TABLE_ROW_MIN = 0
_PARAM_TABLE_ROW_INITIAL = 1
_PARAM_TABLE_ROW_MAX = 2
_PARAM_TABLE_ROW_USED_INITIAL = 3
_PARAM_TABLE_ROW_FITTED = 4
_PARAM_TABLE_ROW_LABELS = ["Min", "Initial", "Max", "Initial used", "Fitted"]

# Mapping from SI tier (power-of-1000 exponent) to SI prefix symbol.
_SI_PREFIXES: dict[int, str] = {
    -8: "y", -7: "z", -6: "a", -5: "f", -4: "p",
    -3: "n", -2: "µ", -1: "m", 0: "",
    1: "k", 2: "M", 3: "G", 4: "T", 5: "P",
    6: "E", 7: "Z", 8: "Y",
}


def _si_scale_and_prefix(value: float) -> tuple[float, str]:
    """Return ``(scale, si_prefix)`` so that ``abs(value) / scale`` is in ``[0.1, 1000)``.

    The scale is a power of 1000 (10^(3*tier)).  Returns ``(1.0, "")`` when *value*
    is zero.  When *value* falls outside the range covered by the available SI prefixes
    (yocto–yotta), the tier is clamped and the mantissa may fall outside ``[0.1, 1000)``.

    Args:
        value (float):
            The physical quantity to be scaled.

    Returns:
        (float):
            Scale factor — divide *value* by this to obtain the display mantissa.
        (str):
            SI prefix symbol corresponding to the scale, e.g. ``"k"``, ``"µ"``,
            or ``""`` for unity scale.

    Examples:
        >>> _si_scale_and_prefix(1234.0)
        (1000.0, 'k')
        >>> _si_scale_and_prefix(0.00456)
        (0.001, 'm')
        >>> _si_scale_and_prefix(0.5)
        (1.0, '')
        >>> _si_scale_and_prefix(0.0)
        (1.0, '')
    """
    abs_val = abs(value)
    if abs_val == 0.0:
        return 1.0, ""
    tier = int(math.floor((math.log10(abs_val) + 1) / 3))
    tier = max(-8, min(8, tier))
    scale = 10.0 ** (3 * tier)
    return scale, _SI_PREFIXES.get(tier, "")


def _format_value_with_uncertainty(value: Any, uncertainty: Any) -> str:
    """Format a fitted value as ``value ± uncertainty [SI prefix]``.

    An SI prefix is chosen so that the displayed value mantissa falls in the
    range ``[0.1, 1000)``.  Both the value and the uncertainty are divided by the
    same SI scale factor before formatting.  The uncertainty is rounded to one
    significant figure and the value is rounded to the same decimal precision.

    Args:
        value (Any):
            Best-fit parameter value.
        uncertainty (Any):
            One-sigma uncertainty for the parameter value.

    Returns:
        (str):
            Formatted text such as ``"1.2 ± 0.2 k"`` or ``"12.3 ± 0.7"``,
            or an empty string when the inputs are not finite.

    Examples:
        >>> _format_value_with_uncertainty(12.345, 0.67)
        '12.3 ± 0.7'
        >>> _format_value_with_uncertainty(1234.0, 230.0)
        '1.2 ± 0.2 k'
        >>> _format_value_with_uncertainty(0.00456, 0.00034)
        '4.6 ± 0.3 m'
    """
    try:
        value_float = float(value)
        uncertainty_float = float(uncertainty)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(value_float) or not math.isfinite(uncertainty_float) or uncertainty_float <= 0.0:
        return ""

    scale, si_prefix = _si_scale_and_prefix(value_float)
    scaled_value = value_float / scale
    scaled_uncertainty = uncertainty_float / scale

    rounded_uncertainty = float(f"{scaled_uncertainty:.1g}")
    if rounded_uncertainty <= 0.0 or not math.isfinite(rounded_uncertainty):
        return ""

    exponent = math.floor(math.log10(abs(scaled_uncertainty)))
    decimals = -exponent
    rounded_value = round(scaled_value, decimals)

    if decimals > 0:
        value_text = f"{rounded_value:.{decimals}f}"
        uncertainty_text = f"{rounded_uncertainty:.{decimals}f}"
    else:
        value_text = f"{rounded_value:.0f}"
        uncertainty_text = f"{rounded_uncertainty:.0f}"

    if si_prefix:
        return f"{value_text} ± {uncertainty_text} {si_prefix}"
    return f"{value_text} ± {uncertainty_text}"


def _format_scalar_for_table(value: Any) -> str:
    """Format a scalar value for display in the parameter table.

    Args:
        value (Any):
            Value to format for display.

    Returns:
        (str):
            Finite numeric values formatted with up to 12 significant figures,
            or an empty string for non-numeric and non-finite inputs.

    Examples:
        >>> _format_scalar_for_table(12.345)
        '12.345'
        >>> _format_scalar_for_table(float("nan"))
        ''
    """
    try:
        value_float = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(value_float):
        return ""
    return f"{value_float:.12g}"


class _ParamTableWidget(QWidget):
    """Table widget for configuring per-parameter bounds and initial values.

    Displays one column per parameter detected in the fit function. The rows
    show the minimum bound, editable initial value, maximum bound, the initial
    values currently used by the fit, and the fitted value with uncertainty.

    Args:
        parent (QWidget | None):
            Optional Qt parent widget.

    Attributes:
        param_settings (dict[str, dict[str, float | None]]):
            Mapping of parameter name → ``{"min": …, "initial": …, "max": …}``.
            ``None`` means the value was not specified by the user.
        settings_changed (pyqtSignal):
            Emitted whenever the user edits a cell in the table.
    """

    settings_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialise the parameter table."""
        super().__init__(parent)
        self._build_ui()
        self.param_settings: dict[str, dict[str, float | None]] = {}
        self._fitted_text_by_param: dict[str, str] = {}
        self._used_initial_text_by_param: dict[str, str] = {}
        self._parameter_names: list[str] = []

    def _build_ui(self) -> None:
        """Build the table widget and surrounding layout."""
        layout = QVBoxLayout(self)

        self._table = QTableWidget(len(_PARAM_TABLE_ROW_LABELS), 0, self)
        self._table.setVerticalHeaderLabels(_PARAM_TABLE_ROW_LABELS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setToolTip(
            "Leave Min/Initial/Max blank to use defaults.\n"
            "Min/Max constrain the curve fit; Initial provides manual starting values."
        )
        self._table.itemChanged.connect(self.settings_changed)
        layout.addWidget(self._table)

        note = QLabel(
            "<i>Blank fields use scipy defaults (unbounded, p0=1).  "
            "If a <code>p0</code> function is defined in the fit code, "
            "the editable Initial row is ignored and the Initial used row "
            "shows the values returned by <code>p0(x, y)</code>.</i>",
            self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_parameters(self, param_names: list[str]) -> None:
        """Repopulate the table for the given parameter names.

        Existing values for parameters that are still present are preserved;
        columns for removed parameters are discarded; new columns are added with
        blank cells.

        Args:
            param_names (list[str]):
                Ordered parameter names as extracted from the fit function.
        """
        old_settings = self._read_table()
        self._parameter_names = list(param_names)

        blocked = self._table.blockSignals(True)
        try:
            self._table.setColumnCount(len(param_names))
            self._table.setHorizontalHeaderLabels(param_names)
            for col, name in enumerate(param_names):
                prev = old_settings.get(name, {})
                for row, key in (
                    (_PARAM_TABLE_ROW_MIN, "min"),
                    (_PARAM_TABLE_ROW_INITIAL, "initial"),
                    (_PARAM_TABLE_ROW_MAX, "max"),
                ):
                    val = prev.get(key)
                    text = "" if val is None else str(val)
                    self._table.setItem(row, col, QTableWidgetItem(text))
                self._set_read_only_cell(
                    _PARAM_TABLE_ROW_USED_INITIAL,
                    col,
                    self._used_initial_text_by_param.get(name, ""),
                )
                self._set_read_only_cell(_PARAM_TABLE_ROW_FITTED, col, self._fitted_text_by_param.get(name, ""))
        finally:
            self._table.blockSignals(blocked)

    def read_settings(self) -> dict[str, dict[str, float | None]]:
        """Read current table values and return a settings dict.

        Returns:
            (dict[str, dict[str, float | None]]):
                ``{param_name: {"min": …, "initial": …, "max": …}}``
                where ``None`` means the cell was blank.
        """
        self.param_settings = self._read_table()
        return self.param_settings

    def load_settings(self, settings: dict[str, dict[str, float | None]], param_names: list[str]) -> None:
        """Populate the table from *settings* for the given *param_names*.

        Args:
            settings (dict[str, dict[str, float | None]]):
                Settings dict as returned by :meth:`read_settings`.
            param_names (list[str]):
                Ordered parameter names to show.
        """
        self.param_settings = settings
        self._fill_table(param_names, settings)

    def update_fitted_results(self, results: dict[str, Any]) -> None:
        """Update the fitted-value row from a transform result dict.

        Args:
            results (dict[str, Any]):
                Transform output mapping containing ``{name}`` and
                ``{name}_err`` entries for each parameter.
        """
        fitted_text_by_param: dict[str, str] = {}
        for name in self._iter_parameter_names():
            fitted_text_by_param[name] = _format_value_with_uncertainty(
                results.get(name),
                results.get(f"{name}_err"),
            )
        self._fitted_text_by_param = fitted_text_by_param
        self._apply_fitted_values()

    def update_used_initial_values(self, values: dict[str, Any]) -> None:
        """Update the row showing the initial values currently used by the fit."""
        self._used_initial_text_by_param = {
            name: _format_scalar_for_table(values.get(name)) for name in self._iter_parameter_names()
        }
        self._set_row_label(_PARAM_TABLE_ROW_USED_INITIAL, "Initial used")
        self._apply_used_initial_values()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_table(self) -> dict[str, dict[str, float | None]]:
        """Read values from the table and return a settings dict."""
        result: dict[str, dict[str, float | None]] = {}
        for col, name in enumerate(self._iter_parameter_names()):
            column_settings: dict[str, float | None] = {}
            for row, key in (
                (_PARAM_TABLE_ROW_MIN, "min"),
                (_PARAM_TABLE_ROW_INITIAL, "initial"),
                (_PARAM_TABLE_ROW_MAX, "max"),
            ):
                item = self._table.item(row, col)
                text = item.text().strip() if item else ""
                if text:
                    try:
                        column_settings[key] = float(text)
                    except ValueError:
                        column_settings[key] = None
                else:
                    column_settings[key] = None
            result[name] = column_settings
        return result

    def _fill_table(
        self,
        param_names: list[str],
        settings: dict[str, dict[str, float | None]],
    ) -> None:
        """Fill the table from *param_names* and *settings*."""
        self._parameter_names = list(param_names)
        blocked = self._table.blockSignals(True)
        try:
            self._table.setColumnCount(len(param_names))
            self._table.setHorizontalHeaderLabels(param_names)
            for col, name in enumerate(param_names):
                vals = settings.get(name, {})
                for row, key in (
                    (_PARAM_TABLE_ROW_MIN, "min"),
                    (_PARAM_TABLE_ROW_INITIAL, "initial"),
                    (_PARAM_TABLE_ROW_MAX, "max"),
                ):
                    val = vals.get(key)
                    text = "" if val is None else str(val)
                    self._table.setItem(row, col, QTableWidgetItem(text))
                self._set_read_only_cell(
                    _PARAM_TABLE_ROW_USED_INITIAL,
                    col,
                    self._used_initial_text_by_param.get(name, ""),
                )
                self._set_read_only_cell(_PARAM_TABLE_ROW_FITTED, col, self._fitted_text_by_param.get(name, ""))
        finally:
            self._table.blockSignals(blocked)

    def _iter_parameter_names(self):
        """Yield parameter names in table column order."""
        yield from self._parameter_names

    def _apply_used_initial_values(self) -> None:
        """Apply cached used-initial text to the table."""
        blocked = self._table.blockSignals(True)
        try:
            for col, name in enumerate(self._iter_parameter_names()):
                self._set_read_only_cell(
                    _PARAM_TABLE_ROW_USED_INITIAL,
                    col,
                    self._used_initial_text_by_param.get(name, ""),
                )
        finally:
            self._table.blockSignals(blocked)

    def _apply_fitted_values(self) -> None:
        """Apply cached fitted-value text to the table."""
        blocked = self._table.blockSignals(True)
        try:
            for col, name in enumerate(self._iter_parameter_names()):
                self._set_read_only_cell(_PARAM_TABLE_ROW_FITTED, col, self._fitted_text_by_param.get(name, ""))
        finally:
            self._table.blockSignals(blocked)

    def _set_row_label(self, row: int, text: str) -> None:
        """Set the vertical header label for *row*."""
        header_item = self._table.verticalHeaderItem(row)
        if header_item is None:
            header_item = QTableWidgetItem(text)
            self._table.setVerticalHeaderItem(row, header_item)
        else:
            header_item.setText(text)

    def _set_read_only_cell(self, row: int, col: int, text: str) -> None:
        """Set a read-only table cell."""
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, col, item)


# ---------------------------------------------------------------------------
# Main plugin
# ---------------------------------------------------------------------------


_INITIAL_TRACE_KEY = "initial_fit"
_BEST_FIT_TRACE_KEY = "best_fit"


class CurveFitPlugin(TransformPlugin):
    """Curve-fitting transform plugin using scipy.optimize.curve_fit.

    Fits a user-defined function to a data trace selected from the sequence
    engine.  The plugin provides three configuration tabs:

    * **Data** — contains the instance-name editor at the top, followed by
      data-selection controls.  In *simple mode* choose a single trace; the
      ``x`` and ``y`` arrays are taken from the
      :class:`~stoner_measurement.plugins.trace.TraceData` object.  In
      *advanced mode* supply independent Python expressions for ``x``, ``y``,
      and an optional ``y``-uncertainty array (used as ``sigma``).
    * **Fit Function** — write the fitting function as Python source code.
      The function must be named ``fit`` and its first argument must be the
      independent variable ``x``; subsequent arguments become the free
      parameters.  An optional ``p0(x, y)`` function may also be defined to
      compute initial parameter estimates; if absent the initial values are
      taken from the Parameters table.
    * **Parameters** — a table with one row per detected parameter.  Each row
      allows an optional minimum bound, initial value, and maximum bound.
      Two optional trace outputs can be enabled:

      * *Initial fit trace* — the fitting function evaluated at the x data
        using the initial parameter estimates (``p0``).
      * *Best fit trace* — the fitting function evaluated at the x data using
        the optimal parameters found by the fit.

    Attributes:
        trace_key (str):
            Key in the ``_traces`` catalogue used in simple mode.
        advanced_mode (bool):
            When ``True``, ``x_expr``, ``y_expr``, and ``y_error_expr`` are
            used to select data instead of ``trace_key``.
        x_expr (str):
            Python expression for the x data array (advanced mode).
        y_expr (str):
            Python expression for the y data array (advanced mode).
        y_error_expr (str):
            Python expression for the y-uncertainty array (advanced mode).
            When non-empty the array is passed as ``sigma`` with
            ``absolute_sigma=True``.
        fit_code (str):
            Python source code defining the ``fit(x, …)`` function and
            optionally a ``p0(x, y)`` function.
        param_names (list[str]):
            Parameter names extracted from the ``fit`` function signature.
            Updated automatically whenever :attr:`fit_code` changes.
        param_settings (dict[str, dict[str, float | None]]):
            Per-parameter bounds and initial value.  Each entry maps a
            parameter name to ``{"min": …, "initial": …, "max": …}`` where
            ``None`` means *unconstrained / auto*.
        show_initial_trace (bool):
            When ``True``, the transform stores an ``"initial_fit"`` trace
            in :attr:`data` containing the fitting function evaluated at the
            x data with the initial parameter estimates.
        show_best_fit_trace (bool):
            When ``True``, the transform stores a ``"best_fit"`` trace in
            :attr:`data` containing the fitting function evaluated at the x
            data with the optimal parameters.
    """

    def __init__(self, parent=None) -> None:
        """Initialise the curve-fit plugin with default configuration."""
        super().__init__(parent)
        # Data selection (mirrors PlotTraceCommand)
        self.trace_key: str = ""
        self.column_key: str = ""
        self.advanced_mode: bool = False
        self.x_expr: str = ""
        self.y_expr: str = ""
        self.y_error_expr: str = ""
        # Fit function source code
        self.fit_code: str = _DEFAULT_FIT_CODE
        # Detected parameter names (derived from fit_code)
        self.param_names: list[str] = _parse_fit_params(self.fit_code)
        # Per-parameter bounds/initial settings
        self.param_settings: dict[str, dict[str, float | None]] = {}
        # Optional trace outputs
        self.show_initial_trace: bool = False
        self.show_best_fit_trace: bool = False
        # Latest syntax error state for fit_code (for UI feedback).
        self.fit_code_syntax_error_line: int | None = None
        self.fit_code_syntax_error_message: str = ""
        self._param_table_widget: _ParamTableWidget | None = None
        self._param_table_preview_timer = QTimer(self)
        self._param_table_preview_timer.setSingleShot(True)
        self._param_table_preview_timer.timeout.connect(self._refresh_param_table_preview)

    # ------------------------------------------------------------------
    # BasePlugin / TransformPlugin abstract interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Unique identifier for this plugin.

        Returns:
            (str):
                ``"Curve Fit"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> CurveFitPlugin().name
            'Curve Fit'
        """
        return "Curve Fit"

    @property
    def required_inputs(self) -> list[str]:
        """Required input keys.

        The plugin retrieves its own data from the engine namespace using
        the configured expressions, so no external inputs are required.

        Returns:
            (list[str]):
                Always an empty list.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> CurveFitPlugin().required_inputs
            []
        """
        return []

    @property
    def output_names(self) -> list[str]:
        """Names of all outputs produced by this plugin.

        One value and one uncertainty output are reported for each detected
        fit parameter.  For a fit function ``fit(x, a, b)`` the base output
        names are ``["a", "a_err", "b", "b_err"]``.  Optional trace outputs
        ``"initial_fit"`` and ``"best_fit"`` are appended when
        :attr:`show_initial_trace` and :attr:`show_best_fit_trace` are enabled.

        Returns:
            (list[str]):
                Alternating ``"{param}"`` and ``"{param}_err"`` names, followed
                by any enabled trace output names.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> p = CurveFitPlugin()
            >>> p.param_names = ["a", "b"]
            >>> p.output_names
            ['a', 'a_err', 'b', 'b_err']
            >>> p.show_initial_trace = True
            >>> p.show_best_fit_trace = True
            >>> p.output_names
            ['a', 'a_err', 'b', 'b_err', 'initial_fit', 'best_fit']
        """
        names: list[str] = []
        for pname in self.param_names:
            names.append(pname)
            names.append(f"{pname}_err")
        if self.show_initial_trace:
            names.append(_INITIAL_TRACE_KEY)
        if self.show_best_fit_trace:
            names.append(_BEST_FIT_TRACE_KEY)
        return names

    @property
    def output_trace_names(self) -> list[str]:
        """Subset of :attr:`output_names` that are (x, y) trace arrays.

        Returns the keys for any enabled optional trace outputs.

        Returns:
            (list[str]):
                ``["initial_fit"]`` if :attr:`show_initial_trace` is enabled,
                ``["best_fit"]`` if :attr:`show_best_fit_trace` is enabled,
                or both, or an empty list if neither is enabled.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> p = CurveFitPlugin()
            >>> p.output_trace_names
            []
            >>> p.show_initial_trace = True
            >>> p.output_trace_names
            ['initial_fit']
            >>> p.show_best_fit_trace = True
            >>> p.output_trace_names
            ['initial_fit', 'best_fit']
        """
        traces: list[str] = []
        if self.show_initial_trace:
            traces.append(_INITIAL_TRACE_KEY)
        if self.show_best_fit_trace:
            traces.append(_BEST_FIT_TRACE_KEY)
        return traces

    @property
    def output_value_names(self) -> list[str]:
        """Subset of :attr:`output_names` that are scalar values.

        Returns the parameter value and uncertainty names, explicitly excluding
        any trace output names.

        Returns:
            (list[str]):
                Alternating ``"{param}"`` and ``"{param}_err"`` names.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> p = CurveFitPlugin()
            >>> p.param_names = ["a", "b"]
            >>> p.show_initial_trace = True
            >>> p.show_best_fit_trace = True
            >>> p.output_value_names
            ['a', 'a_err', 'b', 'b_err']
        """
        names: list[str] = []
        for pname in self.param_names:
            names.append(pname)
            names.append(f"{pname}_err")
        return names

    # ------------------------------------------------------------------
    # Transform implementation
    # ------------------------------------------------------------------

    def transform(self, data: dict[str, Any]) -> dict[str, Any]:
        """Fit the selected data and return optimal parameters and uncertainties.

        Retrieves x/y (and optional y-uncertainty) data from the engine
        namespace, compiles the user-supplied fit function, and calls
        ``scipy.optimize.curve_fit``.  Returns a dict whose keys are the
        parameter names and their ``_err`` counterparts.

        If curve fitting fails (e.g. convergence failure, missing scipy) the
        method logs an error and returns a dict of ``NaN`` values so that
        downstream code can still run.

        Args:
            data (dict[str, Any]):
                Ignored; the plugin retrieves its own data from the engine
                namespace.

        Returns:
            (dict[str, Any]):
                Mapping of parameter name → optimal value and
                ``"{name}_err"`` → 1-sigma uncertainty.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> import numpy as np
            >>> engine = SequenceEngine()
            >>> plugin = CurveFitPlugin()
            >>> engine.add_plugin("curve_fit", plugin)
            >>> engine._namespace["_xdata"] = np.linspace(0, 1, 20)
            >>> engine._namespace["_ydata"] = 2.0 * np.linspace(0, 1, 20) + 0.5
            >>> plugin.advanced_mode = True
            >>> plugin.x_expr = "_xdata"
            >>> plugin.y_expr = "_ydata"
            >>> plugin.fit_code = "def fit(x, a, b): return a * x + b"
            >>> plugin.param_names = ["a", "b"]
            >>> result = plugin.transform({})
            >>> abs(result["a"] - 2.0) < 1e-6
            True
            >>> abs(result["b"] - 0.5) < 1e-6
            True
            >>> engine.shutdown()
        """
        nan_result = {n: _NAN for n in self.output_value_names}

        # ---- 1. Retrieve x / y / sigma from the engine namespace ---------
        try:
            x_data, y_data, sigma, y_col_name, source_names, source_units = self._get_data_arrays()
        except Exception as exc:
            self.log.error("CurveFit: failed to retrieve data — %s", exc)
            return nan_result

        if x_data is None or y_data is None:
            self.log.warning("CurveFit: x or y data is None — skipping fit.")
            return nan_result

        x_arr = np.asarray(x_data, dtype=float)
        y_arr = np.asarray(y_data, dtype=float)
        sigma_arr = np.asarray(sigma, dtype=float) if sigma is not None else None

        # ---- 2. Compile the user code ------------------------------------
        try:
            fit_func, p0_func = self._compile_fit_code()
        except Exception as exc:
            self.log.error("CurveFit: error compiling fit code — %s", exc)
            return nan_result

        if fit_func is None:
            self.log.error("CurveFit: no function named 'fit' found in fit code.")
            return nan_result

        fit_func = self._wrap_user_stdout_callable(fit_func)
        p0_func = self._wrap_user_stdout_callable(p0_func)

        # ---- 3. Build p0 and bounds --------------------------------------
        p0 = self._build_p0(p0_func, x_arr, y_arr)
        bounds = self._build_bounds()

        # ---- 4. Optionally compute the initial-parameter trace -----------
        result: dict[str, Any] = {}
        if self.show_initial_trace:
            initial_trace = self._compute_initial_trace(
                fit_func, x_arr, p0,
                y_col_name=y_col_name,
                source_names=source_names,
                source_units=source_units,
            )
            if initial_trace is not None:
                result[_INITIAL_TRACE_KEY] = initial_trace

        # ---- 5. Run curve_fit --------------------------------------------
        fit_result = self._run_curve_fit(fit_func, x_arr, y_arr, sigma_arr, p0, bounds)
        if fit_result is None:
            return nan_result
        popt, pcov = fit_result

        # ---- 6. Build scalar result dict ---------------------------------
        result.update(self._build_scalar_results(popt, pcov))

        # ---- 7. Optionally compute the best-fit trace --------------------
        if self.show_best_fit_trace:
            best_fit_trace = self._compute_best_fit_trace(
                fit_func, x_arr, popt,
                y_col_name=y_col_name,
                source_names=source_names,
                source_units=source_units,
            )
            if best_fit_trace is not None:
                result[_BEST_FIT_TRACE_KEY] = best_fit_trace

        return result

    def _compute_initial_trace(
        self,
        fit_func,
        x_arr: np.ndarray,
        p0,
        *,
        y_col_name: str = "y",
        source_names: dict[str, str] | None = None,
        source_units: dict[str, str] | None = None,
    ) -> TraceData | None:
        """Evaluate the fit function with initial parameters to produce a trace.

        Falls back to ``1.0`` for each parameter when *p0* is ``None`` so that
        the trace can still be drawn even when no initial values are configured.

        Args:
            fit_func:
                Compiled ``fit(x, …)`` callable.
            x_arr (np.ndarray):
                x data array.
            p0:
                Initial parameter values, or ``None``.

        Keyword Parameters:
            y_col_name (str):
                Column name to use in the output DataFrame.  Defaults to ``"y"``.
            source_names (dict[str, str] | None):
                Human-readable name mapping from the source trace.  Used to
                propagate axis labels to the output TraceData.
            source_units (dict[str, str] | None):
                Physical unit mapping from the source trace.  Used to
                propagate units to the output TraceData.

        Returns:
            (TraceData | None):
                Trace evaluated at the initial parameters, or ``None`` on
                failure.
        """
        p0_vals = p0 if p0 is not None else [1.0] * len(self.param_names)
        try:
            y_initial = fit_func(x_arr, *p0_vals)
            y_arr = np.asarray(y_initial, dtype=float)
            names: dict[str, str] = dict(source_names or {})
            names.setdefault("x", "x")
            names.setdefault(y_col_name, y_col_name)
            units: dict[str, str] = dict(source_units or {})
            units.setdefault("x", "")
            units.setdefault(y_col_name, "")
            df = pd.DataFrame({y_col_name: y_arr}, index=pd.Index(x_arr, name="x"))
            return TraceData(
                df=df,
                column_roles={y_col_name: COLUMN_ROLE_Y},
                names=names,
                units=units,
            )
        except Exception as exc:
            self.log.warning("CurveFit: failed to compute initial trace — %s", exc)
            return None

    def _run_curve_fit(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        fit_func,
        x_arr: np.ndarray,
        y_arr: np.ndarray,
        sigma_arr,
        p0,
        bounds,
    ) -> tuple[np.ndarray, np.ndarray] | None:
        """Run ``scipy.optimize.curve_fit`` and return ``(popt, pcov)``.

        Handles :exc:`ImportError` when scipy is absent and any other
        optimisation failure, logging the appropriate error and returning
        ``None`` in each case.

        Args:
            fit_func:
                Compiled ``fit(x, …)`` callable.
            x_arr (np.ndarray):
                x data array.
            y_arr (np.ndarray):
                y data array.
            sigma_arr:
                y-uncertainty array, or ``None``.
            p0:
                Initial parameter values, or ``None``.
            bounds:
                ``(lower, upper)`` bounds tuple, or ``None``.

        Returns:
            (tuple[np.ndarray, np.ndarray] | None):
                ``(popt, pcov)`` on success, ``None`` on failure.
        """
        try:
            from scipy.optimize import curve_fit  # noqa: PLC0415

            kwargs: dict[str, Any] = {}
            if sigma_arr is not None:
                kwargs["sigma"] = sigma_arr
                kwargs["absolute_sigma"] = True
            if bounds is not None:
                kwargs["bounds"] = bounds
            if p0 is not None:
                kwargs["p0"] = p0

            popt, pcov = curve_fit(fit_func, x_arr, y_arr, **kwargs)
            return popt, pcov
        except ImportError:
            self.log.error("CurveFit: scipy is not installed.  Install scipy to use the curve-fit plugin.")
            return None
        except Exception as exc:
            self.log.error("CurveFit: curve_fit failed — %s", exc)
            return None

    def _build_scalar_results(self, popt: np.ndarray, pcov: np.ndarray) -> dict[str, float]:
        """Build the scalar result dict from fitted parameters and covariance.

        Args:
            popt (np.ndarray):
                Optimal parameter values returned by ``curve_fit``.
            pcov (np.ndarray):
                Covariance matrix returned by ``curve_fit``.

        Returns:
            (dict[str, float]):
                Mapping of parameter name → optimal value and
                ``"{name}_err"`` → 1-sigma uncertainty.
        """
        perr = np.sqrt(np.diag(pcov))
        result: dict[str, float] = {}
        for i, pname in enumerate(self.param_names):
            result[pname] = float(popt[i]) if i < len(popt) else _NAN
            result[f"{pname}_err"] = float(perr[i]) if i < len(perr) else _NAN
        return result

    def _compute_best_fit_trace(
        self,
        fit_func,
        x_arr: np.ndarray,
        popt: np.ndarray,
        *,
        y_col_name: str = "y",
        source_names: dict[str, str] | None = None,
        source_units: dict[str, str] | None = None,
    ) -> TraceData | None:
        """Evaluate the fit function with optimal parameters to produce a trace.

        Args:
            fit_func:
                Compiled ``fit(x, …)`` callable.
            x_arr (np.ndarray):
                x data array.
            popt (np.ndarray):
                Optimal parameter values returned by ``curve_fit``.

        Keyword Parameters:
            y_col_name (str):
                Column name to use in the output DataFrame.  Defaults to ``"y"``.
            source_names (dict[str, str] | None):
                Human-readable name mapping from the source trace.  Used to
                propagate axis labels to the output TraceData.
            source_units (dict[str, str] | None):
                Physical unit mapping from the source trace.  Used to
                propagate units to the output TraceData.

        Returns:
            (TraceData | None):
                Trace evaluated at the optimal parameters, or ``None`` on
                failure.
        """
        try:
            y_best = fit_func(x_arr, *popt)
            y_arr = np.asarray(y_best, dtype=float)
            names: dict[str, str] = dict(source_names or {})
            names.setdefault("x", "x")
            names.setdefault(y_col_name, y_col_name)
            units: dict[str, str] = dict(source_units or {})
            units.setdefault("x", "")
            units.setdefault(y_col_name, "")
            df = pd.DataFrame({y_col_name: y_arr}, index=pd.Index(x_arr, name="x"))
            return TraceData(
                df=df,
                column_roles={y_col_name: COLUMN_ROLE_Y},
                names=names,
                units=units,
            )
        except Exception as exc:
            self.log.warning("CurveFit: failed to compute best-fit trace — %s", exc)
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _emit_stdout_to_console(self, text: str) -> None:
        """Emit captured stdout text to the script-tab console output signal."""
        if not text:
            return
        engine = self.sequence_engine
        if engine is None:
            return
        try:
            engine.output.emit(text)
        except RuntimeError:
            # The underlying Qt object may already be deleted during shutdown.
            pass

    def _wrap_user_stdout_callable(
        self,
        func: Callable[..., Any] | None,
    ) -> Callable[..., Any] | None:
        """Wrap a user callable so its stdout is forwarded to the console."""
        if func is None or self.sequence_engine is None:
            return func

        @functools.wraps(func)
        def _wrapped(*args, **kwargs):
            stream = StringIO()
            try:
                with redirect_stdout(stream):
                    return func(*args, **kwargs)
            finally:
                self._emit_stdout_to_console(stream.getvalue())

        return _wrapped

    def _get_data_arrays(
        self,
    ) -> tuple[
        np.ndarray | None,
        np.ndarray | None,
        np.ndarray | None,
        str,
        dict[str, str],
        dict[str, str],
    ]:
        """Retrieve x, y and sigma arrays from the engine namespace.

        In simple mode, :attr:`column_key` is used to select a specific column
        from a multicolumn
        :class:`~stoner_measurement.plugins.trace.base.TraceData`.  When
        :attr:`column_key` is empty the first :data:`COLUMN_ROLE_Y` column is
        used (backward-compatible behaviour).

        Returns:
            (tuple):
                Six-element tuple ``(x_data, y_data, sigma, y_col_name,
                source_names, source_units)``:

                * *x_data* — independent-variable array, or ``None``.
                * *y_data* — dependent-variable array, or ``None``.
                * *sigma* — y-uncertainty array, or ``None``.
                * *y_col_name* — column name used to select *y_data*.  ``"y"``
                  in advanced mode.
                * *source_names* — ``names`` mapping from the source trace
                  (empty dict in advanced mode).
                * *source_units* — ``units`` mapping from the source trace
                  (empty dict in advanced mode).
        """
        sigma = None
        y_col_name = "y"
        source_names: dict[str, str] = {}
        source_units: dict[str, str] = {}

        if self.advanced_mode:
            if not self.x_expr or not self.y_expr:
                raise ValueError("x_expr and y_expr must be set in advanced mode.")
            x_data = self.eval(self.x_expr)
            y_data = self.eval(self.y_expr)
            if self.y_error_expr:
                sigma = self.eval(self.y_error_expr)
        else:
            traces = self.engine_namespace.get("_traces", {})
            if not self.trace_key or self.trace_key not in traces:
                raise ValueError(f"Trace {self.trace_key!r} not found in _traces catalogue.")
            trace_expr = traces[self.trace_key]
            trace_data = self.eval(trace_expr)
            x_data = trace_data.x
            source_names = dict(getattr(trace_data, "names", {}))
            source_units = dict(getattr(trace_data, "units", {}))

            col = self.column_key
            y_cols = trace_data.get_columns_by_role(COLUMN_ROLE_Y)
            if col and hasattr(trace_data, "df") and col in trace_data.df.columns:
                y_data = trace_data.df[col].to_numpy(dtype=float)
                y_col_name = col
            else:
                y_data = trace_data.y
                y_col_name = y_cols[0] if y_cols else "y"

            e_cols = trace_data.get_columns_by_role(COLUMN_ROLE_E)
            if e_cols:
                error_array: np.ndarray | None = None
                if y_col_name in y_cols:
                    y_idx = y_cols.index(y_col_name)
                    if y_idx < len(e_cols):
                        error_array = trace_data.df[e_cols[y_idx]].to_numpy(dtype=float)
                if error_array is None:
                    error_array = trace_data.df[e_cols[0]].to_numpy(dtype=float)
            else:
                error_array = trace_data.e
            if len(error_array) == len(y_data) and np.any(error_array != 0):
                sigma = error_array

        return x_data, y_data, sigma, y_col_name, source_names, source_units

    def _compile_fit_code(self):
        """Compile the fit code and return ``(fit_func, p0_func)``.

        Returns:
            (tuple[callable | None, callable | None]):
                The compiled ``fit`` and optional ``p0`` callables.
        """
        ns: dict[str, Any] = {"__builtins__": __builtins__}
        ns["np"] = np
        ns["numpy"] = np
        ns["log"] = logging.getLogger(SEQUENCE_LOGGER_NAME)
        exec(compile(self.fit_code, "<fit_code>", "exec"), ns)  # noqa: S102  # pylint: disable=exec-used
        fit_func = ns.get("fit")
        p0_func = ns.get("p0")
        return fit_func, p0_func

    def _build_p0(self, p0_func, x_arr: np.ndarray, y_arr: np.ndarray):
        """Build the p0 initial-parameter vector.

        Uses the ``p0`` function if defined; otherwise uses the Initial values
        from the parameter table.

        Args:
            p0_func:
                The compiled ``p0(x, y)`` callable, or ``None``.
            x_arr (np.ndarray):
                x data array.
            y_arr (np.ndarray):
                y data array.

        Returns:
            (list[float] | None):
                Initial parameter values, or ``None`` if all entries are blank.
        """
        if p0_func is not None:
            try:
                result = p0_func(x_arr, y_arr)
                return list(result)
            except Exception as exc:
                self.log.warning("CurveFit: p0 function raised %s — using table values.", exc)

        initials = []
        all_none = True
        for pname in self.param_names:
            val = self.param_settings.get(pname, {}).get("initial")
            initials.append(1.0 if val is None else val)
            if val is not None:
                all_none = False
        return None if all_none else initials

    def _build_bounds(self):
        """Build the bounds tuple for scipy.optimize.curve_fit.

        Returns:
            (tuple[list, list] | None):
                ``(lower_bounds, upper_bounds)`` or ``None`` if no bounds are
                configured.
        """
        lower: list[float] = []
        upper: list[float] = []
        has_bounds = False
        for pname in self.param_names:
            s = self.param_settings.get(pname, {})
            lo = s.get("min")
            hi = s.get("max")
            lower.append(-_INF if lo is None else lo)
            upper.append(_INF if hi is None else hi)
            if lo is not None or hi is not None:
                has_bounds = True
        if not has_bounds:
            return None
        return (lower, upper)

    def _preview_used_initial_values(self) -> tuple[dict[str, Any], bool]:
        """Return the initial values currently used by the fit for table display.

        Returns:
            (tuple[dict[str, Any], bool]):
                A two-item tuple ``(values, uses_p0)`` where *values* maps each
                parameter name to the initial value currently used by the fit
                when it can be determined, and *uses_p0* indicates whether a
                user-defined ``p0(x, y)`` function is active.
        """
        if not self.param_names:
            return {}, False

        try:
            fit_func, p0_func = self._compile_fit_code()
        except Exception:
            return {}, False

        if fit_func is None:
            return {}, False

        uses_p0 = p0_func is not None
        if uses_p0:
            try:
                x_data, y_data, _, _, _, _ = self._get_data_arrays()
            except Exception:
                return {}, True
            if x_data is None or y_data is None:
                return {}, True
            values = self._build_p0(p0_func, np.asarray(x_data, dtype=float), np.asarray(y_data, dtype=float))
        else:
            values = self._build_p0(None, np.empty(0, dtype=float), np.empty(0, dtype=float))

        resolved_values = [1.0] * len(self.param_names) if values is None else list(values)
        if len(resolved_values) != len(self.param_names):
            return {}, uses_p0
        preview = {name: resolved_values[index] for index, name in enumerate(self.param_names)}
        return preview, uses_p0

    def _refresh_param_table_preview(self) -> None:
        """Refresh the parameter-table preview rows for the current configuration."""
        if self._param_table_widget is None:
            return
        values, _ = self._preview_used_initial_values()
        self._param_table_widget.update_used_initial_values(values)

    def _schedule_param_table_preview_refresh(self, delay_ms: int = 150) -> None:
        """Schedule a debounced parameter-table preview refresh.

        Args:
            delay_ms (int):
                Delay in milliseconds before the preview refresh runs.
        """
        if self._param_table_widget is None:
            return
        self._param_table_preview_timer.start(delay_ms)

    def _update_param_names(self, code: str) -> None:
        """Update :attr:`param_names` by introspecting *code*.

        Args:
            code (str):
                Fit function source code.
        """
        self.fit_code = code
        tree, syntax_error = _parse_fit_tree(code)
        if syntax_error is None:
            self.fit_code_syntax_error_line = None
            self.fit_code_syntax_error_message = ""
            new_names = _fit_param_names_from_tree(tree) if tree is not None else []
        else:
            self.fit_code_syntax_error_line = syntax_error.lineno
            self.fit_code_syntax_error_message = str(syntax_error)
            new_names = []
        if new_names != self.param_names:
            self.param_names = new_names

    def _merge_param_settings(
        self,
        table_settings: dict[str, dict[str, float | None]],
        current_param_names: list[str],
    ) -> None:
        """Merge table settings while preserving non-parameter auxiliary keys.

        Args:
            table_settings (dict[str, dict[str, float | None]]):
                Parameter settings read from the UI table.
            current_param_names (list[str]):
                Parameter names currently managed by the fit-function table.
        """
        auxiliary_settings = {
            key: value for key, value in self.param_settings.items() if key not in current_param_names
        }
        self.param_settings = {**auxiliary_settings, **table_settings}

    # ------------------------------------------------------------------
    # Configuration tabs
    # ------------------------------------------------------------------

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return the configuration tabs for this plugin.

        Produces a *Data* tab (with the instance-name editor at the top,
        followed by trace / expression selection controls), a *Fit Function*
        tab containing a Python code editor, a *Parameters* tab with the
        per-parameter bounds table, and an optional *About* tab.  The separate
        *General* tab is intentionally omitted — its controls are embedded
        at the top of the *Data* tab.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> p = CurveFitPlugin()
            >>> tabs = p.config_tabs()
            >>> [t for t, _ in tabs[:3]]
            ['Data', 'Fit Function', 'Parameters']
            >>> 'General' not in [t for t, _ in tabs]
            True
        """
        def _build_tabs() -> list[tuple[str, QWidget]]:
            tabs = super().config_tabs(parent)
            fit_tab, param_tab = self._build_fit_and_param_tabs(parent)
            # Insert Fit Function and Parameters after the Data tab (index 0).
            tabs.insert(1, ("Parameters", param_tab))
            tabs.insert(1, ("Fit Function", fit_tab))
            return tabs

        return self._get_cached_config_tabs(_build_tabs)

    def _get_trace_columns(self, trace_key: str) -> list[str]:
        """Return the DataFrame column names for the trace identified by *trace_key*.

        Attempts to evaluate the trace expression in the engine namespace and
        return :attr:`~stoner_measurement.plugins.trace.TraceData.columns` from
        the result.  Returns an empty list if the trace has not yet been measured
        or if the evaluation fails.

        Args:
            trace_key (str):
                The trace catalogue key (same as :attr:`trace_key`).

        Returns:
            (list[str]):
                Column names from the trace's DataFrame, or an empty list.
        """
        traces = self.engine_namespace.get("_traces", {})
        if not trace_key or trace_key not in traces:
            return []
        try:
            trace_data = self.eval(traces[trace_key])
            cols = getattr(trace_data, "columns", None)
            if isinstance(cols, list):
                return cols
        except Exception:
            pass
        return []

    def _build_column_combo(self, widget: QWidget) -> QComboBox:
        """Build a column-selection combo box for the given widget.

        Populates the combo with the column names of the trace identified by
        :attr:`trace_key`.  When the trace is not yet available a ``"(default)"``
        placeholder item is shown and :attr:`column_key` is cleared.

        Args:
            widget (QWidget):
                Parent widget for the new combo box.

        Returns:
            (QComboBox):
                Configured column combo box.
        """
        combo = QComboBox(widget)
        self._populate_column_combo(combo, self.trace_key)
        return combo

    def _populate_column_combo(self, combo: QComboBox, trace_key: str) -> None:
        """Populate *combo* with ``(default)`` plus columns for *trace_key*.

        Existing combo entries are cleared first.  If :attr:`column_key`
        matches one of the available columns it is selected; otherwise the
        ``(default)`` entry is selected.

        Args:
            combo (QComboBox):
                Combo box to populate.
            trace_key (str):
                Trace key used to resolve available columns.
        """
        columns = self._get_trace_columns(trace_key)
        combo.clear()
        combo.addItem(_DEFAULT_COLUMN_OPTION)
        combo.addItems(columns)
        if self.column_key and self.column_key in columns:
            combo.setCurrentText(self.column_key)
        else:
            combo.setCurrentText(_DEFAULT_COLUMN_OPTION)

    def _create_data_source_widgets(
        self, widget: QWidget, traces: dict[str, str]
    ) -> dict[str, Any]:
        """Create the data source selection widgets for the *Data* tab.

        Builds and returns the trace dropdown, column dropdown,
        advanced-mode checkbox, x/y dropdowns, and y-uncertainty line edit
        together with the channel-items mapping used by the signal handlers.

        Args:
            widget (QWidget):
                Parent widget for all created controls.
            traces (dict[str, str]):
                Mapping of trace key → engine-namespace expression, typically
                ``engine_namespace["_traces"]``.

        Returns:
            (dict[str, Any]):
                Dict with keys ``"trace_combo"``, ``"column_combo"``,
                ``"advanced_check"``, ``"x_combo"``, ``"y_combo"``,
                ``"y_error_edit"``, and ``"channel_items"``.
        """
        trace_keys = list(traces.keys())
        channel_items: dict[str, str] = {}
        for key, expr in traces.items():
            channel_items[f"{key} (x)"] = f"{expr}.x"
            channel_items[f"{key} (y)"] = f"{expr}.y"
        channel_names = list(channel_items.keys())

        trace_combo = QComboBox(widget)
        if trace_keys:
            trace_combo.addItems(trace_keys)
            if self.trace_key in trace_keys:
                trace_combo.setCurrentText(self.trace_key)
            else:
                self.trace_key = trace_keys[0]
        else:
            trace_combo.addItem("(no traces available)")

        column_combo = self._build_column_combo(widget)

        advanced_check = QCheckBox(widget)
        advanced_check.setChecked(self.advanced_mode)

        x_combo = QComboBox(widget)
        if channel_names:
            x_combo.addItems(channel_names)
            if not _set_combo_to_expr(x_combo, channel_items, self.x_expr):
                self.x_expr = channel_items[channel_names[0]]
                x_combo.setCurrentIndex(0)
        else:
            x_combo.addItem("(no channels available)")

        y_combo = QComboBox(widget)
        if channel_names:
            y_combo.addItems(channel_names)
            if not _set_combo_to_expr(y_combo, channel_items, self.y_expr):
                self.y_expr = channel_items[channel_names[0]]
                y_combo.setCurrentIndex(0)
        else:
            y_combo.addItem("(no channels available)")

        y_error_edit = QLineEdit(self.y_error_expr, widget)
        y_error_edit.setToolTip(
            "Python expression for y-uncertainty (sigma).  Leave blank to fit without uncertainties."
        )

        return {
            "trace_combo": trace_combo,
            "column_combo": column_combo,
            "advanced_check": advanced_check,
            "x_combo": x_combo,
            "y_combo": y_combo,
            "y_error_edit": y_error_edit,
            "channel_items": channel_items,
        }

    def _build_data_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build the *Data* selection tab widget.

        Args:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                Configured data selection widget.
        """
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        traces: dict[str, str] = self.engine_namespace.get("_traces", {})
        ws = self._create_data_source_widgets(widget, traces)

        layout.addRow("Trace:", ws["trace_combo"])
        layout.addRow("Column:", ws["column_combo"])
        layout.addRow("Advanced mode:", ws["advanced_check"])
        layout.addRow("X data:", ws["x_combo"])
        layout.addRow("Y data:", ws["y_combo"])
        layout.addRow("Y uncertainty:", ws["y_error_edit"])
        layout.addRow(
            QLabel(
                "<i>In advanced mode expressions are evaluated against the engine namespace at runtime.</i>",
                widget,
            )
        )
        widget.setLayout(layout)

        def _update_enabled(advanced: bool) -> None:
            ws["trace_combo"].setEnabled(not advanced)
            ws["column_combo"].setEnabled(not advanced)
            ws["x_combo"].setEnabled(advanced)
            ws["y_combo"].setEnabled(advanced)
            ws["y_error_edit"].setEnabled(advanced)

        _update_enabled(self.advanced_mode)
        ws["advanced_check"].toggled.connect(_update_enabled)

        def _apply_trace(text: str) -> None:
            if text != "(no traces available)":
                self.trace_key = text
                columns = self._get_trace_columns(self.trace_key)
                ws["column_combo"].blockSignals(True)
                self._populate_column_combo(ws["column_combo"], self.trace_key)
                if self.column_key not in columns:
                    self.column_key = ""
                    ws["column_combo"].setCurrentText(_DEFAULT_COLUMN_OPTION)
                ws["column_combo"].blockSignals(False)
            self._schedule_param_table_preview_refresh()

        def _apply_column(text: str) -> None:
            if text != _DEFAULT_COLUMN_OPTION:
                self.column_key = text
            else:
                self.column_key = ""
            self._schedule_param_table_preview_refresh()

        def _apply_advanced(checked: bool) -> None:
            self.advanced_mode = checked
            self._schedule_param_table_preview_refresh()

        def _apply_x(text: str) -> None:
            if text != "(no channels available)":
                self.x_expr = ws["channel_items"].get(text, self.x_expr)
            self._schedule_param_table_preview_refresh()

        def _apply_y(text: str) -> None:
            if text != "(no channels available)":
                self.y_expr = ws["channel_items"].get(text, self.y_expr)
            self._schedule_param_table_preview_refresh()

        def _apply_y_error() -> None:
            self.y_error_expr = ws["y_error_edit"].text().strip()
            self._schedule_param_table_preview_refresh()

        ws["trace_combo"].currentTextChanged.connect(_apply_trace)
        ws["column_combo"].currentTextChanged.connect(_apply_column)
        ws["advanced_check"].toggled.connect(_apply_advanced)
        ws["x_combo"].currentTextChanged.connect(_apply_x)
        ws["y_combo"].currentTextChanged.connect(_apply_y)
        ws["y_error_edit"].editingFinished.connect(_apply_y_error)

        return widget

    def _build_fit_tab(self, parent: QWidget | None) -> tuple[QWidget, EditorWidget]:
        """Build the *Fit Function* tab widget.

        Args:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (tuple[QWidget, EditorWidget]):
                ``(fit_function_widget, editor)`` where *editor* is needed by
                :meth:`_build_fit_and_param_tabs` to wire the code-change signal.
        """
        fit_widget = QWidget(parent)
        fit_layout = QVBoxLayout(fit_widget)

        hint_label = QLabel(
            "<b>Define a <code>fit(x, p1, p2, …)</code> function.</b>  "
            "Optionally define <code>p0(x, y)</code> to compute initial "
            "parameter estimates; if absent the Parameters table is used.",
            fit_widget,
        )
        hint_label.setWordWrap(True)
        fit_layout.addWidget(hint_label)

        namespace_label = QLabel(
            "<i>Runtime namespace includes Python built-ins and "
            "<code>numpy</code> available as <code>np</code> and <code>numpy</code>.</i>",
            fit_widget,
        )
        namespace_label.setWordWrap(True)
        fit_layout.addWidget(namespace_label)

        editor = EditorWidget(fit_widget)
        editor.set_text(self.fit_code)
        if self.fit_code_syntax_error_line is not None and self.fit_code_syntax_error_message:
            editor.set_syntax_error(self.fit_code_syntax_error_line, self.fit_code_syntax_error_message)
        fit_layout.addWidget(editor)
        fit_widget.setLayout(fit_layout)
        return fit_widget, editor

    def _build_fit_and_param_tabs(self, parent: QWidget | None) -> tuple[QWidget, QWidget]:
        """Build the *Fit Function* and *Parameters* tab widgets.

        The two widgets share a connection: when the editor contents change the
        parameter names are re-extracted and the parameter table is updated.
        The *Parameters* tab also contains checkboxes for the optional trace
        outputs (:attr:`show_initial_trace` and :attr:`show_best_fit_trace`).

        Args:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (tuple[QWidget, QWidget]):
                ``(fit_function_widget, parameters_widget)``
        """
        # ---- Fit Function tab -------------------------------------------
        fit_widget, editor = self._build_fit_tab(parent)

        # ---- Parameters tab ---------------------------------------------
        param_container = QWidget(parent)
        param_layout = QVBoxLayout(param_container)

        param_widget = _ParamTableWidget(param_container)
        param_widget.load_settings(self.param_settings, self.param_names)
        param_widget.update_fitted_results(self.data)
        self._param_table_widget = param_widget
        self._refresh_param_table_preview()
        param_layout.addWidget(param_widget)

        # Optional trace output checkboxes.
        initial_check = QCheckBox("Calculate initial-parameter trace", param_container)
        initial_check.setChecked(self.show_initial_trace)
        initial_check.setToolTip(
            "When enabled, stores a trace of the fitting function evaluated with the initial parameter values (p0)."
        )
        param_layout.addWidget(initial_check)

        best_fit_check = QCheckBox("Calculate best-fit trace", param_container)
        best_fit_check.setChecked(self.show_best_fit_trace)
        best_fit_check.setToolTip(
            "When enabled, stores a trace of the fitting function evaluated "
            "with the optimal parameters found by the fit."
        )
        param_layout.addWidget(best_fit_check)
        param_container.setLayout(param_layout)

        # ---- Wire code changes to parameter detection -------------------
        def _on_code_changed() -> None:
            code = editor.text()
            old_names = list(self.param_names)
            self._update_param_names(code)
            if self.fit_code_syntax_error_line is not None and self.fit_code_syntax_error_message:
                editor.set_syntax_error(self.fit_code_syntax_error_line, self.fit_code_syntax_error_message)
            else:
                editor.clear_syntax_error()
            # Flush current table values into param_settings.
            table_settings = param_widget.read_settings()
            if self.param_names != old_names:
                param_widget.set_parameters(self.param_names)
                table_settings = param_widget.read_settings()
            self._merge_param_settings(table_settings, old_names + self.param_names)
            self._schedule_param_table_preview_refresh()

        editor.textChanged.connect(_on_code_changed)

        # ---- Wire table changes back to param_settings ------------------
        def _on_table_changed() -> None:
            table_settings = param_widget.read_settings()
            self._merge_param_settings(table_settings, self.param_names)
            self._schedule_param_table_preview_refresh()

        param_widget.settings_changed.connect(_on_table_changed)

        def _on_transform_complete(results: dict[str, Any]) -> None:
            param_widget.update_fitted_results(results)
            self._refresh_param_table_preview()

        self.transform_complete.connect(_on_transform_complete)

        # ---- Wire trace checkboxes to attributes -----------------------
        def _on_initial_toggled(checked: bool) -> None:
            self.show_initial_trace = checked

        def _on_best_fit_toggled(checked: bool) -> None:
            self.show_best_fit_trace = checked

        initial_check.toggled.connect(_on_initial_toggled)
        best_fit_check.toggled.connect(_on_best_fit_toggled)

        return fit_widget, param_container

    # ------------------------------------------------------------------
    # JSON serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Serialise the curve-fit configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict extended with ``"trace_key"``, ``"column_key"``,
                ``"advanced_mode"``, ``"x_expr"``, ``"y_expr"``,
                ``"y_error_expr"``, ``"fit_code"``, ``"param_names"``,
                ``"param_settings"``, ``"show_initial_trace"``,
                and ``"show_best_fit_trace"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> p = CurveFitPlugin()
            >>> d = p.to_json()
            >>> d["type"]
            'transform'
            >>> "fit_code" in d and "param_settings" in d
            True
            >>> "show_initial_trace" in d and "show_best_fit_trace" in d
            True
        """
        d = super().to_json()
        d["trace_key"] = self.trace_key
        d["column_key"] = self.column_key
        d["advanced_mode"] = self.advanced_mode
        d["x_expr"] = self.x_expr
        d["y_expr"] = self.y_expr
        d["y_error_expr"] = self.y_error_expr
        d["fit_code"] = self.fit_code
        d["param_names"] = self.param_names
        d["param_settings"] = self.param_settings
        d["show_initial_trace"] = self.show_initial_trace
        d["show_best_fit_trace"] = self.show_best_fit_trace
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore configuration from a serialised dict.

        Args:
            data (dict[str, Any]):
                Dict as produced by :meth:`to_json`.
        """
        self.trace_key = data.get("trace_key", "")
        self.column_key = data.get("column_key", "")
        self.advanced_mode = data.get("advanced_mode", False)
        self.x_expr = data.get("x_expr", "")
        self.y_expr = data.get("y_expr", "")
        self.y_error_expr = data.get("y_error_expr", "")
        self.fit_code = data.get("fit_code", _DEFAULT_FIT_CODE)
        self.param_names = data.get("param_names", _parse_fit_params(self.fit_code))
        raw_settings = data.get("param_settings", {})
        self.param_settings = {
            name: {k: (float(v) if v is not None else None) for k, v in entry.items()}
            for name, entry in raw_settings.items()
        }
        self.show_initial_trace = data.get("show_initial_trace", False)
        self.show_best_fit_trace = data.get("show_best_fit_trace", False)


# ---------------------------------------------------------------------------
# Module-level helper (mirrors plot_trace.py)
# ---------------------------------------------------------------------------


def _set_combo_to_expr(
    combo: QComboBox,
    items: dict[str, str],
    expr: str,
) -> bool:
    """Set *combo* current item to the entry in *items* whose value matches *expr*.

    Args:
        combo (QComboBox):
            Combo box to update.
        items (dict[str, str]):
            Mapping of display name → expression.
        expr (str):
            Expression to search for.

    Returns:
        (bool):
            ``True`` if a match was found and the combo was updated.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication, QComboBox
        >>> _ = QApplication.instance() or QApplication([])
        >>> combo = QComboBox()
        >>> combo.addItems(["a", "b"])
        >>> _set_combo_to_expr(combo, {"a": "expr_a", "b": "expr_b"}, "expr_b")
        True
        >>> combo.currentText()
        'b'
    """
    for display_name, item_expr in items.items():
        if item_expr == expr:
            combo.setCurrentText(display_name)
            return True
    return False
