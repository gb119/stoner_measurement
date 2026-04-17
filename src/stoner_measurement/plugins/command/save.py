"""SaveCommand — built-in command plugin for writing data to disc.

:class:`SaveCommand` is a concrete :class:`CommandPlugin` that evaluates a
Python expression to obtain a file path and then writes data to a TDI Format 2.0
tab-delimited text file.  Two save modes are supported:

* **Traces** — writes all (or a selected subset of) trace channels from the
  ``_traces`` catalogue in the sequence engine namespace.
* **Data** — writes the accumulated :class:`~pandas.DataFrame` from a named
  :class:`~stoner_measurement.plugins.state_control.StateControlPlugin` instance.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import numpy as np
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.plugins.command.base import CommandPlugin

#: Regex matching the start of a Python string literal (with optional prefix).
_STRING_EXPR_RE = re.compile(r'^[fFrRbBuU]*["\']')


def _ensure_string_expr(text: str) -> str:
    """Wrap *text* in quotes if it does not already look like a Python string expression.

    If *text* begins with an optional string prefix (``f``, ``r``, ``b``, ``u``)
    followed by a quote character it is returned unchanged.  Otherwise the text
    is passed through :func:`repr` so that it becomes a valid Python string
    literal that will evaluate back to the original text.

    Args:
        text (str):
            Raw text from a UI text field.

    Returns:
        (str):
            A Python string-expression that evaluates to the same value as
            *text*, guaranteed to start and end with quote characters.

    Examples:
        >>> _ensure_string_expr("'already/quoted.txt'")
        "'already/quoted.txt'"
        >>> _ensure_string_expr("plain/path.txt")
        "'plain/path.txt'"
        >>> _ensure_string_expr("f'dynamic/{name}.txt'")
        "f'dynamic/{name}.txt'"
        >>> _ensure_string_expr("")
        ''
    """
    if not text or _STRING_EXPR_RE.match(text):
        return text
    return repr(text)


def _flatten_to_metadata(obj: Any, prefix: str = "") -> list[str]:
    """Recursively flatten a nested dict or list into TDI metadata cell strings.

    Each leaf value is formatted as ``{prefix}{typename}={repr(value)}``.
    Nested dict keys are joined to the prefix with a ``.`` separator; list
    indices use ``[{index}]`` notation.  Any object with an ``.item()`` method
    (e.g. a numpy scalar) is converted to its Python native equivalent before
    formatting so that type names and ``repr`` output are clean.

    Args:
        obj (Any):
            The value to flatten.  Typically the ``dict`` returned by a
            plugin's :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
            method, or a scalar produced by evaluating a ``_values`` expression.

    Keyword Parameters:
        prefix (str):
            Dot-separated key path accumulated by recursive calls.  Pass an
            empty string (the default) to start from the root.

    Returns:
        (list[str]):
            Ordered list of ``"{key}{typename}={repr(value)}"`` strings, one
            per leaf value in *obj*.

    Examples:
        >>> _flatten_to_metadata({"a": {"b": 1}, "c": [{"A": 2.0}, {"B": 4}]})
        ['a.b{int}=1', 'c[0].A{float}=2.0', 'c[1].B{int}=4']
        >>> _flatten_to_metadata(42, "x")
        ['x{int}=42']
        >>> _flatten_to_metadata("hello", "s")
        ["s{str}='hello'"]
    """
    entries: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            child = f"{prefix}.{k}" if prefix else str(k)
            entries.extend(_flatten_to_metadata(v, child))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            entries.extend(_flatten_to_metadata(v, f"{prefix}[{i}]"))
    else:
        # Convert numpy scalars (or any object with .item()) to Python natives.
        if hasattr(obj, "item"):
            obj = obj.item()
        typename = type(obj).__name__
        entries.append(f"{prefix}{{{typename}}}={repr(obj)}")
    return entries


def _to_float_or_nan(value: Any) -> float:
    """Return *value* as float, or NaN when it cannot be converted."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


class SaveCommand(CommandPlugin):
    """Command plugin that saves current trace or state-control data to disc.

    The save path is given as a Python expression string (``path_expr``) that
    is evaluated against the sequence engine namespace at runtime using
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`.  This
    allows the path to incorporate namespace variables such as loop counters,
    timestamps, or instrument settings::

        "f'data/run_{run_index:03d}.txt'"

    Two save modes are supported via :attr:`save_mode`:

    * **Traces** (``"traces"``, default) — writes trace channel data from the
      ``_traces`` catalogue.  :attr:`trace_selection` determines which traces
      are saved; an empty dict saves all available traces.
    * **Data** (``"data"``) — writes the accumulated
      :class:`~pandas.DataFrame` from the
      :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
      instance named by :attr:`data_source`.

    The output is a **TDI Format 2.0** tab-delimited text file structured as
    follows:

    * The top-left cell (row 0, column 0) contains ``"TDI Format 2.0"``.
    * The remaining cells of row 0 are column headers — one per data column.
      In trace mode each header has the form
      ``"{channel_name}:{axis_label} ({axis_units})"``.  In data mode the
      DataFrame index is written first (header ``"index"`` unless the index is
      named), followed by DataFrame column names.
    * The remaining cells of column 0 (rows 1 onwards) hold flattened
      key-value metadata derived from two sources:

      1. The ``to_json()`` state of every plugin registered with the engine,
         formatted as ``{key}{typename}={repr(value)}``.  Nested dicts are
         flattened using ``.`` separators; list items use ``[{index}]``
         notation.
      2. The current scalar readings from the ``_values`` catalog, formatted
         identically.

    * The remaining cells (rows 1 onwards, columns 1 onwards) contain the
      numerical data from each column.

    If a parent directory does not exist it is created automatically.  When
    :attr:`no_overwrite` is ``True`` (the default) and the resolved path
    already exists, a numeric suffix (``_001``, ``_002``, …) is inserted
    before the file extension until a free filename is found.

    Attributes:
        path_expr (str):
            Python expression string that evaluates to the file path.
            Defaults to ``"'data/output.txt'"``.  When the expression evaluates
            to a relative path it is resolved against the default data directory
            configured in the application settings.  If no default data
            directory is set the path is relative to the current working
            directory.
        save_mode (str):
            Either ``"traces"`` (default) or ``"data"``.  Selects whether
            trace channels or a state-control plugin's DataFrame are saved.
        trace_selection (dict[str, bool]):
            Per-trace enable flags for trace mode.  Keys are trace catalogue
            keys (``"{instance_name}:{channel_name}"``).  A key mapping to
            ``True`` (or absent from the dict) means the trace is saved;
            mapping to ``False`` means it is excluded.  An empty dict (the
            default) saves all available traces.
        data_source (str):
            Instance name of the
            :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
            whose :attr:`~stoner_measurement.plugins.state_control.StateControlPlugin.data`
            DataFrame is saved in data mode.  Defaults to ``""``.
        no_overwrite (bool):
            When ``True`` (the default) an existing file is never overwritten;
            instead a numeric suffix is appended to the stem until a free
            filename is found.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command import SaveCommand
        >>> cmd = SaveCommand()
        >>> cmd.name
        'Save'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        False
        >>> cmd.save_mode
        'traces'
        >>> cmd.no_overwrite
        True
    """

    def __init__(self, parent=None) -> None:
        """Initialise with default configuration."""
        super().__init__(parent)
        self.path_expr: str = "'data/output.txt'"
        self.save_mode: str = "traces"
        self.trace_selection: dict[str, bool] = {}
        self.data_source: str = ""
        self.no_overwrite: bool = True

    @property
    def name(self) -> str:
        """Unique identifier for the save command.

        Returns:
            (str):
                ``"Save"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> SaveCommand().name
            'Save'
        """
        return "Save"

    def execute(
        self,
        *,
        trace: str | list[str] | None = None,
        data: str | None = None,
        no_overwrite: bool | None = None,
    ) -> None:
        """Evaluate :attr:`path_expr` and write data to disc.

        Evaluates :attr:`path_expr` in the sequence engine namespace to obtain
        the output file path, creates any required parent directories, and
        writes a TDI Format 2.0 tab-delimited text file.

        The keyword parameters allow per-call overrides of the configured
        settings without permanently modifying the plugin:

        * ``trace`` and ``data`` are mutually exclusive — supplying both raises
          :exc:`ValueError`.
        * Supplying ``trace`` implies trace mode for this call; supplying
          ``data`` implies data mode.
        * ``no_overwrite`` overrides :attr:`no_overwrite` for this call only.

        When the effective no-overwrite flag is ``True`` and the resolved path
        already exists, a numeric suffix (``_001``, ``_002``, …) is appended
        before the file extension until a free filename is found.

        **Trace mode** (``save_mode == "traces"``)

        Each non-empty channel (``x``, ``y``, ``d``, ``e``) of every selected
        trace contributes one column.  Without the ``trace`` kwarg the selection
        is driven by :attr:`trace_selection` (absent key → enabled).  When
        ``trace`` is supplied it must be a trace catalogue key or a list of
        trace catalogue keys; only those traces are saved.  Column headers have
        the form ``"{channel_name}:{axis_label} ({axis_units})"``.

        **Data mode** (``save_mode == "data"``)

        The accumulated :class:`~pandas.DataFrame` from the
        :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
        instance named by :attr:`data_source` (or the ``data`` kwarg) is saved.
        The DataFrame index is written as the first numerical column (header
        ``"index"`` unless the index is named), followed by DataFrame column
        names.

        The file layout is:

        * **Row 0** — ``"TDI Format 2.0"`` followed by one column header per
          data column.
        * **Column 0 (rows 1+)** — flattened metadata entries of the form
          ``"{key}{typename}={repr(value)}"`` collected from the ``to_json()``
          state of every plugin registered with the engine, followed by the
          current scalar readings from the ``_values`` catalog.
        * **Remaining cells** — numerical data from each data column.

        Keyword Parameters:
            trace (str | list[str] | None):
                One or more trace catalogue keys
                (``"{instance_name}:{channel_name}"`` format) to save.  When
                supplied, only the listed traces are saved regardless of
                :attr:`trace_selection`, and the save mode for this call
                becomes ``"traces"``.  May not be combined with *data*.
                Defaults to ``None`` (use configured :attr:`trace_selection`).
            data (str | None):
                Instance name of the
                :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
                whose DataFrame to save.  When supplied the save mode for
                this call becomes ``"data"`` and the value overrides
                :attr:`data_source`.  May not be combined with *trace*.
                Defaults to ``None`` (use configured :attr:`data_source`).
            no_overwrite (bool | None):
                When ``True``, prevent overwriting an existing file (see
                :attr:`no_overwrite`).  ``None`` (default) uses the configured
                :attr:`no_overwrite` attribute.

        Raises:
            ValueError:
                If both *trace* and *data* are supplied.
            RuntimeError:
                If the plugin is not attached to a sequence engine.
            TypeError:
                If :attr:`path_expr` does not evaluate to a string.
            OSError:
                If the file cannot be written (e.g. due to permissions).

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> import tempfile, os
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> cmd = SaveCommand()
            >>> engine.add_plugin("save", cmd)
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     path = os.path.join(tmp, "out.txt")
            ...     cmd.path_expr = repr(path)
            ...     cmd.execute()
            ...     first_line = open(path).readline().rstrip("\\n")
            >>> first_line.startswith("TDI Format 2.0")
            True
            >>> engine.shutdown()
        """
        _save_mode, _trace_keys, _data_source, _no_overwrite = self._resolve_effective_options(
            trace=trace,
            data=data,
            no_overwrite=no_overwrite,
        )
        ns = self.engine_namespace
        metadata = self._build_metadata(ns=ns)
        columns = self._build_data_columns(
            ns=ns,
            save_mode=_save_mode,
            trace_keys=_trace_keys,
            data_source=_data_source,
        )
        if _save_mode == "data" and not columns:
            return
        dest = self._resolve_destination(no_overwrite=_no_overwrite)
        rows = self._build_rows(metadata=metadata, columns=columns)
        self._write_rows(dest=dest, rows=rows)
        self.log.info("Data saved to %s", dest)

    def _resolve_effective_options(
        self,
        *,
        trace: str | list[str] | None,
        data: str | None,
        no_overwrite: bool | None,
    ) -> tuple[str, set[str] | None, str, bool]:
        """Resolve per-call overrides into effective save settings."""
        if trace is not None and data is not None:
            raise ValueError("SaveCommand.execute(): 'trace' and 'data' are mutually exclusive")

        if trace is not None:
            save_mode = "traces"
        elif data is not None:
            save_mode = "data"
        else:
            save_mode = self.save_mode

        trace_keys: set[str] | None
        if trace is not None:
            trace_keys = {trace} if isinstance(trace, str) else set(trace)
        else:
            trace_keys = None

        data_source = data if data is not None else self.data_source
        effective_no_overwrite = self.no_overwrite if no_overwrite is None else no_overwrite
        return save_mode, trace_keys, data_source, effective_no_overwrite

    def _resolve_destination(self, *, no_overwrite: bool) -> pathlib.Path:
        """Evaluate :attr:`path_expr`, resolve to a writable path, and apply no-overwrite."""
        path_val = self.eval(self.path_expr)
        if not isinstance(path_val, str):
            raise TypeError(f"SaveCommand.path_expr must evaluate to a str, got {type(path_val).__name__!r}")

        dest = pathlib.Path(path_val)
        if not dest.is_absolute():
            from stoner_measurement.ui.settings_dialog import (
                KEY_DEFAULT_DATA_DIR,
                make_app_settings,
            )

            settings = make_app_settings()
            data_dir = settings.value(KEY_DEFAULT_DATA_DIR, "", type=str)
            if data_dir:
                dest = pathlib.Path(data_dir) / dest

        dest.parent.mkdir(parents=True, exist_ok=True)
        if no_overwrite and dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            parent_dir = dest.parent
            counter = 1
            while dest.exists():
                dest = parent_dir / f"{stem}_{counter:03d}{suffix}"
                counter += 1
        return dest

    def _build_metadata(self, *, ns: dict[str, Any]) -> list[str]:
        """Build flattened metadata strings for the first output column."""
        from stoner_measurement.plugins.base_plugin import BasePlugin

        engine = self.sequence_engine
        if engine is None:
            raise RuntimeError("SaveCommand must be attached to a SequenceEngine before execute()")

        metadata: list[str] = []
        seen_ids: set[int] = set()
        for var_name in engine._plugin_var_names.values():  # noqa: SLF001
            plugin = ns.get(var_name)
            if isinstance(plugin, BasePlugin) and id(plugin) not in seen_ids:
                seen_ids.add(id(plugin))
                state = plugin.to_json()
                prefix = str(state.get("instance_name", var_name))
                metadata.extend(_flatten_to_metadata(state, prefix))

        values_catalog: dict[str, str] = ns.get("_values", {})
        for key, expr in values_catalog.items():
            try:
                val = self.eval(expr)
                metadata.extend(_flatten_to_metadata(val, key))
            except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                self.log.debug("Failed to evaluate value %r: %s", key, exc)
        return metadata

    def _build_data_columns(
        self,
        *,
        ns: dict[str, Any],
        save_mode: str,
        trace_keys: set[str] | None,
        data_source: str,
    ) -> list[tuple[str, np.ndarray]]:
        """Build numeric columns and headers for traces or DataFrame data mode."""
        if save_mode == "data":
            return self._build_data_mode_columns(ns=ns, data_source=data_source)
        return self._build_trace_mode_columns(ns=ns, trace_keys=trace_keys)

    def _build_data_mode_columns(
        self,
        *,
        ns: dict[str, Any],
        data_source: str,
    ) -> list[tuple[str, np.ndarray]]:
        """Build numeric columns from a state-control DataFrame including the index first."""
        if not data_source:
            self.log.warning("SaveCommand: no data_source configured for data mode")
            return []
        source_plugin = ns.get(data_source)
        if source_plugin is None:
            self.log.warning("SaveCommand: data_source %r not found in namespace", data_source)
            return []
        df = getattr(source_plugin, "data", None)
        if df is None:
            self.log.warning("SaveCommand: plugin %r has no 'data' attribute", data_source)
            return []
        if df.empty:
            self.log.debug("SaveCommand: plugin %r data is empty — writing headers only", data_source)

        columns: list[tuple[str, np.ndarray]] = []
        index_name = str(df.index.name) if df.index.name else "index"
        index_arr = np.fromiter(
            (_to_float_or_nan(value) for value in df.index),
            dtype=float,
            count=len(df.index),
        )
        columns.append((index_name, index_arr))
        for col_name in df.columns:
            arr = df[col_name].to_numpy(dtype=float, na_value=float("nan"))
            columns.append((str(col_name), arr))
        return columns

    def _build_trace_mode_columns(
        self,
        *,
        ns: dict[str, Any],
        trace_keys: set[str] | None,
    ) -> list[tuple[str, np.ndarray]]:
        """Build numeric columns from selected traces."""
        columns: list[tuple[str, np.ndarray]] = []
        traces_catalog: dict[str, str] = ns.get("_traces", {})
        for trace_key, expr in traces_catalog.items():
            if trace_keys is not None:
                if trace_key not in trace_keys:
                    continue
            elif not self.trace_selection.get(trace_key, True):
                continue
            try:
                trace_data = self.eval(expr)
                channel_name = trace_key.split(":", 1)[-1]
                for channel_attr in ("x", "y", "d", "e"):
                    arr: np.ndarray = getattr(trace_data, channel_attr, None)
                    if arr is None or len(arr) == 0:
                        continue
                    label = (trace_data.names or {}).get(channel_attr) or channel_attr
                    units = (trace_data.units or {}).get(channel_attr, "")
                    columns.append((f"{channel_name}:{label} ({units})", arr))
            except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                self.log.debug("Failed to evaluate trace %r: %s", trace_key, exc)
        return columns

    def _build_rows(
        self,
        *,
        metadata: list[str],
        columns: list[tuple[str, np.ndarray]],
    ) -> list[list[str]]:
        """Build row-wise TDI table data from metadata and numeric columns."""
        header_row = ["TDI Format 2.0"] + [col[0] for col in columns]
        max_data_len = max((len(col[1]) for col in columns), default=0)
        n_rows = max(len(metadata), max_data_len)
        rows: list[list[str]] = [header_row]
        for i in range(n_rows):
            meta_cell = metadata[i] if i < len(metadata) else ""
            data_cells = [str(col[1][i]) if i < len(col[1]) else "" for col in columns]
            rows.append([meta_cell] + data_cells)
        return rows

    def _write_rows(self, *, dest: pathlib.Path, rows: list[list[str]]) -> None:
        """Write the tab-delimited TDI rows to *dest*."""
        content = "\n".join("\t".join(row) for row in rows) + "\n"
        dest.write_text(content, encoding="utf-8")

    def __call__(
        self,
        *,
        trace: str | list[str] | None = None,
        data: str | None = None,
        no_overwrite: bool | None = None,
    ) -> None:
        """Invoke :meth:`execute`, forwarding any keyword-parameter overrides.

        The generated sequence script calls ``{instance_name}()`` (no args),
        which uses all configured defaults.  Passing keyword arguments allows
        callers to override trace selection, data source, or the no-overwrite
        flag for a single invocation without changing the plugin configuration.

        Keyword Parameters:
            trace (str | list[str] | None):
                Trace catalogue key(s) to save for this call.  See
                :meth:`execute` for full semantics.
            data (str | None):
                Instance name of the state-control plugin whose DataFrame to
                save for this call.  See :meth:`execute` for full semantics.
            no_overwrite (bool | None):
                Per-call no-overwrite override.  ``None`` uses the configured
                :attr:`no_overwrite` attribute.

        Raises:
            ValueError:
                If both *trace* and *data* are supplied.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> import tempfile, os
            >>> engine = SequenceEngine()
            >>> cmd = SaveCommand()
            >>> engine.add_plugin("save", cmd)
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     path = os.path.join(tmp, "out2.txt")
            ...     cmd.path_expr = repr(path)
            ...     cmd(no_overwrite=False)
            ...     first_line = open(path).readline().rstrip("\\n")
            >>> first_line.startswith("TDI Format 2.0")
            True
            >>> engine.shutdown()
        """
        self.execute(trace=trace, data=data, no_overwrite=no_overwrite)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a settings widget for the save command.

        Displays controls for the output path expression, save mode
        (``"traces"`` or ``"data"``), the no-overwrite flag, and
        mode-specific settings:

        * **Traces mode** — a scrollable list of per-trace checkboxes built
          from the ``_traces`` catalogue in the sequence engine namespace (or
          an empty list when the plugin is detached).
        * **Data mode** — a combo box listing all
          :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
          instances registered with the engine (or a plain text field when the
          plugin is detached).

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The settings widget for the *Settings* tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> from PyQt6.QtWidgets import QWidget
            >>> isinstance(SaveCommand().config_widget(), QWidget)
            True
        """
        from stoner_measurement.plugins.state_control import StateControlPlugin

        widget = QWidget(parent)
        outer_layout = QVBoxLayout(widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()

        # --- Path expression ---
        path_edit = QLineEdit(self.path_expr, widget)
        path_edit.setToolTip(
            "Python expression evaluated in the sequence engine namespace. "
            "Must produce a string file path. "
            "Example: f'data/run_{run_index:03d}.txt'"
        )

        def _apply_path() -> None:
            text = path_edit.text().strip()
            text = _ensure_string_expr(text)
            if text != path_edit.text():
                path_edit.setText(text)
            self.path_expr = text

        path_edit.editingFinished.connect(_apply_path)

        def _browse_path() -> None:
            import pathlib

            from stoner_measurement.ui.settings_dialog import (
                KEY_DEFAULT_DATA_DIR,
                make_app_settings,
            )

            settings = make_app_settings()
            data_dir = settings.value(KEY_DEFAULT_DATA_DIR, "", type=str)
            start_dir = data_dir if data_dir else ""
            path, _ = QFileDialog.getSaveFileName(
                widget,
                "Save Data File",
                start_dir,
                "Text Files (*.txt);;All Files (*)",
            )
            if path:
                p = pathlib.Path(path)
                if data_dir:
                    try:
                        rel = p.relative_to(data_dir)
                        expr = repr(str(rel))
                    except ValueError:
                        expr = repr(str(p))
                else:
                    expr = repr(str(p))
                path_edit.setText(expr)
                self.path_expr = expr

        browse_btn = QPushButton("Browse…", widget)
        browse_btn.setFixedWidth(80)
        browse_btn.setToolTip("Open a file dialog to choose the save path.")
        browse_btn.clicked.connect(_browse_path)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(path_edit)
        path_row.addWidget(browse_btn)
        form.addRow("Path expression:", path_row)

        # --- No-overwrite checkbox ---
        no_overwrite_check = QCheckBox(widget)
        no_overwrite_check.setChecked(self.no_overwrite)
        no_overwrite_check.setToolTip(
            "When checked, a numeric suffix (_001, _002, …) is added to the "
            "filename if the path already exists, preventing accidental overwrites."
        )

        def _apply_no_overwrite(state: int) -> None:
            self.no_overwrite = bool(state)

        no_overwrite_check.stateChanged.connect(_apply_no_overwrite)
        form.addRow("Never overwrite:", no_overwrite_check)

        # --- Mode selector ---
        mode_combo = QComboBox(widget)
        mode_combo.addItem("Traces", "traces")
        mode_combo.addItem("Data", "data")
        current_idx = mode_combo.findData(self.save_mode)
        if current_idx >= 0:
            mode_combo.setCurrentIndex(current_idx)
        mode_combo.setToolTip("Select whether to save trace channels or a state-control plugin's data.")
        form.addRow("Save mode:", mode_combo)

        form.addRow(
            QLabel(
                "<i>Expression is evaluated at runtime in the sequence engine namespace.</i>",
                widget,
            )
        )

        outer_layout.addLayout(form)

        # --- Mode-specific area (stacked: traces or data) ---
        from PyQt6.QtWidgets import QStackedWidget

        stack = QStackedWidget(widget)
        outer_layout.addWidget(stack)

        # Page 0: Traces — scrollable list of per-trace checkboxes.
        traces_scroll = QScrollArea()
        traces_scroll.setWidgetResizable(True)
        traces_container = QWidget()
        traces_layout = QVBoxLayout(traces_container)
        traces_layout.setContentsMargins(4, 4, 4, 4)

        ns = self.engine_namespace or {}
        traces_catalog: dict[str, str] = ns.get("_traces", {})

        if traces_catalog:
            for trace_key in traces_catalog:
                cb = QCheckBox(trace_key, traces_container)
                cb.setChecked(self.trace_selection.get(trace_key, True))
                cb.stateChanged.connect(lambda state, k=trace_key: self.trace_selection.update({k: bool(state)}))
                traces_layout.addWidget(cb)
        else:
            traces_layout.addWidget(QLabel("<i>No traces available.</i>", traces_container))

        traces_layout.addStretch()
        traces_container.setLayout(traces_layout)
        traces_scroll.setWidget(traces_container)
        stack.addWidget(traces_scroll)  # index 0

        # Page 1: Data — combo box of StateControlPlugin instances.
        data_widget = QWidget()
        data_form = QFormLayout(data_widget)

        engine = self.sequence_engine
        state_plugins: list[str] = []
        if engine is not None:
            for var_name in engine._plugin_var_names.values():  # noqa: SLF001
                plugin_inst = ns.get(var_name)
                if isinstance(plugin_inst, StateControlPlugin):
                    state_plugins.append(var_name)

        if state_plugins:
            source_combo = QComboBox(data_widget)
            for name in state_plugins:
                source_combo.addItem(name)
            idx = source_combo.findText(self.data_source)
            if idx >= 0:
                source_combo.setCurrentIndex(idx)
            elif state_plugins:
                # Auto-select the first available plugin.
                self.data_source = state_plugins[0]

            def _apply_source(index: int) -> None:
                if index >= 0:
                    self.data_source = source_combo.itemText(index)

            source_combo.currentIndexChanged.connect(_apply_source)
            data_form.addRow("Data source:", source_combo)
        else:
            source_edit = QLineEdit(self.data_source, data_widget)
            source_edit.setToolTip("Instance name of a StateControlPlugin to save data from.")

            def _apply_source_text() -> None:
                self.data_source = source_edit.text().strip()

            source_edit.editingFinished.connect(_apply_source_text)
            data_form.addRow("Data source:", source_edit)
            data_form.addRow(QLabel("<i>No state-control plugins available.</i>", data_widget))

        data_widget.setLayout(data_form)
        stack.addWidget(data_widget)  # index 1

        # Sync stack page to current mode and wire mode_combo changes.
        stack.setCurrentIndex(0 if self.save_mode == "traces" else 1)

        def _on_mode_changed(index: int) -> None:
            mode = mode_combo.itemData(index)
            if mode:
                self.save_mode = mode
            stack.setCurrentIndex(0 if self.save_mode == "traces" else 1)

        mode_combo.currentIndexChanged.connect(_on_mode_changed)

        outer_layout.addStretch()
        widget.setLayout(outer_layout)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise the save command configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict from :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                extended with ``"path_expr"``, ``"save_mode"``,
                ``"trace_selection"``, ``"data_source"``, and
                ``"no_overwrite"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> d = SaveCommand().to_json()
            >>> d["type"]
            'command'
            >>> "path_expr" in d
            True
            >>> "save_mode" in d
            True
            >>> "no_overwrite" in d
            True
        """
        d = super().to_json()
        d["path_expr"] = self.path_expr
        d["save_mode"] = self.save_mode
        d["trace_selection"] = self.trace_selection
        d["data_source"] = self.data_source
        d["no_overwrite"] = self.no_overwrite
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore configuration from a serialised dict.

        Args:
            data (dict[str, Any]):
                Serialised dict as produced by :meth:`to_json`.
        """
        if "path_expr" in data:
            self.path_expr = data["path_expr"]
        if "save_mode" in data:
            self.save_mode = data["save_mode"]
        if "trace_selection" in data:
            self.trace_selection = dict(data["trace_selection"])
        if "data_source" in data:
            self.data_source = data["data_source"]
        if "no_overwrite" in data:
            self.no_overwrite = bool(data["no_overwrite"])
