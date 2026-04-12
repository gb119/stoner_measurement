"""SaveCommand — built-in command plugin for writing data to disc.

:class:`SaveCommand` is a concrete :class:`CommandPlugin` that evaluates a
Python expression to obtain a file path and then writes the current trace and
scalar value catalogs from the sequence engine namespace to a TDI Format 2.0
tab-delimited text file.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin


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


class SaveCommand(CommandPlugin):
    """Command plugin that saves current trace and configuration data to disc.

    The save path is given as a Python expression string (``path_expr``) that
    is evaluated against the sequence engine namespace at runtime using
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`.  This
    allows the path to incorporate namespace variables such as loop counters,
    timestamps, or instrument settings::

        "f'data/run_{run_index:03d}.txt'"

    The output is a **TDI Format 2.0** tab-delimited text file structured as
    follows:

    * The top-left cell (row 0, column 0) contains ``"TDI Format 2.0"``.
    * The remaining cells of row 0 are column headers for each trace channel
      in the form ``"{trace_key}:{channel_label} ({channel_units})"``, one
      column per non-empty channel (``x``, ``y``, ``d``, ``e``) from each
      entry in the ``_traces`` namespace catalog.
    * The remaining cells of column 0 (rows 1 onwards) hold flattened
      key-value metadata derived from two sources:

      1. The ``to_json()`` state of every plugin registered with the engine,
         formatted as ``{key}{typename}={repr(value)}``.  Nested dicts are
         flattened using ``.`` separators; list items use ``[{index}]``
         notation.
      2. The current scalar readings from the ``_values`` catalog, formatted
         identically.

    * The remaining cells (rows 1 onwards, columns 1 onwards) contain the
      numerical data from each trace channel.

    If a parent directory does not exist it is created automatically.

    Attributes:
        path_expr (str):
            Python expression string that evaluates to the file path.
            Defaults to ``"'data/output.txt'"``.

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
    """

    def __init__(self, parent=None) -> None:
        """Initialise with a default path expression."""
        super().__init__(parent)
        self.path_expr: str = "'data/output.txt'"

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

    def execute(self) -> None:
        """Evaluate :attr:`path_expr` and write trace and configuration data to disc.

        Evaluates :attr:`path_expr` in the sequence engine namespace to obtain
        the output file path, creates any required parent directories, and
        writes a TDI Format 2.0 tab-delimited text file.

        The file layout is:

        * **Row 0** — ``"TDI Format 2.0"`` followed by one column header per
          non-empty trace channel in the form
          ``"{trace_key}:{channel_label} ({channel_units})"``.
        * **Column 0 (rows 1+)** — flattened metadata entries of the form
          ``"{key}{typename}={repr(value)}"`` collected from the ``to_json()``
          state of every plugin registered with the engine, followed by the
          current scalar readings from the ``_values`` catalog.
        * **Remaining cells** — numerical data from each trace channel in the
          corresponding column.

        Raises:
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
        import pathlib

        import numpy as np

        from stoner_measurement.plugins.base_plugin import BasePlugin

        path_val = self.eval(self.path_expr)
        if not isinstance(path_val, str):
            raise TypeError(
                f"SaveCommand.path_expr must evaluate to a str, got {type(path_val).__name__!r}"
            )
        dest = pathlib.Path(path_val)
        dest.parent.mkdir(parents=True, exist_ok=True)

        ns = self.engine_namespace
        engine = self.sequence_engine

        # ------------------------------------------------------------------
        # Build metadata entries for column 0.
        # ------------------------------------------------------------------

        metadata: list[str] = []

        # 1. Flattened to_json() state from every registered base plugin.
        seen_ids: set[int] = set()
        for var_name in engine._plugin_var_names.values():  # noqa: SLF001
            plugin = ns.get(var_name)
            if isinstance(plugin, BasePlugin) and id(plugin) not in seen_ids:
                seen_ids.add(id(plugin))
                state = plugin.to_json()
                prefix = str(state.get("instance_name", var_name))
                metadata.extend(_flatten_to_metadata(state, prefix))

        # 2. Current scalar readings from the _values catalog.
        values_catalog: dict[str, str] = ns.get("_values", {})
        for key, expr in values_catalog.items():
            try:
                val = self.eval(expr)
                metadata.extend(_flatten_to_metadata(val, key))
            except Exception as exc:  # noqa: BLE001
                self.log.debug("Failed to evaluate value %r: %s", key, exc)

        # ------------------------------------------------------------------
        # Build trace-data columns.
        # ------------------------------------------------------------------

        traces_catalog: dict[str, str] = ns.get("_traces", {})
        # Each entry: (header_string, 1-D numpy array)
        columns: list[tuple[str, np.ndarray]] = []
        for trace_key, expr in traces_catalog.items():
            try:
                trace_data = self.eval(expr)
                for channel_attr in ("x", "y", "d", "e"):
                    arr: np.ndarray = getattr(trace_data, channel_attr, None)
                    if arr is None or len(arr) == 0:
                        continue
                    label = (trace_data.names or {}).get(channel_attr) or channel_attr
                    units = (trace_data.units or {}).get(channel_attr, "")
                    columns.append((f"{trace_key}:{label} ({units})", arr))
            except Exception as exc:  # noqa: BLE001
                self.log.debug("Failed to evaluate trace %r: %s", trace_key, exc)

        # ------------------------------------------------------------------
        # Assemble and write the TDI Format 2.0 table.
        # ------------------------------------------------------------------

        header_row = ["TDI Format 2.0"] + [col[0] for col in columns]

        max_data_len = max((len(col[1]) for col in columns), default=0)
        n_rows = max(len(metadata), max_data_len)

        rows: list[list[str]] = [header_row]
        for i in range(n_rows):
            meta_cell = metadata[i] if i < len(metadata) else ""
            data_cells = [str(col[1][i]) if i < len(col[1]) else "" for col in columns]
            rows.append([meta_cell] + data_cells)

        content = "\n".join("\t".join(row) for row in rows) + "\n"
        dest.write_text(content, encoding="utf-8")
        self.log.info("Data saved to %s", dest)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a settings widget with a path-expression editor.

        Displays a :class:`~PyQt6.QtWidgets.QFormLayout` containing a
        :class:`~PyQt6.QtWidgets.QLineEdit` that accepts a Python expression
        string for the output file path, and a brief description label.

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
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        path_edit = QLineEdit(self.path_expr, widget)
        path_edit.setToolTip(
            "Python expression evaluated in the sequence engine namespace. "
            "Must produce a string file path. "
            "Example: f'data/run_{run_index:03d}.txt'"
        )

        def _apply() -> None:
            self.path_expr = path_edit.text().strip()

        path_edit.editingFinished.connect(_apply)
        layout.addRow("Path expression:", path_edit)
        layout.addRow(
            QLabel(
                "<i>Expression is evaluated at runtime in the sequence "
                "engine namespace.</i>",
                widget,
            )
        )
        widget.setLayout(layout)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise the save command configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict from :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                extended with ``"path_expr"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> d = SaveCommand().to_json()
            >>> d["type"]
            'command'
            >>> "path_expr" in d
            True
        """
        d = super().to_json()
        d["path_expr"] = self.path_expr
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore :attr:`path_expr` from a serialised dict.

        Args:
            data (dict[str, Any]):
                Serialised dict as produced by :meth:`to_json`.
        """
        if "path_expr" in data:
            self.path_expr = data["path_expr"]
