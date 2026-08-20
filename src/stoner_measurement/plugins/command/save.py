"""SaveCommand — built-in command plugin for writing data to disc.

:class:`SaveCommand` evaluates a Python expression to obtain a file path and
writes all or selected :class:`~stoner_measurement.core.TraceData`
tables from the sequence engine's shared ``_traces`` catalogue.  Instrument
measurements and collected state scan/sweep data use the same save path.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
from qtpy.QtWidgets import (
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

from stoner_measurement.core.sequence_metadata import sequence_metadata
from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.plugins.trace_catalog_ui import (
    bind_trace_catalog_updates,
    remap_catalog_text,
)

#: Regex matching the start of a Python string literal (with optional prefix).
_STRING_EXPR_RE = re.compile(r'^(?P<leading>\s*)(?P<prefix>[fFrRbBuU]*)(?P<quote>["\'])')


@dataclass(frozen=True)
class SavePayload:
    """Neutral data package passed from :class:`SaveCommand` to file writers."""

    metadata: list[str]
    columns: list[tuple[str, np.ndarray]]


class BaseSaveWriter:
    """Base class for concrete save-file writers."""

    format_id = "base"
    label = "Base"
    file_filter = "All Files (*)"
    supports_incremental = False
    aligns_metadata_with_data_rows = False

    @classmethod
    def available(cls) -> bool:
        """Return whether this writer can be used in the current environment."""
        return True

    @classmethod
    def unavailable_reason(cls) -> str:
        """Return a short explanation when :meth:`available` is false."""
        return ""

    def write(self, *, dest: pathlib.Path, payload: SavePayload) -> None:
        """Write *payload* to *dest*."""
        raise NotImplementedError

    def append_data_rows(
        self,
        *,
        dest: pathlib.Path,
        payload: SavePayload,
        start: int,
        stop: int,
    ) -> None:
        """Append data rows for incremental writers."""
        raise NotImplementedError(f"{self.label} does not support incremental appends")


class TdiSaveWriter(BaseSaveWriter):
    """Write the existing TDI Format 2.0 tab-delimited text layout."""

    format_id = "tdi"
    label = "TDI Format 2.0"
    file_filter = "TDI Text Files (*.txt);;All Files (*)"
    supports_incremental = True
    aligns_metadata_with_data_rows = True

    def write(self, *, dest: pathlib.Path, payload: SavePayload) -> None:
        rows = self.build_rows(payload=payload)
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join("\t".join(row) for row in rows) + "\n"
        dest.write_text(content, encoding="utf-8")

    def append_data_rows(
        self,
        *,
        dest: pathlib.Path,
        payload: SavePayload,
        start: int,
        stop: int,
    ) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for i in range(start, stop):
            data_cells = [str(col[1][i]) if i < len(col[1]) else "" for col in payload.columns]
            lines.append("\t".join([""] + data_cells))
        if not lines:
            return
        with dest.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def build_rows(self, *, payload: SavePayload) -> list[list[str]]:
        """Build row-wise TDI table data from metadata and numeric columns."""
        header_row = ["TDI Format 2.0"] + [col[0] for col in payload.columns]
        max_data_len = max((len(col[1]) for col in payload.columns), default=0)
        n_rows = max(len(payload.metadata), max_data_len)
        rows: list[list[str]] = [header_row]
        for i in range(n_rows):
            meta_cell = payload.metadata[i] if i < len(payload.metadata) else ""
            data_cells = [str(col[1][i]) if i < len(col[1]) else "" for col in payload.columns]
            rows.append([meta_cell] + data_cells)
        return rows


class NexusSaveWriter(BaseSaveWriter):
    """Write a NeXus-style HDF5 file with NXentry and NXdata groups."""

    format_id = "nexus"
    label = "NeXus/HDF5"
    file_filter = "NeXus Files (*.nxs *.h5 *.hdf5);;All Files (*)"
    supports_incremental = True

    @classmethod
    def available(cls) -> bool:
        try:
            return importlib.import_module("h5py") is not None
        except ImportError:
            return False

    @classmethod
    def unavailable_reason(cls) -> str:
        return "NeXus export requires the optional 'h5py' package."

    def write(self, *, dest: pathlib.Path, payload: SavePayload) -> None:
        try:
            import h5py
        except ImportError as exc:
            raise RuntimeError(self.unavailable_reason()) from exc

        dest.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(dest, "w") as handle:
            handle.attrs["default"] = "entry"
            handle.attrs["file_format"] = "NeXus"
            handle.attrs["creator"] = "stoner_measurement"
            handle.attrs["stoner_measurement_format"] = "nexus-1"

            entry = handle.create_group("entry")
            entry.attrs["NX_class"] = "NXentry"
            entry.attrs["default"] = "data"
            data_group = entry.create_group("data")
            data_group.attrs["NX_class"] = "NXdata"
            if payload.columns:
                signal_name = self._dataset_name(payload.columns[1][0] if len(payload.columns) > 1 else payload.columns[0][0])
                data_group.attrs["signal"] = signal_name
                if len(payload.columns) > 1:
                    data_group.attrs["axes"] = [self._dataset_name(payload.columns[0][0])]

            used_names: set[str] = set()
            for header, values in payload.columns:
                name = self._unique_dataset_name(header, used_names)
                dataset = data_group.create_dataset(
                    name,
                    data=np.asarray(values, dtype=float),
                    maxshape=(None,),
                    chunks=True,
                )
                label, units = self._split_header(header)
                dataset.attrs["long_name"] = label
                dataset.attrs["original_name"] = header
                if units:
                    dataset.attrs["units"] = units

            metadata_group = entry.create_group("metadata")
            metadata_group.attrs["NX_class"] = "NXcollection"
            string_dtype = h5py.string_dtype(encoding="utf-8")
            metadata_group.create_dataset(
                "flattened",
                data=np.asarray(payload.metadata, dtype=object),
                dtype=string_dtype,
            )

    def append_data_rows(
        self,
        *,
        dest: pathlib.Path,
        payload: SavePayload,
        start: int,
        stop: int,
    ) -> None:
        try:
            import h5py
        except ImportError as exc:
            raise RuntimeError(self.unavailable_reason()) from exc

        if stop <= start:
            return

        with h5py.File(dest, "a") as handle:
            data_group = handle["entry"]["data"]
            used_names: set[str] = set()
            for header, values in payload.columns:
                name = self._unique_dataset_name(header, used_names)
                dataset = data_group[name]
                new_values = np.asarray(values[start:stop], dtype=float)
                old_size = dataset.shape[0]
                dataset.resize((old_size + len(new_values),))
                dataset[old_size:] = new_values

    def _unique_dataset_name(self, header: str, used_names: set[str]) -> str:
        base = self._dataset_name(header)
        name = base
        counter = 1
        while name in used_names:
            name = f"{base}_{counter}"
            counter += 1
        used_names.add(name)
        return name

    def _dataset_name(self, header: str) -> str:
        label, _units = self._split_header(header)
        name = re.sub(r"\W+", "_", label).strip("_").lower()
        return name or "data"

    def _split_header(self, header: str) -> tuple[str, str]:
        match = re.match(r"^(?P<label>.*)\s+\((?P<units>.*)\)$", header)
        if match:
            return match.group("label"), match.group("units")
        return header, ""


SAVE_WRITERS: dict[str, type[BaseSaveWriter]] = {
    writer.format_id: writer
    for writer in (
        TdiSaveWriter,
        NexusSaveWriter,
    )
}


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


def _literal_path_expression_value(expression: str) -> str | None:
    """Return literal path text without evaluating f-string replacements.

    Existing ``f`` prefixes are removed while preserving a compatible raw
    prefix, allowing the preference root and configured filename to be joined
    before the complete path is interpolated. Non-literal expressions return
    ``None`` and remain handled by the normal runtime evaluator.
    """
    match = _STRING_EXPR_RE.match(expression)
    if match is None:
        return None
    prefix = match.group("prefix")
    without_f = "".join(char for char in prefix if char.lower() != "f")
    literal = f"{expression[:match.start('prefix')]}{without_f}{expression[match.end('prefix'):]}"
    try:
        value = ast.literal_eval(literal)
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) else None


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
        for k in sorted(obj, key=str):
            v = obj[k]
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
    """Save traces or collected table data to a text file.

    Use this command when you want to write the current measurement results to
    disk from inside a sequence. It can save either:

    * one or more trace datasets from the trace catalogue, including collected
      state-scan and state-sweep tables.

    In the configuration panel you select which trace tables to save and
    provide a **path expression**. The path
    can be a fixed filename or a Python expression that builds a filename from
    current sequence variables, for example::

        "f'data/run_{run_index:03d}.txt'"

    By default, existing files are not overwritten. Instead, if the chosen
    filename already exists, a numeric suffix is added automatically.

    The output is a **TDI Format 2.0** tab-delimited text file structured as
    follows:

    * The top-left cell (row 0, column 0) contains ``"TDI Format 2.0"``.
    * The remaining cells of row 0 are trace column headers with the form
      ``"{channel_name}:{axis_label} ({axis_units})"``.
    * The remaining cells of column 0 (rows 1 onwards) hold a flattened
      metadata snapshot. ``sequence`` is the depth-first list of dotted
      instance paths; each path's final component names a top-level serialised
      configuration item, alongside evaluated ``outputs`` scalar readings.
      Nested dicts are flattened using ``.`` separators; list items use
      ``[{index}]`` notation.
    * The remaining cells (rows 1 onwards, columns 1 onwards) contain the
      numerical data from each column.

    If a parent directory does not exist it is created automatically.  When
    :attr:`no_overwrite` is ``True`` (the default) and the resolved path
    already exists, a numeric suffix (``_001``, ``_002``, …) is inserted
    before the file extension until a free filename is found.

    Attributes:
        path_expr (str):
            Python expression string that evaluates to the filename or path.
            Plain or raw string literals containing ``{`` are automatically
            evaluated as f-strings, so an explicit ``f`` prefix is optional.
            Defaults to ``"'data/output.txt'"``. A relative value is first
            joined to the default data directory configured in the application
            settings, then the complete path is evaluated for replacement
            fields. This allows placeholders in either the preference-sourced
            directory or this command's filename. If no default data directory
            is set the path is relative to the current working directory.
        trace_selection (dict[str, bool]):
            Per-trace enable flags for trace mode.  Keys are trace catalogue
            keys (``"{instance_name}:{channel_name}"``).  A key mapping to
            ``True`` (or absent from the dict) means the trace is saved;
            mapping to ``False`` means it is excluded.  An empty dict (the
            default) saves all available traces.
        no_overwrite (bool):
            When ``True`` (the default) an existing file is never overwritten;
            instead a numeric suffix is appended to the stem until a free
            filename is found.
        save_format (str):
            Registered writer identifier for the output file format. Defaults
            to ``"tdi"``. ``"nexus"`` writes a NeXus/HDF5 file when ``h5py`` is
            available.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command import SaveCommand
        >>> cmd = SaveCommand()
        >>> cmd.name
        'Save'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        True
        >>> cmd.no_overwrite
        True
    """

    def __init__(self, parent=None) -> None:
        """Initialise with default configuration."""
        super().__init__(parent)
        self.path_expr: str = "'data/output.txt'"
        self.trace_selection: dict[str, bool] = {}
        self.no_overwrite: bool = True
        self.save_format: str = TdiSaveWriter.format_id
        self.incremental_save: bool = False
        self._incremental_files: dict[str, dict[str, str | int]] = {}

    @property
    def has_lifecycle(self) -> bool:
        """Participate in lifecycle setup so each script starts a new save session."""
        return True

    def connect(self) -> None:
        """Start a new save session, forgetting incremental files from earlier runs."""
        self._incremental_files.clear()

    def configure(self) -> None:
        """No-op lifecycle hook; Save has no hardware to configure."""

    def disconnect(self) -> None:
        """No-op lifecycle hook; Save has no hardware to disconnect."""

    @property
    def name(self) -> str:
        """Unique identifier for the save command.

        Returns:
            (str):
                ``"Save"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
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
        no_overwrite: bool | None = None,
    ) -> None:
        """Evaluate :attr:`path_expr` and write data to disc.

        Evaluates :attr:`path_expr` in the sequence engine namespace to obtain
        the output file path, creates any required parent directories, and
        writes a TDI Format 2.0 tab-delimited text file.

        The keyword parameters allow per-call overrides of the configured
        settings without permanently modifying the plugin:

        * ``trace`` optionally selects one or more trace catalogue keys.
        * ``no_overwrite`` overrides :attr:`no_overwrite` for this call only.

        When the effective no-overwrite flag is ``True`` and the resolved path
        already exists, a numeric suffix (``_001``, ``_002``, …) is appended
        before the file extension until a free filename is found.

        The x axis and every DataFrame column of each selected trace contributes
        one output column.  Without the ``trace`` kwarg the selection
        is driven by :attr:`trace_selection` (absent key → enabled).  When
        ``trace`` is supplied it must be a trace catalogue key or a list of
        trace catalogue keys; only those traces are saved.  Column headers have
        the form ``"{channel_name}:{axis_label} ({axis_units})"``.

        The file layout is:

        * **Row 0** — ``"TDI Format 2.0"`` followed by one column header per
          data column.
        * **Column 0 (rows 1+)** — flattened metadata entries of the form
          ``"{key}{typename}={repr(value)}"`` collected from the ``to_json()``
          state of each plugin instance in the current sequence. ``sequence``
          stores depth-first dotted instance paths so nested steps retain their
          structure; each final path component maps to its serialised
          configuration at the metadata root, and ``outputs`` maps catalogue
          keys to evaluated current scalar readings.
        * **Remaining cells** — numerical data from each data column.

        Keyword Parameters:
            trace (str | list[str] | None):
                One or more trace catalogue keys
                (``"{instance_name}:{channel_name}"`` format) to save.  When
                supplied, only the listed traces are saved regardless of
                :attr:`trace_selection`.
                Defaults to ``None`` (use configured :attr:`trace_selection`).
            no_overwrite (bool | None):
                When ``True``, prevent overwriting an existing file (see
                :attr:`no_overwrite`).  ``None`` (default) uses the configured
                :attr:`no_overwrite` attribute.

        Raises:
            RuntimeError:
                If the plugin is not attached to a sequence engine.
            TypeError:
                If :attr:`path_expr` does not evaluate to a string.
            OSError:
                If the file cannot be written (e.g. due to permissions).

        Examples:
            >>> from qtpy.QtWidgets import QApplication
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
        trace_keys, effective_no_overwrite = self._resolve_effective_options(
            trace=trace, no_overwrite=no_overwrite
        )
        payload = self.build_payload(trace_keys=trace_keys)
        writer = self._writer()

        if self.incremental_save and writer.supports_incremental:
            dest = self._write_incremental_data_rows(
                payload=payload,
                writer=writer,
                no_overwrite=effective_no_overwrite,
            )
        else:
            original = self._resolve_original_destination()
            dest = self._next_available_destination(original) if effective_no_overwrite else original
            writer.write(dest=dest, payload=payload)
            self._record_saved_file(
                original=original,
                dest=dest,
                data_rows=self._data_row_count(payload.columns),
            )
        self.log.info("Data saved to %s", dest)

    def build_payload(self, *, trace_keys: set[str] | None = None) -> SavePayload:
        """Take an independent snapshot of selected data ready for writing.

        The returned arrays are copies, so a caller may pass the payload to a
        background writer without retaining a live view of data that the
        sequence engine may continue to update.

        Keyword Args:
            trace_keys (set[str] | None):
                Trace catalogue keys to include. ``None`` applies the command's
                configured :attr:`trace_selection` mapping.

        Returns:
            (SavePayload):
                Metadata and numeric columns detached from the live namespace.
        """
        ns = self.engine_namespace
        metadata = self._build_metadata(ns=ns)
        columns = self._build_trace_columns(ns=ns, trace_keys=trace_keys)
        return SavePayload(metadata=metadata, columns=columns)

    def _writer(self) -> BaseSaveWriter:
        """Return the configured save writer instance."""
        writer_cls = SAVE_WRITERS.get(self.save_format)
        if writer_cls is None:
            raise ValueError(f"Unknown save format {self.save_format!r}")
        if not writer_cls.available():
            raise RuntimeError(writer_cls.unavailable_reason())
        return writer_cls()

    def _resolve_effective_options(
        self,
        *,
        trace: str | list[str] | None,
        no_overwrite: bool | None,
    ) -> tuple[set[str] | None, bool]:
        """Resolve per-call overrides into effective save settings."""
        trace_keys = {trace} if isinstance(trace, str) else set(trace) if trace is not None else None
        effective_no_overwrite = self.no_overwrite if no_overwrite is None else no_overwrite
        return trace_keys, effective_no_overwrite

    def _resolve_destination(self, *, no_overwrite: bool) -> pathlib.Path:
        """Evaluate :attr:`path_expr`, resolve to a writable path, and apply no-overwrite."""
        dest = self._resolve_original_destination()
        if no_overwrite:
            dest = self._next_available_destination(dest)
        return dest

    def _resolve_original_destination(self) -> pathlib.Path:
        """Join the configured root and filename, then evaluate the complete path."""
        path_val = _literal_path_expression_value(self.path_expr)
        if path_val is None:
            path_val = self.eval(self.path_expr)
        if not isinstance(path_val, str):
            raise TypeError(f"SaveCommand.path_expr must evaluate to a str, got {type(path_val).__name__!r}")

        dest = pathlib.Path(path_val)
        if not dest.is_absolute():
            from stoner_measurement.app_config import default_data_directory

            data_dir = default_data_directory()
            if data_dir:
                dest = pathlib.Path(data_dir) / dest

        full_path = self.eval(repr(str(dest)))
        if not isinstance(full_path, str):
            raise TypeError(
                "SaveCommand complete path must evaluate to a str, "
                f"got {type(full_path).__name__!r}"
            )
        return pathlib.Path(full_path)

    def _next_available_destination(self, dest: pathlib.Path) -> pathlib.Path:
        """Return *dest* or a numeric-suffixed variant that does not exist."""
        if not dest.exists():
            return dest

        stem = dest.stem
        suffix = dest.suffix
        parent_dir = dest.parent
        counter = 1
        while dest.exists():
            dest = parent_dir / f"{stem}_{counter:03d}{suffix}"
            counter += 1
        return dest

    def _build_metadata(self, *, ns: dict[str, Any]) -> list[str]:
        """Snapshot the current sequence configuration and evaluated outputs."""
        engine = self.sequence_engine
        if engine is None:
            raise RuntimeError("SaveCommand must be attached to a SequenceEngine before execute()")

        sequence_view = ns.get("sequence")
        steps = getattr(sequence_view, "steps", None)
        if steps is None:
            steps = engine.step_plugins()
        metadata = sequence_metadata(steps)
        outputs: dict[str, Any] = {}
        values_catalog: dict[str, str] = ns.get("_values", {})
        for key, expr in values_catalog.items():
            try:
                outputs[key] = self.eval(expr)
            except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                self.log.debug("Failed to evaluate value %r: %s", key, exc)
        metadata["outputs"] = outputs
        return _flatten_to_metadata(metadata)

    def _build_trace_columns(
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
                for column_name in trace_data.df.columns:
                    values = trace_data.df[column_name].to_numpy(dtype=float, copy=True)
                    label = (trace_data.names or {}).get(column_name) or str(column_name)
                    units = (trace_data.units or {}).get(column_name, "")
                    columns.append((f"{trace_key}:{label} ({units})", values))
            except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                self.log.debug("Failed to evaluate trace %r: %s", trace_key, exc)
        return columns

    def _write_incremental_data_rows(
        self,
        *,
        payload: SavePayload,
        writer: BaseSaveWriter,
        no_overwrite: bool,
    ) -> pathlib.Path:
        """Write or append data-mode rows according to the incremental save state."""
        original = self._resolve_original_destination()
        original_key = str(original)
        entry = self._incremental_files.get(original_key)
        is_new_file = entry is None
        if entry is None:
            actual = self._next_available_destination(original) if no_overwrite else original
            entry = {"actual_filename": str(actual), "rows_saved": 0}
            self._incremental_files[original_key] = entry

        dest = pathlib.Path(str(entry["actual_filename"]))
        rows_saved = int(entry["rows_saved"])
        meta_rows = len(payload.metadata)
        data_rows = self._data_row_count(payload.columns)

        if is_new_file or (writer.aligns_metadata_with_data_rows and rows_saved < meta_rows):
            writer.write(dest=dest, payload=payload)
        elif data_rows > rows_saved:
            writer.append_data_rows(dest=dest, payload=payload, start=rows_saved, stop=data_rows)

        entry["rows_saved"] = data_rows
        return dest

    def _record_saved_file(
        self,
        *,
        original: pathlib.Path,
        dest: pathlib.Path,
        data_rows: int,
    ) -> None:
        """Track the latest non-incremental data save for the current original filename."""
        self._incremental_files[str(original)] = {
            "actual_filename": str(dest),
            "rows_saved": data_rows,
        }

    def _data_row_count(self, columns: list[tuple[str, np.ndarray]]) -> int:
        """Return the number of data rows available across the supplied columns."""
        return max((len(col[1]) for col in columns), default=0)

    def __call__(
        self,
        *,
        trace: str | list[str] | None = None,
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
            >>> from qtpy.QtWidgets import QApplication
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
        self.execute(trace=trace, no_overwrite=no_overwrite)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a settings widget for the save command.

        Displays controls for the output path expression, output file format,
        incremental and no-overwrite flags, and a scrollable list of per-trace
        checkboxes built from the ``_traces`` catalogue in the sequence engine
        namespace (or an empty list when the plugin is detached).

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The settings widget for the *Settings* tab.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> from qtpy.QtWidgets import QWidget
            >>> isinstance(SaveCommand().config_widget(), QWidget)
            True
        """
        widget = QWidget(parent)
        outer_layout = QVBoxLayout(widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        self._build_path_form_row(widget, form)
        self._build_no_overwrite_row(widget, form)
        self._build_format_selector(widget, form)
        self._build_incremental_row(widget, form)
        outer_layout.addLayout(form)
        outer_layout.addWidget(self._build_traces_page())

        outer_layout.addStretch()
        widget.setLayout(outer_layout)
        return widget

    def _build_path_form_row(self, widget: QWidget, form: QFormLayout) -> None:
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
            from stoner_measurement.app_config import default_data_directory

            data_dir = default_data_directory()
            start_dir = data_dir if data_dir else ""
            path, _ = QFileDialog.getSaveFileName(
                widget,
                "Save Data File",
                start_dir,
                self._writer_filter_string(),
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
        browse_btn.setMinimumWidth(80)
        browse_btn.setToolTip("Open a file dialog to choose the save path.")
        browse_btn.clicked.connect(_browse_path)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.addWidget(path_edit)
        path_row.addWidget(browse_btn)
        form.addRow("Path expression:", path_row)

    def _writer_filter_string(self) -> str:
        """Return the QFileDialog filter string for registered save writers."""
        filters = [writer.file_filter for writer in SAVE_WRITERS.values()]
        return ";;".join(dict.fromkeys(filters))

    def _build_no_overwrite_row(self, widget: QWidget, form: QFormLayout) -> None:
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

    def _build_format_selector(self, widget: QWidget, form: QFormLayout) -> QComboBox:
        format_combo = QComboBox(widget)
        for writer_id, writer_cls in SAVE_WRITERS.items():
            label = writer_cls.label
            if not writer_cls.available():
                label = f"{label} (unavailable)"
            format_combo.addItem(label, writer_id)
            item_idx = format_combo.count() - 1
            if not writer_cls.available():
                format_combo.model().item(item_idx).setEnabled(False)
                format_combo.setItemData(item_idx, writer_cls.unavailable_reason(), role=3)

        current_idx = format_combo.findData(self.save_format)
        if current_idx >= 0:
            format_combo.setCurrentIndex(current_idx)
        format_combo.setToolTip("Select the file format used for saved measurement data.")

        def _apply_format(index: int) -> None:
            writer_id = format_combo.itemData(index)
            if writer_id:
                self.save_format = writer_id

        format_combo.currentIndexChanged.connect(_apply_format)
        form.addRow("File format:", format_combo)
        return format_combo

    def _build_incremental_row(self, widget: QWidget, form: QFormLayout) -> None:
        incremental_check = QCheckBox(widget)
        incremental_check.setChecked(self.incremental_save)
        incremental_check.setToolTip("Append only newly available rows on repeated saves.")
        incremental_check.stateChanged.connect(
            lambda state: setattr(self, "incremental_save", bool(state))
        )
        form.addRow("Save incrementally:", incremental_check)

    def _build_traces_page(self) -> QScrollArea:
        traces_scroll = QScrollArea()
        traces_scroll.setWidgetResizable(True)
        traces_container = QWidget()
        traces_layout = QVBoxLayout(traces_container)
        traces_layout.setContentsMargins(4, 4, 4, 4)

        def _populate_traces(traces_catalog: dict[str, str]) -> None:
            trace_keys = list(traces_catalog)
            for old_key in list(self.trace_selection):
                if old_key in traces_catalog:
                    continue
                renamed_key = remap_catalog_text(old_key, trace_keys)
                if renamed_key is not None and renamed_key not in self.trace_selection:
                    self.trace_selection[renamed_key] = self.trace_selection.pop(old_key)
            while traces_layout.count():
                item = traces_layout.takeAt(0)
                child = item.widget()
                if child is not None:
                    child.deleteLater()
            if traces_catalog:
                for trace_key in traces_catalog:
                    checkbox = QCheckBox(trace_key, traces_container)
                    checkbox.setChecked(self.trace_selection.get(trace_key, True))
                    checkbox.stateChanged.connect(
                        lambda state, key=trace_key: self.trace_selection.update(
                            {key: bool(state)}
                        )
                    )
                    traces_layout.addWidget(checkbox)
            else:
                traces_layout.addWidget(QLabel("<i>No traces available.</i>", traces_container))
            traces_layout.addStretch()

        traces_catalog: dict[str, str] = self.engine_namespace.get("_traces", {})
        _populate_traces(traces_catalog)
        traces_container.setLayout(traces_layout)
        traces_scroll.setWidget(traces_container)
        bind_trace_catalog_updates(self, traces_scroll, _populate_traces)
        return traces_scroll

    def to_json(self) -> dict[str, Any]:
        """Serialise the save command configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict from :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                extended with ``"path_expr"``, ``"trace_selection"``,
                ``"no_overwrite"``, ``"incremental_save"``, and
                ``"save_format"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> d = SaveCommand().to_json()
            >>> d["type"]
            'command'
            >>> "path_expr" in d
            True
            >>> "trace_selection" in d
            True
            >>> "no_overwrite" in d
            True
        """
        d = super().to_json()
        d["path_expr"] = self.path_expr
        d["trace_selection"] = self.trace_selection
        d["no_overwrite"] = self.no_overwrite
        d["save_format"] = self.save_format
        d["incremental_save"] = self.incremental_save
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore configuration from a serialised dict.

        Args:
            data (dict[str, Any]):
                Serialised dict as produced by :meth:`to_json`.
        """
        if "path_expr" in data:
            self.path_expr = data["path_expr"]
        if "trace_selection" in data:
            self.trace_selection = dict(data["trace_selection"])
        if "no_overwrite" in data:
            self.no_overwrite = bool(data["no_overwrite"])
        if "save_format" in data:
            self.save_format = str(data["save_format"])
        if "incremental_save" in data:
            self.incremental_save = bool(data["incremental_save"])
        self._incremental_files = {}
