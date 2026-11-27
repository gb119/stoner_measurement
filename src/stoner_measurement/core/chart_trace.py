"""Append-only trace storage for controller chart samples."""

from __future__ import annotations

from threading import RLock

import numpy as np
import pandas as pd

from stoner_measurement.core.trace_data import COLUMN_ROLE_Y, TraceData


class ChartTrace(TraceData):
    """Store controller history with detached table reads across threads."""

    def __init__(self, owner: object) -> None:
        super().__init__(names={"x": "Unix time"}, units={"x": "s"})
        self.owner = owner
        self._channels: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def append(self, timestamp: float, samples: dict[tuple[str, str], float]) -> bool:
        """Append one update and return whether it introduced new columns."""
        with self._lock:
            changed = self._add_columns(
                [channel for channel in samples if channel not in self._channels]
            )
            row: dict[str, object] = dict.fromkeys(self.columns, np.nan)
            row["x"] = timestamp
            row.update((self._channels[channel], value) for channel, value in samples.items())
            self.append_row(row, batch_size=max(256, self.row_count // 2))
            return changed

    def _add_columns(self, missing: list[tuple[str, str]]) -> bool:
        if not missing:
            return False
        columns = self.columns
        names = dict(self.names)
        units = dict(self.units)
        roles = dict(self.column_roles)
        for label, unit in missing:
            column = label
            suffix = 1
            while column in names:
                suffix += 1
                column = f"{label} [{suffix}]"
            self._channels[label, unit] = column
            columns.append(column)
            names[column] = label
            units[column] = unit
            roles[column] = COLUMN_ROLE_Y
        super().__init__(
            super().df.reindex(columns=columns), column_roles=roles, names=names, units=units
        )
        return True

    @property
    def df(self) -> pd.DataFrame:
        """Return a detached dataframe safe to read while chart updates append."""
        with self._lock:
            return super().df.copy()

    @property
    def row_count(self) -> int:
        """Return the number of recorded rows under the chart lock."""
        with self._lock:
            return super().row_count

    def snapshot(self) -> TraceData:
        """Copy the complete trace for operations that read several columns."""
        with self._lock:
            return TraceData(
                super().df, column_roles=self.column_roles, names=self.names, units=self.units
            )

    def schema(self) -> TraceData:
        """Return the known chart columns without copying the acquired rows."""
        with self._lock:
            return TraceData(
                super().df.iloc[:0],
                column_roles=self.column_roles,
                names=self.names,
                units=self.units,
            )

    def clear(self) -> None:
        """Discard recorded rows while retaining channel names and units."""
        with self._lock:
            super().clear()

    def append_row(self, row: dict[str, object], *, batch_size: int = 256) -> None:
        """Append a row while excluding concurrent clears and table reads."""
        with self._lock:
            super().append_row(row, batch_size=batch_size)
