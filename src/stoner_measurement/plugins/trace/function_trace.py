"""Synthetic trace plugin driven by a user-defined Python function."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget

from stoner_measurement.core.trace_data import COLUMN_ROLE_Y, COLUMN_ROLE_Z, TraceData
from stoner_measurement.plugins.trace.base import TracePlugin
from stoner_measurement.ui.editor_widget import EditorWidget

DEFAULT_FUNCTION_CODE = '''\
def calculate_data(x: np.ndarray) -> pd.DataFrame:
    """Return one row of synthetic data for every scan value."""
    return pd.DataFrame({"y": np.sin(x)})
'''


class FunctionTracePlugin(TracePlugin):
    """Calculate a synthetic trace by passing scan values to Python code.

    Use this hardware-free trace plugin to test sequences, plotting, saving,
    transforms, and other application workflows with arbitrary reproducible
    data. The **Scan** page is the standard trace-plugin scan-generator page.
    The **Function** page defines ``calculate_data(x)``, where ``x`` is the
    one-dimensional NumPy array produced by the selected scan generator.

    ``calculate_data`` must return a :class:`pandas.DataFrame` with exactly one
    row for every value in ``x`` and at least one uniquely named column. The
    column name ``x`` is reserved: the plugin inserts the scan values as that
    column. The first returned column is the primary y channel and subsequent
    columns are auxiliary channels. All returned columns must contain numeric
    values. The execution namespace provides :mod:`numpy` as ``np`` and
    ``numpy``, and :mod:`pandas` as ``pd`` and ``pandas``; imports and helper
    functions may also be included in the editor.

    User code is compiled at acquisition time. A missing or non-callable
    ``calculate_data`` function, an invalid return type, duplicate/reserved
    columns, non-numeric data, or a row-count mismatch raises an informative
    exception and puts the trace plugin into its standard error state.

    Attributes:
        function_code (str):
            Complete trusted Python source executed for each acquisition.
        scan_generator (BaseScanGenerator):
            Standard configurable generator that supplies ``x``.
        data (dict[str, TraceData]):
            Latest successful trace, keyed by ``"Function Trace"``.

    Warning:
        The source is executed as normal Python and is not sandboxed. Only run
        code from trusted sequence files.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.function_code = DEFAULT_FUNCTION_CODE
        self._function_editor: EditorWidget | None = None
        self._apply_initial_config()

    @property
    def name(self) -> str:
        """Return the plugin and output trace display name."""
        return "Function Trace"

    def _compile_calculate_data(self) -> Callable[[np.ndarray], pd.DataFrame]:
        """Compile the configured source and return ``calculate_data``."""
        namespace: dict[str, Any] = {
            "__builtins__": __builtins__,
            "np": np,
            "numpy": np,
            "pd": pd,
            "pandas": pd,
        }
        # Executing trusted user-authored calculation code is the purpose of
        # this plugin and matches the curve-fit transform's execution model.
        exec(  # noqa: S102  # nosec B102  # pylint: disable=exec-used
            compile(self.function_code, "<function_trace_code>", "exec"), namespace
        )
        function = namespace.get("calculate_data")
        if not callable(function):
            raise ValueError("Function code must define callable calculate_data(x).")
        return function

    def _measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Evaluate ``calculate_data`` for the generated scan values."""
        del parameters
        x = np.asarray(self.scan_generator.generate(), dtype=float)
        if x.ndim != 1:
            raise ValueError("The scan generator must produce a one-dimensional array.")
        frame = self._compile_calculate_data()(x.copy())
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("calculate_data(x) must return a pandas DataFrame.")
        if len(frame) != len(x):
            raise ValueError(
                "calculate_data(x) returned "
                f"{len(frame)} rows for {len(x)} scan values; the lengths must match."
            )
        if frame.columns.has_duplicates:
            raise ValueError("calculate_data(x) returned duplicate DataFrame column names.")
        if not len(frame.columns):
            raise ValueError("calculate_data(x) must return at least one data column.")
        if "x" in frame.columns:
            raise ValueError("DataFrame column name 'x' is reserved for scan values.")

        numeric = frame.copy().reset_index(drop=True)
        for column in numeric.columns:
            try:
                numeric[column] = pd.to_numeric(numeric[column], errors="raise")
            except (TypeError, ValueError) as exc:
                raise TypeError(f"DataFrame column {column!r} must be numeric.") from exc
        numeric.insert(0, "x", x)
        data_columns = list(numeric.columns[1:])
        roles = {
            column: COLUMN_ROLE_Y if index == 0 else COLUMN_ROLE_Z
            for index, column in enumerate(data_columns)
        }
        return {self.name: TraceData(numeric, column_roles=roles)}

    def _plugin_config_tabs(self) -> QWidget:
        """Build the compact shared Python editor used by the Function page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel(
            "<b>Define <code>calculate_data(x)</code> and return a numeric "
            "<code>pandas.DataFrame</code> with <code>len(x)</code> rows.</b>",
            page,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        namespace = QLabel(
            "<i>The runtime namespace provides <code>np</code>, <code>numpy</code>, "
            "<code>pd</code>, and <code>pandas</code>. The name <code>x</code> is "
            "reserved for the generated scan values.</i>",
            page,
        )
        namespace.setWordWrap(True)
        layout.addWidget(namespace)
        editor = EditorWidget(page)
        editor.setObjectName("functionTraceEditor")
        editor.set_text(self.function_code)
        editor.setMinimumHeight(180)
        editor.setMaximumHeight(260)
        editor.textChanged.connect(lambda: self._apply_editor_source(editor))
        layout.addWidget(editor)
        layout.addStretch()
        self._function_editor = editor
        return page

    def _apply_editor_source(self, editor: EditorWidget) -> None:
        """Store editor text and display syntax errors in its gutter."""
        self.function_code = editor.text()
        try:
            compile(self.function_code, "<function_trace_code>", "exec")
        except SyntaxError as exc:
            editor.set_syntax_error(exc.lineno, str(exc))
        else:
            editor.set_syntax_error(None, "")

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return the standard Scan page followed by Function and About."""
        tabs = super().config_tabs(parent)
        tabs[1] = ("Function", tabs[1][1])
        return tabs

    def to_json(self) -> dict[str, Any]:
        """Serialise the scan generator and calculation source."""
        data = super().to_json()
        data["function_code"] = self.function_code
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore the scan generator and calculation source."""
        super()._restore_from_json(data)
        self.function_code = str(data.get("function_code", DEFAULT_FUNCTION_CODE))
