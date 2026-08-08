"""Shared tabular measurement data structures."""

from __future__ import annotations

import numpy as np
import pandas as pd

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

_VALID_ROLES: frozenset[str] = frozenset(
    {COLUMN_ROLE_Y, COLUMN_ROLE_Z, COLUMN_ROLE_D, COLUMN_ROLE_E}
)


class TraceData:
    """One complete trace table with a shared independent-variable axis.

    The DataFrame index stores x and each DataFrame column stores measured,
    derived, or uncertainty data on that same x grid.  Column roles identify
    primary data (``y``), auxiliary data (``z``), x uncertainty (``d``), and
    y uncertainty (``e``).  Missing roles default to primary for the first
    column and auxiliary for subsequent columns.

    ``names`` and ``units`` are completed for ``"x"`` and every DataFrame
    column during construction.  Unknown role or metadata keys are rejected so
    these mappings cannot silently drift away from the table.

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
        self._df = pd.DataFrame() if df is None else df.copy()
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
        for index, column in enumerate(columns):
            roles.setdefault(column, COLUMN_ROLE_Y if index == 0 else COLUMN_ROLE_Z)
        self.column_roles = roles

        valid_metadata_keys = {"x", *columns}
        supplied_names = dict(names or {})
        supplied_units = dict(units or {})
        unknown_metadata = (set(supplied_names) | set(supplied_units)).difference(valid_metadata_keys)
        if unknown_metadata:
            raise ValueError(f"Trace metadata references unknown columns: {sorted(unknown_metadata)!r}")
        self.names = {"x": supplied_names.get("x", "x")}
        self.units = {"x": supplied_units.get("x", "")}
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
        columns: dict[str, np.ndarray] = {"y": np.asarray(y, dtype=float)}
        roles = {"y": COLUMN_ROLE_Y}
        if x_error is not None:
            columns["d"] = np.asarray(x_error, dtype=float)
            roles["d"] = COLUMN_ROLE_D
        if y_error is not None:
            columns["e"] = np.asarray(y_error, dtype=float)
            roles["e"] = COLUMN_ROLE_E
        frame = pd.DataFrame(columns, index=pd.Index(np.asarray(x, dtype=float), name="x"))
        return cls(frame, column_roles=roles, names=names, units=units)

    # ------------------------------------------------------------------
    # DataFrame-backed properties
    # ------------------------------------------------------------------

    @property
    def df(self) -> pd.DataFrame:
        """The underlying :class:`pandas.DataFrame` (index = x, columns = data).

        Returns:
            (pd.DataFrame):
                The backing DataFrame.  All columns are established when the
                :class:`TraceData` object is constructed.

        Examples:
            >>> import numpy as np, pandas as pd
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([1.0, 2.0]), np.array([3.0, 4.0]))
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
                The DataFrame index as a float64 array.

        Examples:
            >>> import numpy as np
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([0.0, 1.0]), np.array([2.0, 3.0]))
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
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([0.0, 1.0]), np.array([2.0, 3.0]))
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
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([0.0]), np.array([1.0]))
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
            >>> from stoner_measurement.core import TraceData
            >>> td = TraceData.from_xy(np.array([0.0]), np.array([1.0]))
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
        return f"TraceData(columns={self.columns!r}, rows={len(self._df)})"

    def __repr__(self) -> str:
        """Return the human-friendly trace summary."""
        return str(self)
