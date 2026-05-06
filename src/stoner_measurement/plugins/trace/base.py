"""TracePlugin — abstract base class for plugins that collect (x, y) traces.

Trace plugins acquire a complete sequence of data points from one or more
instrument channels.  Examples include current-voltage characteristics,
frequency sweeps, and time-series captures.

Each measurement trace is represented by a :class:`TraceData` object that is
backed by a :class:`pandas.DataFrame`.  The independent variable (*x*) is
stored as the index; one or more dependent variable columns are stored as
DataFrame columns, each annotated with a *role* string that describes what the
column contains (primary y data, z data, error bars, etc.).

All TracePlugin subclasses share a standard lifecycle API used by the sequence
engine:

1. :meth:`~TracePlugin.connect` — open instrument connections and verify the
   instrument identity.
2. :meth:`~TracePlugin.configure` — push plugin settings to the instrument.
3. :meth:`~TracePlugin.measure` — trigger and collect the complete multipoint
   trace, returning all ``(channel, x, y)`` points as a list.
4. :meth:`~TracePlugin.disconnect` — cleanly release all reserved resources.

Status during these operations is reported via the :attr:`~TracePlugin.status`
property and the :attr:`~TracePlugin.status_changed` signal using the
:class:`TraceStatus` enum.
"""

from __future__ import annotations

import enum
from abc import abstractmethod
from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
import pandas as pd
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.plugins.base_plugin import BasePlugin, _ABCQObjectMeta
from stoner_measurement.scan import (
    ArbitraryFunctionScanGenerator,
    BaseScanGenerator,
    FunctionScanGenerator,
    ListScanGenerator,
    RampScanGenerator,
    SteppedScanGenerator,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Column role constants
# ---------------------------------------------------------------------------

COLUMN_ROLE_Y: str = "y"
"""Role tag identifying a column as the primary dependent variable."""

COLUMN_ROLE_Z: str = "z"
"""Role tag identifying a column as a secondary dependent variable."""

COLUMN_ROLE_D: str = "d"
"""Role tag identifying a column as x-axis uncertainty (error bar)."""

COLUMN_ROLE_E: str = "e"
"""Role tag identifying a column as y-axis uncertainty (error bar)."""

COLUMN_ROLE_F: str = "f"
"""Role tag identifying a column as z-axis uncertainty (error bar)."""

_VALID_ROLES: frozenset[str] = frozenset(
    {COLUMN_ROLE_Y, COLUMN_ROLE_Z, COLUMN_ROLE_D, COLUMN_ROLE_E, COLUMN_ROLE_F}
)


class TraceData:
    """Container for a measurement trace backed by a :class:`pandas.DataFrame`.

    Each :class:`TraceData` instance corresponds to one named channel produced by a
    :class:`TracePlugin`.  The independent variable (*x*) is stored as the DataFrame
    index; one or more dependent variable columns are stored as DataFrame columns,
    each annotated with a *role* string (see the ``COLUMN_ROLE_*`` constants).

    Two construction paths are supported:

    * **Legacy / backward-compatible path** — pass ``x``, ``y``, and optionally
      ``d`` (x-error) and ``e`` (y-error) as NumPy arrays, together with optional
      ``names`` and ``units`` dicts keyed by ``"x"``, ``"y"``, ``"d"``, ``"e"``.
      A :class:`~pandas.DataFrame` is built automatically.
    * **New-style path** — pass a pre-built :class:`~pandas.DataFrame` as ``df``
      (index = x values, columns = dependent variable data) together with a
      ``column_roles`` mapping and optional ``names`` / ``units`` dicts.  The
      ``x``, ``y``, ``d``, and ``e`` positional arguments are ignored when ``df``
      is provided.

    Attributes:
        column_roles (dict[str, str]):
            Mapping from column name to role string.  Valid roles are the module
            constants :data:`COLUMN_ROLE_Y`, :data:`COLUMN_ROLE_Z`,
            :data:`COLUMN_ROLE_D`, :data:`COLUMN_ROLE_E`, and
            :data:`COLUMN_ROLE_F`.
        names (dict[str, str]):
            Mapping from axis/column identifier to a human-readable display name.
            Key ``"x"`` addresses the index (independent variable); all other keys
            are column names.  Legacy code may use ``{"x": …, "y": …, "d": …,
            "e": …}`` and those keys continue to work.
        units (dict[str, str]):
            Mapping from axis/column identifier to a physical unit string.  Same
            key conventions as ``names``.

    Keyword Parameters:
        x (np.ndarray | None):
            Independent-variable values (legacy path).  Defaults to an empty
            float array when omitted.
        y (np.ndarray | None):
            Primary dependent-variable values (legacy path).  Defaults to an
            empty float array when omitted.
        d (np.ndarray | None):
            x-axis error-bar values (legacy path).  Omitted from the DataFrame
            when ``None`` or an empty array.
        e (np.ndarray | None):
            y-axis error-bar values (legacy path).  Omitted from the DataFrame
            when ``None`` or an empty array.
        names (dict[str, str] | None):
            Human-readable name mapping (both paths).
        units (dict[str, str] | None):
            Physical unit mapping (both paths).
        df (pd.DataFrame | None):
            Pre-built DataFrame for the new-style path.  The index must contain
            the independent-variable values.  When provided, the ``x`` / ``y``
            / ``d`` / ``e`` keyword arguments are ignored.
        column_roles (dict[str, str] | None):
            Column-name → role mapping for the new-style path.  Ignored when
            ``df`` is ``None``.

    Examples:
        >>> import numpy as np
        >>> from stoner_measurement.plugins.trace.base import TraceData, COLUMN_ROLE_Y
        >>> td = TraceData(x=np.array([0.0, 1.0]), y=np.array([0.0, 2.0]))
        >>> float(td.x[1])
        1.0
        >>> float(td.y[1])
        2.0
        >>> len(td.d)
        0
        >>> x_arr, y_arr = td  # backward-compatible unpacking
        >>> float(x_arr[0])
        0.0
        >>> td.get_columns_by_role(COLUMN_ROLE_Y)
        ['y']
    """

    def __init__(
        self,
        x: np.ndarray | None = None,
        y: np.ndarray | None = None,
        d: np.ndarray | None = None,
        e: np.ndarray | None = None,
        names: dict[str, str] | None = None,
        units: dict[str, str] | None = None,
        *,
        df: pd.DataFrame | None = None,
        column_roles: dict[str, str] | None = None,
    ) -> None:
        """Initialise a TraceData instance.

        See class docstring for full parameter descriptions.
        """
        if df is not None:
            # New-style path: caller supplies a ready-made DataFrame.
            self._df: pd.DataFrame = df.copy()
            self.column_roles: dict[str, str] = dict(column_roles) if column_roles is not None else {}
            self.names: dict[str, str] = dict(names) if names is not None else {"x": "x"}
            self.units: dict[str, str] = dict(units) if units is not None else {"x": ""}
        else:
            # Legacy / backward-compatible path.
            x_arr = np.array([], dtype=float) if x is None else np.asarray(x, dtype=float)
            y_arr = np.array([], dtype=float) if y is None else np.asarray(y, dtype=float)

            col_data: dict[str, np.ndarray] = {"y": y_arr}
            roles: dict[str, str] = {"y": COLUMN_ROLE_Y}

            if d is not None:
                d_arr = np.asarray(d, dtype=float)
                if len(d_arr) > 0:
                    col_data["d"] = d_arr
                    roles["d"] = COLUMN_ROLE_D

            if e is not None:
                e_arr = np.asarray(e, dtype=float)
                if len(e_arr) > 0:
                    col_data["e"] = e_arr
                    roles["e"] = COLUMN_ROLE_E

            self._df = pd.DataFrame(col_data, index=pd.Index(x_arr, name="x"))
            self.column_roles = roles

            if names is not None:
                self.names = dict(names)
            else:
                self.names = {"x": "x", "y": "y"}
                if "d" in col_data:
                    self.names["d"] = ""
                if "e" in col_data:
                    self.names["e"] = ""

            if units is not None:
                self.units = dict(units)
            else:
                self.units = {"x": "", "y": ""}
                if "d" in col_data:
                    self.units["d"] = ""
                if "e" in col_data:
                    self.units["e"] = ""

    # ------------------------------------------------------------------
    # DataFrame-backed properties
    # ------------------------------------------------------------------

    @property
    def df(self) -> pd.DataFrame:
        """The underlying :class:`pandas.DataFrame` (index = x, columns = data).

        Returns:
            (pd.DataFrame):
                The backing DataFrame.  Callers should treat this as read-only
                and use :meth:`add_column` to add new columns.

        Examples:
            >>> import numpy as np, pandas as pd
            >>> from stoner_measurement.plugins.trace.base import TraceData
            >>> td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
            >>> isinstance(td.df, pd.DataFrame)
            True
            >>> list(td.df.columns)
            ['y']
        """
        return self._df

    @property
    def columns(self) -> list[str]:
        """Ordered list of column names in the underlying DataFrame.

        Returns:
            (list[str]):
                Column names in DataFrame order.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.plugins.trace.base import TraceData
            >>> td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
            >>> td.columns
            ['y']
        """
        return list(self._df.columns)

    # ------------------------------------------------------------------
    # Backward-compatible array properties
    # ------------------------------------------------------------------

    @property
    def x(self) -> np.ndarray:
        """Independent-variable values as a one-dimensional NumPy array.

        Returns:
            (np.ndarray):
                The DataFrame index as a float64 array.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.plugins.trace.base import TraceData
            >>> td = TraceData(x=np.array([0.0, 1.0]), y=np.array([2.0, 3.0]))
            >>> td.x.tolist()
            [0.0, 1.0]
        """
        return self._df.index.to_numpy(dtype=float)

    @property
    def y(self) -> np.ndarray:
        """First :data:`COLUMN_ROLE_Y`-role column as a one-dimensional NumPy array.

        Returns:
            (np.ndarray):
                The first ``"y"``-role column, or an empty float64 array if no
                such column exists.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.plugins.trace.base import TraceData
            >>> td = TraceData(x=np.array([0.0, 1.0]), y=np.array([2.0, 3.0]))
            >>> td.y.tolist()
            [2.0, 3.0]
        """
        cols = self.get_columns_by_role(COLUMN_ROLE_Y)
        if not cols:
            return np.array([], dtype=float)
        return self._df[cols[0]].to_numpy(dtype=float)

    @property
    def d(self) -> np.ndarray:
        """First :data:`COLUMN_ROLE_D`-role column as a one-dimensional NumPy array.

        Returns:
            (np.ndarray):
                The first ``"d"``-role column, or an empty float64 array if no
                such column exists.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.plugins.trace.base import TraceData
            >>> td = TraceData(x=np.array([0.0]), y=np.array([1.0]))
            >>> len(td.d)
            0
        """
        cols = self.get_columns_by_role(COLUMN_ROLE_D)
        if not cols:
            return np.array([], dtype=float)
        return self._df[cols[0]].to_numpy(dtype=float)

    @property
    def e(self) -> np.ndarray:
        """First :data:`COLUMN_ROLE_E`-role column as a one-dimensional NumPy array.

        Returns:
            (np.ndarray):
                The first ``"e"``-role column, or an empty float64 array if no
                such column exists.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.plugins.trace.base import TraceData
            >>> td = TraceData(x=np.array([0.0]), y=np.array([1.0]))
            >>> len(td.e)
            0
        """
        cols = self.get_columns_by_role(COLUMN_ROLE_E)
        if not cols:
            return np.array([], dtype=float)
        return self._df[cols[0]].to_numpy(dtype=float)

    # ------------------------------------------------------------------
    # Multi-column API
    # ------------------------------------------------------------------

    def get_columns_by_role(self, role: str) -> list[str]:
        """Return the names of all columns that carry *role*.

        Args:
            role (str):
                One of the ``COLUMN_ROLE_*`` constants.

        Returns:
            (list[str]):
                Column names (in insertion order) whose role matches *role*.
                Empty list if no columns carry that role.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.plugins.trace.base import (
            ...     TraceData, COLUMN_ROLE_Y, COLUMN_ROLE_E,
            ... )
            >>> td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
            >>> td.get_columns_by_role(COLUMN_ROLE_Y)
            ['y']
            >>> td.get_columns_by_role(COLUMN_ROLE_E)
            []
        """
        return [col for col in self._df.columns if self.column_roles.get(col) == role]

    def add_column(self, name: str, data: np.ndarray, role: str) -> None:
        """Add a new data column to this trace.

        Args:
            name (str):
                Name for the new column.  Must not already exist in the
                DataFrame.
            data (np.ndarray):
                One-dimensional data array whose length matches the number of
                rows in the DataFrame.
            role (str):
                Role tag for the new column.  Must be one of the
                ``COLUMN_ROLE_*`` constants.

        Raises:
            ValueError:
                If *role* is not one of the recognised role constants.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.plugins.trace.base import (
            ...     TraceData, COLUMN_ROLE_Y, COLUMN_ROLE_Z,
            ... )
            >>> td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
            >>> td.add_column("z", np.array([5.0, 6.0]), COLUMN_ROLE_Z)
            >>> td.get_columns_by_role(COLUMN_ROLE_Z)
            ['z']
            >>> td.df["z"].tolist()
            [5.0, 6.0]
        """
        if role not in _VALID_ROLES:
            raise ValueError(
                f"Invalid column role {role!r}. "
                f"Valid roles are: {sorted(_VALID_ROLES)}"
            )
        self._df[name] = np.asarray(data, dtype=float)
        self.column_roles[name] = role

    # ------------------------------------------------------------------
    # Backward-compatible iteration and indexing
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[np.ndarray]:
        """Yield ``x`` then ``y`` to support two-element tuple unpacking.

        This provides backward compatibility with code that previously used
        ``x_arr, y_arr = trace_data[channel]``.

        Yields:
            (np.ndarray):
                ``x`` — the independent-variable array.
            (np.ndarray):
                ``y`` — the primary dependent-variable array.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.plugins.trace.base import TraceData
            >>> td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
            >>> a, b = td
            >>> float(a[0])
            1.0
            >>> float(b[0])
            2.0
        """
        yield self.x
        yield self.y

    def __getitem__(self, index: int) -> np.ndarray:
        """Return the array at *index* (0 → x, 1 → y, 2 → d, 3 → e).

        Args:
            index (int):
                0 for ``x``, 1 for ``y``, 2 for ``d`` (x-error), 3 for ``e``
                (y-error).

        Returns:
            (np.ndarray):
                The requested array.

        Raises:
            IndexError:
                If *index* is outside the range 0–3.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.plugins.trace.base import TraceData
            >>> td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
            >>> float(td[0][0])
            1.0
            >>> float(td[1][0])
            2.0
        """
        arrays = (self.x, self.y, self.d, self.e)
        if not 0 <= index < len(arrays):
            raise IndexError(f"TraceData index {index!r} out of range 0–3")
        return arrays[index]


class TraceStatus(enum.Enum):
    """Operational status of a :class:`TracePlugin`.

    Used by the :attr:`~TracePlugin.status` property and the
    :attr:`~TracePlugin.status_changed` signal to communicate the current
    lifecycle phase to the sequence engine and the user interface.

    Attributes:
        IDLE:
            No operation is in progress; the plugin is ready to accept the
            next lifecycle call.
        CONNECTING:
            :meth:`~TracePlugin.connect` is executing; instrument connections
            are being opened and/or verified.
        CONFIGURING:
            :meth:`~TracePlugin.configure` is executing; instrument settings
            are being applied.
        MEASURING:
            :meth:`~TracePlugin.measure` is active and data points are being
            acquired.
        DATA_AVAILABLE:
            A :meth:`~TracePlugin.measure` call has completed successfully;
            the most-recently acquired trace is ready for use.
        DISCONNECTING:
            :meth:`~TracePlugin.disconnect` is executing; resources are being
            released.
        ERROR:
            An unrecoverable error occurred during a lifecycle call.

    Examples:
        >>> TraceStatus.IDLE.value
        'idle'
        >>> TraceStatus("measuring") is TraceStatus.MEASURING
        True
    """

    IDLE = "idle"
    CONNECTING = "connecting"
    CONFIGURING = "configuring"
    MEASURING = "measuring"
    DATA_AVAILABLE = "data_available"
    DISCONNECTING = "disconnecting"
    ERROR = "error"


class _ScanTabContainer(QWidget):
    """Container that hosts the active scan generator's config widget.

    The content is replaced automatically whenever the owning
    :class:`TracePlugin` emits :attr:`~TracePlugin.scan_generator_changed`.
    """

    def __init__(self, plugin: TracePlugin, parent: QWidget | None = None) -> None:
        """Initialise the container and bind it to *plugin*."""
        super().__init__(parent)
        self._plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._content: QWidget | None = None
        self._refresh()
        plugin.scan_generator_changed.connect(self._refresh)

    def _refresh(self) -> None:
        """Replace the content widget with the current generator's config widget."""
        if self._content is not None:
            self.layout().removeWidget(self._content)
            self._content.hide()
            self._content.deleteLater()
            self._content = None
        self._content = self._plugin.scan_generator.config_widget(parent=self)
        self.layout().addWidget(self._content)
        self._content.show()


class _ScanPage(QWidget):
    """Combined scan configuration page.

    Displays the instance-name editor, an optional scan-generator type
    selector, a horizontal rule, and the active generator's configuration
    widget — all on a single page.  The generator widget auto-refreshes when
    the active generator changes; the type combo box stays in sync with the
    current generator class.
    """

    def __init__(self, plugin: TracePlugin, parent: QWidget | None = None) -> None:
        """Initialise the scan page and bind it to *plugin*."""
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # --- Header form: instance name + optional generator selector ---
        header_form = QFormLayout()

        name_edit = QLineEdit(plugin.instance_name)
        name_edit.setToolTip("Python variable name used to access this plugin in the sequence engine")

        def _apply_name() -> None:
            new_name = name_edit.text().strip()
            if new_name and new_name.isidentifier():
                name_edit.setStyleSheet("")
                plugin.instance_name = new_name
            else:
                name_edit.setStyleSheet("border: 1px solid red;")
                name_edit.setToolTip(
                    f"{new_name!r} is not a valid Python identifier. "
                    "Use only letters, digits and underscores, "
                    "and do not start with a digit."
                )
                name_edit.setText(plugin.instance_name)

        name_edit.editingFinished.connect(_apply_name)
        header_form.addRow("Instance name:", name_edit)
        header_form.addRow("Plugin type:", QLabel(plugin.plugin_type))

        if len(plugin._scan_generator_classes) > 1:
            combo = QComboBox()
            for cls in plugin._scan_generator_classes:
                combo.addItem(cls.__name__, cls)
            current_idx = combo.findData(type(plugin.scan_generator))
            if current_idx >= 0:
                combo.setCurrentIndex(current_idx)

            def _on_type_changed(index: int) -> None:
                cls = combo.itemData(index)
                if cls is not None and not isinstance(plugin.scan_generator, cls):
                    plugin.set_scan_generator_class(cls)

            def _sync_type_combo() -> None:
                current_cls = type(plugin.scan_generator)
                idx = combo.findData(current_cls)
                if idx >= 0 and combo.currentIndex() != idx:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)

            combo.currentIndexChanged.connect(_on_type_changed)
            plugin.scan_generator_changed.connect(_sync_type_combo)
            header_form.addRow("Generator type:", combo)

        header_widget = QWidget()
        header_widget.setLayout(header_form)
        layout.addWidget(header_widget)

        # --- Horizontal separator ---
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # --- Scan generator config widget (auto-refreshes on generator change) ---
        scan_container = _ScanTabContainer(plugin, parent=self)
        layout.addWidget(scan_container)


class TracePlugin(QObject, BasePlugin, metaclass=_ABCQObjectMeta):
    """Abstract base class for plugins that collect (x, y) data traces.

    A :class:`TracePlugin` acquires one or more complete traces of (x, y) data
    from instruments.  Subclasses must implement :attr:`name` (inherited from
    :class:`~stoner_measurement.plugins.base_plugin.BasePlugin`) and
    :meth:`execute`.

    The class provides:

    * **Lifecycle API** — :meth:`connect`, :meth:`configure`, :meth:`measure`,
      and :meth:`disconnect` form the standard sequence-engine interface.
      Default implementations are no-ops (or delegate to :meth:`execute`);
      override them in concrete plugins to interact with real hardware.
    * **Status reporting** — :attr:`status` (a :class:`TraceStatus` value) and
      :attr:`status_changed` signal communicate the current lifecycle phase.
    * **Single-channel acquisition** — :meth:`execute` yields ``(x, y)`` pairs
      for the primary channel.
    * **Multi-channel acquisition** — :meth:`execute_multichannel` yields
      ``(channel, x, y)`` triples; the default implementation wraps
      :meth:`execute` using the first entry of :attr:`channel_names`.
    * **Complete-trace acquisition** — :meth:`measure` runs the full
      acquisition and returns all ``(channel, x, y)`` points as a list.
      Code generated by the sequence engine calls :meth:`measure` once to
      obtain the complete dataset.
    * **Scan generator** — :attr:`scan_generator` (also accessible via
      :attr:`trace_scan`) holds the active
      :class:`~stoner_measurement.scan.BaseScanGenerator` instance.  The
      default class used is given by :attr:`_scan_generator_class` and can be
      changed at runtime via :meth:`set_scan_generator_class`.
    * **Trace details** — :attr:`num_traces`, :attr:`trace_title`,
      :attr:`x_label`, :attr:`y_label`, :attr:`x_units`, and :attr:`y_units`
      describe the shape and labelling of the acquired data.

    Attributes:
        _scan_generator_class (type[BaseScanGenerator]):
            Default scan generator class instantiated in :meth:`__init__`.
            Override at class level in a subclass to change the default for
            that plugin type.
        _scan_generator_classes (list[type[BaseScanGenerator]]):
            Ordered list of scan generator classes offered to the user in the
            *Scan Type* configuration tab.  The tab is only shown when this
            list contains more than one entry.  Override at class level to
            restrict or extend the available choices.
        scan_generator (BaseScanGenerator):
            Active scan generator instance.  Replaced (and
            :attr:`scan_generator_changed` emitted) when
            :meth:`set_scan_generator_class` is called.  Also accessible as
            :attr:`trace_scan`.
        data (dict[str, TraceData]):
            Most recently acquired trace data, populated by :meth:`measure`.
            Maps each channel name to a :class:`TraceData` instance whose
            ``x`` and ``y`` attributes hold the measured arrays.  The
            ``names`` and ``units`` dicts are populated from the plugin's
            :attr:`x_label`, :attr:`y_label`, :attr:`x_units`, and
            :attr:`y_units` properties.  Empty until the first successful
            call to :meth:`measure`.
        status_changed (pyqtSignal[object]):
            Emitted with the new :class:`TraceStatus` value whenever
            :attr:`status` changes.
        scan_generator_changed (pyqtSignal):
            Emitted after :attr:`scan_generator` is replaced with a new
            instance.  The first configuration tab and the *Scan Type*
            selector both connect to this signal to update their content.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.trace import DummyPlugin
        >>> plugin = DummyPlugin()
        >>> plugin.plugin_type
        'trace'
        >>> plugin.x_label
        'x'
        >>> plugin.y_label
        'y'
        >>> plugin.channel_names == [plugin.name]
        True
        >>> plugin.status is TraceStatus.IDLE
        True
        >>> plugin.num_traces
        1
        >>> plugin.trace_title
        'Dummy'
    """

    _scan_generator_class: ClassVar[type[BaseScanGenerator]] = FunctionScanGenerator
    _scan_generator_classes: ClassVar[list[type[BaseScanGenerator]]] = [
        FunctionScanGenerator,
        SteppedScanGenerator,
        ListScanGenerator,
        RampScanGenerator,
        ArbitraryFunctionScanGenerator,
    ]

    scan_generator_changed = pyqtSignal()
    instance_name_changed = pyqtSignal(str, str)
    status_changed = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy and create the built-in scan generator."""
        super().__init__(parent)
        self.scan_generator: BaseScanGenerator = self._scan_generator_class(parent=self)
        self._status: TraceStatus = TraceStatus.IDLE
        self.data: dict[str, TraceData] = {}
        self._report_channel_statistics: bool = False
        self.channel_statistics: dict[str, dict[str, float]] = {}
        self._cached_config_tabs: list | None = None

    def _on_instance_name_changed(self, old_name: str, new_name: str) -> None:
        """Emit :attr:`instance_name_changed` when the instance name changes."""
        self.instance_name_changed.emit(old_name, new_name)

    # ------------------------------------------------------------------
    # Scan generator management
    # ------------------------------------------------------------------

    def set_scan_generator_class(self, cls: type[BaseScanGenerator]) -> None:
        """Replace the active scan generator with a new instance of *cls*.

        If the current generator is already an instance of *cls* this method
        does nothing.  Otherwise a new instance is created (with this plugin
        as Qt parent), assigned to :attr:`scan_generator`, and
        :attr:`scan_generator_changed` is emitted so that connected widgets
        can refresh their content.

        Args:
            cls (type[BaseScanGenerator]):
                The scan generator class to instantiate.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> from stoner_measurement.scan import FunctionScanGenerator
            >>> plugin = DummyPlugin()
            >>> plugin.set_scan_generator_class(FunctionScanGenerator)
            >>> isinstance(plugin.scan_generator, FunctionScanGenerator)
            True
        """
        if isinstance(self.scan_generator, cls):
            return
        self.scan_generator = cls(parent=self)
        self.scan_generator_changed.emit()

    # ------------------------------------------------------------------
    # Plugin type tag
    # ------------------------------------------------------------------

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a trace collector.

        Returns:
            (str):
                Always ``"trace"``.
        """
        return "trace"

    # ------------------------------------------------------------------
    # JSON serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> dict:
        """Serialise this plugin's configuration, including the scan generator.

        Extends the base :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
        dict with a ``"scan_generator"`` key containing the serialised
        :attr:`scan_generator` state.

        Returns:
            (dict):
                A JSON-serialisable dictionary with at least the keys produced
                by :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                plus ``"scan_generator"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> d = plugin.to_json()
            >>> d["type"]
            'trace'
            >>> "scan_generator" in d
            True
            >>> d["scan_generator"]["type"]
            'SteppedScanGenerator'
        """
        data = super().to_json()
        data["scan_generator"] = self.scan_generator.to_json()
        data["report_channel_statistics"] = self._report_channel_statistics
        return data

    def _restore_from_json(self, data: dict) -> None:
        """Restore the scan generator from *data*.

        Called by :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.from_json`
        after construction.  Reconstructs the :attr:`scan_generator` and emits
        :attr:`scan_generator_changed` so that any already-connected widgets
        can update their content.

        Args:
            data (dict):
                Serialised plugin dict as produced by :meth:`to_json`.
        """
        if "scan_generator" in data:
            gen = BaseScanGenerator.from_json(data["scan_generator"], parent=self)
            self.scan_generator = gen
            self.scan_generator_changed.emit()
        if "report_channel_statistics" in data:
            self._report_channel_statistics = bool(data["report_channel_statistics"])

    @property
    def status(self) -> TraceStatus:
        """Current operational status of this plugin.

        Returns:
            (TraceStatus):
                The current :class:`TraceStatus` value.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> plugin.status is TraceStatus.IDLE
            True
        """
        return self._status

    def _set_status(self, status: TraceStatus) -> None:
        """Update :attr:`status` and emit :attr:`status_changed` if the value changed."""
        if self._status != status:
            self._status = status
            self.status_changed.emit(status)

    # ------------------------------------------------------------------
    # Lifecycle API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open instrument connections and verify the instrument identity.

        Called once at the start of a measurement sequence to reserve hardware
        resources.  Subclasses should override this method to open serial,
        USB, GPIB, or Ethernet connections and to confirm that the connected
        instrument is the expected type.

        The default implementation is a no-op and leaves the status unchanged
        (``IDLE``).  Override and call ``self._set_status(TraceStatus.IDLE)``
        after a successful connection to signal readiness.

        Raises:
            RuntimeError:
                If the instrument cannot be reached or is not the expected
                type.  Subclasses should raise (or emit :attr:`status_changed`
                with :attr:`TraceStatus.ERROR`) on failure.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> plugin.connect()   # no-op for the dummy plugin
            >>> plugin.status is TraceStatus.IDLE
            True
        """

    def configure(self) -> None:
        """Apply plugin settings to the instrument.

        Called after :meth:`connect` and before :meth:`measure` to push
        configuration (range, integration time, averaging, etc.) to the
        hardware.  May also be called mid-sequence to reconfigure without
        reconnecting.

        The default implementation is a no-op.  Override to send the
        appropriate commands to the instrument.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> plugin.configure()   # reads widget values for the dummy plugin
        """

    def measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Trigger acquisition and return all trace data keyed by channel name.

        This is the primary measurement entry point for the sequence engine.
        It sets :attr:`status` to :attr:`TraceStatus.MEASURING`, delegates to
        :meth:`execute_multichannel` to acquire the complete trace, and finally
        sets :attr:`status` to :attr:`TraceStatus.DATA_AVAILABLE` before
        returning.

        The result is also stored as :attr:`data` so that downstream code can
        access it without holding on to the return value.

        Subclasses may override this method to implement custom measurement
        logic while still honouring the status transitions.

        Args:
            parameters (dict[str, Any]):
                Step-specific configuration forwarded to
                :meth:`execute_multichannel` (and thence to :meth:`execute`).

        Returns:
            (dict[str, TraceData]):
                Mapping of channel name to a :class:`TraceData` instance
                containing the measured ``x`` and ``y`` arrays together with
                ``names`` and ``units`` metadata derived from :attr:`x_label`,
                :attr:`y_label`, :attr:`x_units`, and :attr:`y_units`.  The
                same dict is stored as :attr:`data`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> from stoner_measurement.scan import SteppedScanGenerator
            >>> plugin = DummyPlugin()
            >>> plugin.scan_generator = SteppedScanGenerator(
            ...     start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
            ... )
            >>> result = plugin.measure({})
            >>> list(result.keys())
            ['Dummy']
            >>> import numpy as np
            >>> isinstance(result['Dummy'].x, np.ndarray)
            True
            >>> len(result['Dummy'].x)
            5
            >>> result['Dummy'].names['x']
            'I'
            >>> result['Dummy'].units['y']
            'V'
            >>> plugin.status is TraceStatus.DATA_AVAILABLE
            True
            >>> plugin.data is result
            True
        """
        self._set_status(TraceStatus.MEASURING)
        # xs/ys keys also serve as the set of channels seen so far.
        xs: dict[str, list[float]] = {}
        ys: dict[str, list[float]] = {}
        # names/units only need the axes that are actually present.  The legacy
        # "d" and "e" sentinel keys are no longer included because the DataFrame
        # has no error-bar columns until add_column() is called explicitly.
        names = {"x": self.x_label, "y": self.y_label}
        units = {"x": self.x_units, "y": self.y_units}
        try:
            for channel, x, y in self.execute_multichannel(parameters):
                if channel not in xs:
                    xs[channel] = []
                    ys[channel] = []
                xs[channel].append(x)
                ys[channel].append(y)
        finally:
            self._set_status(TraceStatus.DATA_AVAILABLE)
        self.data = {}
        for ch in xs:
            x_arr = np.array(xs[ch])
            y_arr = np.array(ys[ch])
            df = pd.DataFrame({"y": y_arr}, index=pd.Index(x_arr, name="x"))
            self.data[ch] = TraceData(
                df=df,
                column_roles={"y": COLUMN_ROLE_Y},
                names=names,
                units=units,
            )
        self._update_channel_statistics()
        return self.data

    def disconnect(self) -> None:
        """Release all reserved instrument resources.

        Called at the end of a measurement sequence (or after an error) to
        cleanly close connections and free hardware resources.  The default
        implementation is a no-op and resets :attr:`status` to
        :attr:`TraceStatus.IDLE`.  Override to close serial/USB/GPIB/Ethernet
        connections.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> plugin.disconnect()
            >>> plugin.status is TraceStatus.IDLE
            True
        """
        self._set_status(TraceStatus.IDLE)

    # ------------------------------------------------------------------
    # Trace details
    # ------------------------------------------------------------------

    @property
    def num_traces(self) -> int:
        """Number of independent trace channels provided by this plugin.

        Returns:
            (int):
                ``len(self.channel_names)``; always at least 1.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> DummyPlugin().num_traces
            1
        """
        return len(self.channel_names)

    @property
    def trace_title(self) -> str:
        """Human-readable display title for the trace (used in plot titles, legends, etc.).

        This title is intended for display purposes only.  For file-system
        usage, derive a sanitised name from :attr:`name` or
        :attr:`instance_name` instead.

        The default implementation returns :attr:`name`.  Override in a
        subclass to provide a more descriptive title.

        Returns:
            (str):
                Trace title string.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> DummyPlugin().trace_title
            'Dummy'
        """
        return self.name

    @property
    def x_units(self) -> str:
        """Physical units for the x (independent) axis.

        The default implementation returns an empty string (dimensionless).
        Override to specify units such as ``"V"``, ``"Hz"``, or ``"s"``.

        Returns:
            (str):
                Unit string; empty string if dimensionless.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> DummyPlugin().x_units
            ''
        """
        return ""

    @property
    def y_units(self) -> str:
        """Physical units for the y (dependent) axis.

        The default implementation returns an empty string (dimensionless).
        Override to specify units such as ``"A"``, ``"Ω"``, or ``"dB"``.

        Returns:
            (str):
                Unit string; empty string if dimensionless.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> DummyPlugin().y_units
            ''
        """
        return ""

    @property
    def trace_scan(self) -> BaseScanGenerator:
        """The active scan generator for this trace.

        This is an alias for :attr:`scan_generator` and is provided as the
        canonical accessor for the sequence engine and external code that needs
        to inspect or iterate the scan sequence.

        Returns:
            (BaseScanGenerator):
                The currently active scan generator instance.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> from stoner_measurement.scan import SteppedScanGenerator
            >>> plugin = DummyPlugin()
            >>> isinstance(plugin.trace_scan, SteppedScanGenerator)
            True
            >>> plugin.trace_scan is plugin.scan_generator
            True
        """
        return self.scan_generator

    # ------------------------------------------------------------------
    # Configuration tabs
    # ------------------------------------------------------------------

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return a fixed set of configuration tabs for this plugin.

        Returns a *Scan* tab (instance name, optional generator selector, and
        the generator's own config widget), a *Settings* tab populated by
        :meth:`_plugin_config_tabs`, and an optional *About* tab whose HTML
        content is provided by :meth:`_about_html`.

        Tab widgets are created once and cached on the plugin instance so that
        user-edited state is preserved when tabs are hidden and re-shown (e.g.
        when the user selects a different sequence step and then re-selects this
        one).

        Keyword Parameters:
            parent (QWidget | None):
                Ignored after the first call; widgets are cached without a
                parent and are re-parented automatically by
                :class:`~PyQt6.QtWidgets.QTabWidget` when added.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs; the *Scan* tab is always
                first.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> tabs = plugin.config_tabs()
            >>> tabs[0][0]
            'Dummy \u2013 Scan'
            >>> tabs[1][0]
            'Dummy \u2013 Settings'
        """
        if self._cached_config_tabs is not None:
            return self._cached_config_tabs

        tabs: list[tuple[str, QWidget]] = [
            (f"{self.name} \u2013 Scan", _ScanPage(self)),
        ]

        settings_widget: QWidget = self._plugin_config_tabs() or QWidget()
        stats_check = QCheckBox("Report channel average and standard deviation outputs")
        stats_check.setChecked(self._report_channel_statistics)
        stats_check.toggled.connect(self._set_report_channel_statistics)
        self._attach_statistics_checkbox(settings_widget, stats_check)

        tabs.append((f"{self.name} \u2013 Settings", settings_widget))

        about_tab = self._make_about_tab()
        if about_tab is not None:
            tabs.append(about_tab)

        self._cached_config_tabs = tabs
        return self._cached_config_tabs

    def _plugin_config_tabs(self) -> QWidget | None:
        """Return the settings widget for the *Settings* tab, or ``None`` for a blank tab.

        The default implementation returns ``None``, which causes
        :meth:`config_tabs` to display an empty :class:`~PyQt6.QtWidgets.QWidget`
        as the *Settings* tab.

        Override this method in a subclass to return a configured
        :class:`~PyQt6.QtWidgets.QWidget` for the *Settings* tab.  Do
        **not** override :meth:`config_tabs` directly; that would bypass the
        scan-related tab structure managed by this class.

        Returns:
            (QWidget | None):
                The settings widget, or ``None`` for a blank tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> plugin._plugin_config_tabs() is None
            True
        """
        return None

    # ------------------------------------------------------------------
    # Abstract acquisition interface
    # ------------------------------------------------------------------

    @abstractmethod
    def execute(self, parameters: dict[str, Any]) -> Generator[tuple[float, float]]:
        """Acquire a trace and yield ``(x, y)`` data points.

        This method is the primary acquisition entry point.  Each yielded
        tuple represents a single measured (x, y) pair on the default channel.

        Args:
            parameters (dict[str, Any]):
                Step-specific configuration provided by the caller (e.g.
                sweep range, integration time).

        Yields:
            (tuple[float, float]):
                ``(x, y)`` data point pairs.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> from stoner_measurement.scan import SteppedScanGenerator
            >>> plugin = DummyPlugin()
            >>> plugin.scan_generator = SteppedScanGenerator(
            ...     start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
            ... )
            >>> pts = list(plugin.execute({}))
            >>> len(pts)
            5
            >>> isinstance(pts[0], tuple) and len(pts[0]) == 2
            True
        """

    @property
    def channel_names(self) -> list[str]:
        """Names of the available measurement channels.

        The default implementation returns a single-element list containing
        :attr:`name`.  Override to expose multiple channels.

        Returns:
            (list[str]):
                Ordered list of channel name strings.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> DummyPlugin().channel_names
            ['Dummy']
        """
        return [self.name]

    @property
    def x_label(self) -> str:
        """Axis label for the independent variable.

        Returns:
            (str):
                Human-readable label string; default ``"x"``.
        """
        return "x"

    @property
    def y_label(self) -> str:
        """Axis label for the dependent variable.

        Returns:
            (str):
                Human-readable label string; default ``"y"``.
        """
        return "y"

    def execute_multichannel(self, parameters: dict[str, Any]) -> Generator[tuple[str, float, float]]:
        """Acquire traces from all channels and yield ``(channel, x, y)`` triples.

        The default implementation wraps :meth:`execute` using the first entry
        of :attr:`channel_names`.  Override this method when the plugin
        supports simultaneous multi-channel acquisition.

        Args:
            parameters (dict[str, Any]):
                Step-specific configuration forwarded to :meth:`execute`.

        Yields:
            (tuple[str, float, float]):
                ``(channel_name, x, y)`` triples.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> from stoner_measurement.scan import SteppedScanGenerator
            >>> plugin = DummyPlugin()
            >>> plugin.scan_generator = SteppedScanGenerator(
            ...     start=0.0, stages=[(0.2, 0.1, True)], parent=plugin
            ... )
            >>> pts = list(plugin.execute_multichannel({}))
            >>> len(pts)
            3
            >>> pts[0][0]
            'Dummy'
        """
        channel = self.channel_names[0]
        for x, y in self.execute(parameters):
            yield channel, x, y

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Any,
    ) -> list[str]:
        """Return action code lines that acquire a trace via :meth:`measure`.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Ignored for :class:`TracePlugin` (leaf node in the sequence tree).
            render_sub_step (Any):
                Ignored for :class:`TracePlugin`.

        Returns:
            (list[str]):
                A single line that calls ``measure({})`` and assigns the
                result to the plugin's :attr:`data` attribute.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> lines = plugin.generate_action_code(1, [], lambda s, i: [])
            >>> "    dummy.data = dummy.measure({})" in lines
            True
            >>> any("for" in line for line in lines)
            False
        """
        prefix = "    " * indent
        var_name = self.instance_name
        return [
            f"{prefix}{var_name}.data = {var_name}.measure({{}})",
            "",
        ]

    def reported_traces(self) -> dict[str, str]:
        """Return a mapping of channel names to Python expressions for accessing trace data.

        Each entry corresponds to one measurement channel provided by this plugin.
        The key is ``"{instance_name}:{channel_name}"`` (a human-readable identifier)
        and the value is the Python expression ``"{instance_name}.data['{channel_name}']"``
        that retrieves the ``(x_array, y_array)`` tuple for that channel from the most
        recently acquired :attr:`data` dict.

        Returns:
            (dict[str, str]):
                Mapping of ``"{instance_name}:{channel_name}"`` → expression for each
                channel in :attr:`channel_names`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> traces = plugin.reported_traces()
            >>> list(traces.keys())
            ['dummy:Dummy']
            >>> traces['dummy:Dummy']
            "dummy.data['Dummy']"
        """
        var = self.instance_name
        return {f"{var}:{ch}": f"{var}.data['{ch}']" for ch in self.channel_names}

    def reported_values(self) -> dict[str, str]:
        """Return optional channel statistics as scalar value outputs.

        When enabled, each channel contributes ``mean`` and ``std`` values.

        Returns:
            (dict[str, str]):
                Mapping of ``"{instance_name}:{value_name}"`` to Python
                expressions that read from :attr:`channel_statistics`.
        """
        if not self._report_channel_statistics:
            return {}

        var = self.instance_name
        values: dict[str, str] = {}
        for channel in self.channel_names:
            values[f"{var}:{channel} mean"] = (
                f"{var}.get_channel_statistic({channel!r}, 'mean')"
            )
            values[f"{var}:{channel} std"] = (
                f"{var}.get_channel_statistic({channel!r}, 'std')"
            )
        return values

    def _set_report_channel_statistics(self, enabled: bool) -> None:
        """Enable/disable reporting of per-channel mean/std scalar outputs."""
        self._report_channel_statistics = bool(enabled)
        if not self._report_channel_statistics:
            self.channel_statistics = {}
            return
        self._update_channel_statistics()

    def _update_channel_statistics(self) -> None:
        """Recalculate per-channel mean and standard deviation from :attr:`data`."""
        if not self._report_channel_statistics:
            self.channel_statistics = {}
            return

        stats: dict[str, dict[str, float]] = {}
        for channel, trace_data in self.data.items():
            y_values = np.asarray(trace_data.y, dtype=float)
            if y_values.size == 0:
                mean_val = float("nan")
                std_val = float("nan")
            else:
                mean_val = float(np.mean(y_values))
                std_val = float(np.std(y_values))
            stats[channel] = {"mean": mean_val, "std": std_val}
        self.channel_statistics = stats

    def get_channel_statistic(self, channel: str, statistic: str) -> float:
        """Return a cached per-channel statistic, defaulting to ``nan``.

        Args:
            channel (str):
                Channel name key in :attr:`channel_statistics`.
            statistic (str):
                Statistic key for the channel (for example ``"mean"`` or ``"std"``).

        Returns:
            (float):
                Cached statistic value, or ``nan`` if unavailable.
        """
        return float(self.channel_statistics.get(channel, {}).get(statistic, float("nan")))

    def _attach_statistics_checkbox(self, settings_widget: QWidget, checkbox: QCheckBox) -> None:
        """Attach the statistics checkbox to the top of the settings widget.

        Args:
            settings_widget (QWidget):
                Settings tab widget to augment.
            checkbox (QCheckBox):
                Checkbox controlling channel statistics output reporting.
        """
        layout = settings_widget.layout()
        if layout is None:
            layout = QVBoxLayout(settings_widget)

        if isinstance(layout, QFormLayout):
            layout.insertRow(0, checkbox)
            return

        if hasattr(layout, "insertWidget"):
            layout.insertWidget(0, checkbox)
            return

        if hasattr(layout, "addWidget"):
            layout.addWidget(checkbox)
