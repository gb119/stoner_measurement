"""Shared tabular measurement data structures."""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Column role constants
# ---------------------------------------------------------------------------

COLUMN_ROLE_Y: str = "y"
"""Role tag identifying a column as the primary dependent variable."""

COLUMN_ROLE_X: str = "x"
"""Role tag identifying the independent-variable column."""

COLUMN_ROLE_Z: str = "z"
"""Role tag identifying a column as a secondary dependent variable."""

COLUMN_ROLE_D: str = "d"
"""Role tag identifying a column as x-axis uncertainty (error bar)."""

COLUMN_ROLE_E: str = "e"
"""Role tag identifying a column as y-axis uncertainty (error bar)."""

_VALID_ROLES: frozenset[str] = frozenset(
    {COLUMN_ROLE_X, COLUMN_ROLE_Y, COLUMN_ROLE_Z, COLUMN_ROLE_D, COLUMN_ROLE_E}
)


class TraceData:
    """One complete trace table with a shared independent-variable column.

    The DataFrame uses a simple integer row index. Its columns store the
    independent variable, measured or derived data, and uncertainties on the
    same row grid. Column roles identify x (``x``), primary data (``y``),
    auxiliary data (``z``), x uncertainty (``d``), and y uncertainty (``e``).

    ``names`` and ``units`` are completed for every DataFrame column during
    construction. Unknown role or metadata keys are rejected so these mappings
    cannot silently drift away from the table.

    Use :meth:`from_xy` as a convenience for a conventional single-y trace.
    """

    def __init__(
        self,
        df: pd.DataFrame | None = None,
        *,
        column_roles: dict[str, str] | None = None,
        names: dict[str, str] | None = None,
        units: dict[str, str] | None = None,
    ) -> None:
        """Initialise a validated DataFrame-backed trace dataset."""
        self._df = (
            pd.DataFrame({"x": pd.Series(dtype=float)})
            if df is None
            else df.copy().reset_index(drop=True)
        )
        self._row_count = len(self._df)
        self._capacity = self._row_count
        if self._df.columns.has_duplicates:
            raise ValueError("TraceData columns must have unique names.")

        columns = list(self._df.columns)
        roles = dict(column_roles or {})
        unknown_role_columns = set(roles).difference(columns)
        if unknown_role_columns:
            raise ValueError(f"Column roles reference unknown columns: {sorted(unknown_role_columns)!r}")
        invalid_roles = {role for role in roles.values() if role not in _VALID_ROLES}
        if invalid_roles:
            raise ValueError(f"Invalid column roles: {sorted(invalid_roles)!r}")
        x_columns = [column for column, role in roles.items() if role == COLUMN_ROLE_X]
        if not x_columns and "x" in columns:
            roles["x"] = COLUMN_ROLE_X
            x_columns = ["x"]
        if len(x_columns) != 1:
            raise ValueError("TraceData requires exactly one COLUMN_ROLE_X column.")
        data_columns = [column for column in columns if column not in x_columns]
        for index, column in enumerate(data_columns):
            roles.setdefault(column, COLUMN_ROLE_Y if index == 0 else COLUMN_ROLE_Z)
        self.column_roles = roles

        valid_metadata_keys = set(columns)
        supplied_names = dict(names or {})
        supplied_units = dict(units or {})
        unknown_metadata = (set(supplied_names) | set(supplied_units)).difference(valid_metadata_keys)
        if unknown_metadata:
            raise ValueError(f"Trace metadata references unknown columns: {sorted(unknown_metadata)!r}")
        self.names = {}
        self.units = {}
        for column in columns:
            self.names[column] = supplied_names.get(column, str(column))
            self.units[column] = supplied_units.get(column, "")

    @classmethod
    def from_xy(
        cls,
        x: np.ndarray,
        y: np.ndarray,
        *,
        x_error: np.ndarray | None = None,
        y_error: np.ndarray | None = None,
        names: dict[str, str] | None = None,
        units: dict[str, str] | None = None,
    ) -> TraceData:
        """Build a conventional single-y trace without a second constructor path."""
        columns: dict[str, np.ndarray] = {
            "x": np.asarray(x, dtype=float),
            "y": np.asarray(y, dtype=float),
        }
        roles = {"x": COLUMN_ROLE_X, "y": COLUMN_ROLE_Y}
        if x_error is not None:
            columns["d"] = np.asarray(x_error, dtype=float)
            roles["d"] = COLUMN_ROLE_D
        if y_error is not None:
            columns["e"] = np.asarray(y_error, dtype=float)
            roles["e"] = COLUMN_ROLE_E
        frame = pd.DataFrame(columns)
        return cls(frame, column_roles=roles, names=names, units=units)

    # ------------------------------------------------------------------
    # DataFrame-backed properties
    # ------------------------------------------------------------------

    @property
    def df(self) -> pd.DataFrame:
        """The committed DataFrame rows (integer row index, columns = channels).

        Returns:
            (pd.DataFrame):
                A view containing committed rows only. Reserved append capacity
                is excluded.

        Examples:
            >>> import numpy as np, pandas as pd
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([1.0, 2.0]), np.array([3.0, 4.0]))
            >>> isinstance(td.df, pd.DataFrame)
            True
            >>> list(td.df.columns)
            ['x', 'y']
        """
        self._sync_external_growth()
        if self._row_count == self._capacity:
            return self._df
        return self._df.iloc[: self._row_count]

    @property
    def row_count(self) -> int:
        """Number of committed rows, excluding reserved append capacity."""
        self._sync_external_growth()
        return self._row_count

    def reserve_rows(self, capacity: int) -> None:
        """Reserve storage for at least *capacity* rows without exposing empty rows."""
        requested = max(self._row_count, int(capacity))
        if requested <= self._capacity:
            return
        self._df = self._df.reindex(pd.RangeIndex(requested))
        self._capacity = requested

    def append_row(self, row: dict[str, object], *, batch_size: int = 256) -> None:
        """Append one committed row, growing the backing frame in batches."""
        columns = list(self._df.columns)
        if set(row) != set(columns):
            missing = sorted(set(columns).difference(row))
            extra = sorted(set(row).difference(columns))
            raise ValueError(f"Trace row columns do not match: missing={missing!r}, extra={extra!r}")
        if self._row_count >= self._capacity:
            self.reserve_rows(self._capacity + max(1, int(batch_size)))
        self._df.iloc[self._row_count] = [row[column] for column in columns]
        self._row_count += 1

    def _sync_external_growth(self) -> None:
        """Account for legacy direct row additions when no capacity was reserved."""
        actual_rows = len(self._df)
        if actual_rows != self._capacity and self._row_count == self._capacity:
            self._row_count = actual_rows
            self._capacity = actual_rows

    @property
    def columns(self) -> list[str]:
        """Ordered list of column names in the underlying DataFrame.

        Returns:
            (list[str]):
                Column names in DataFrame order.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([1.0]), np.array([2.0]))
            >>> td.columns
            ['y']
        """
        return list(self._df.columns)

    # ------------------------------------------------------------------
    # Convenience array views
    # ------------------------------------------------------------------

    @property
    def x(self) -> np.ndarray:
        """Independent-variable values as a one-dimensional NumPy array.

        Returns:
            (np.ndarray):
                The ``COLUMN_ROLE_X`` column as a float64 array.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([0.0, 1.0]), np.array([2.0, 3.0]))
            >>> td.x.tolist()
            [0.0, 1.0]
        """
        cols = self.get_columns_by_role(COLUMN_ROLE_X)
        if not cols:
            return np.array([], dtype=float)
        return self.df[cols[0]].to_numpy(dtype=float)

    @property
    def y(self) -> np.ndarray:
        """First :data:`COLUMN_ROLE_Y`-role column as a one-dimensional NumPy array.

        Returns:
            (np.ndarray):
                The first ``"y"``-role column, or an empty float64 array if no
                such column exists.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([0.0, 1.0]), np.array([2.0, 3.0]))
            >>> td.y.tolist()
            [2.0, 3.0]
        """
        cols = self.get_columns_by_role(COLUMN_ROLE_Y)
        if not cols:
            return np.array([], dtype=float)
        return self.df[cols[0]].to_numpy(dtype=float)

    @property
    def d(self) -> np.ndarray:
        """First :data:`COLUMN_ROLE_D`-role column as a one-dimensional NumPy array.

        Returns:
            (np.ndarray):
                The first ``"d"``-role column, or an empty float64 array if no
                such column exists.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([0.0]), np.array([1.0]))
            >>> len(td.d)
            0
        """
        cols = self.get_columns_by_role(COLUMN_ROLE_D)
        if not cols:
            return np.array([], dtype=float)
        return self.df[cols[0]].to_numpy(dtype=float)

    @property
    def e(self) -> np.ndarray:
        """First :data:`COLUMN_ROLE_E`-role column as a one-dimensional NumPy array.

        Returns:
            (np.ndarray):
                The first ``"e"``-role column, or an empty float64 array if no
                such column exists.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([0.0]), np.array([1.0]))
            >>> len(td.e)
            0
        """
        cols = self.get_columns_by_role(COLUMN_ROLE_E)
        if not cols:
            return np.array([], dtype=float)
        return self.df[cols[0]].to_numpy(dtype=float)

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
            >>> from stoner_measurement.core import (
            ...     TraceData, COLUMN_ROLE_Y, COLUMN_ROLE_E,
            ... )
            >>> td = TraceData.from_xy(np.array([1.0]), np.array([2.0]))
            >>> td.get_columns_by_role(COLUMN_ROLE_Y)
            ['y']
            >>> td.get_columns_by_role(COLUMN_ROLE_E)
            []
        """
        return [col for col in self._df.columns if self.column_roles.get(col) == role]

    def __str__(self) -> str:
        """Return a concise summary of the trace shape and columns."""
        return f"TraceData(columns={self.columns!r}, rows={self.row_count})"

    def __repr__(self) -> str:
        """Return the human-friendly trace summary."""
        return str(self)
