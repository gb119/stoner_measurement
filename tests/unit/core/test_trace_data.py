"""Focused tests for the canonical core TraceData contract."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stoner_measurement.core import (
    COLUMN_ROLE_D,
    COLUMN_ROLE_E,
    COLUMN_ROLE_X,
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
)


def _frame(**columns: list[float]) -> pd.DataFrame:
    """Return a numeric trace frame with a conventional x column."""
    length = len(next(iter(columns.values()), []))
    return pd.DataFrame({"x": np.arange(length, dtype=float), **columns})


class TestConstruction:
    def test_empty_trace_has_no_columns(self):
        trace = TraceData()
        assert trace.columns == ["x"]
        assert trace.names == {"x": "x"}
        assert trace.units == {"x": ""}

    def test_input_frame_is_copied(self):
        frame = _frame(signal=[1.0, 2.0])
        trace = TraceData(frame)
        frame.loc[0, "signal"] = 99.0
        assert trace.df.loc[0, "signal"] == 1.0

    def test_roles_default_to_primary_then_auxiliary(self):
        trace = TraceData(_frame(voltage=[1.0], resistance=[2.0]))
        assert trace.column_roles == {
            "x": COLUMN_ROLE_X,
            "voltage": COLUMN_ROLE_Y,
            "resistance": COLUMN_ROLE_Z,
        }

    def test_explicit_roles_are_preserved(self):
        trace = TraceData(
            _frame(a=[1.0], b=[2.0]),
            column_roles={"a": COLUMN_ROLE_Y, "b": COLUMN_ROLE_Y},
        )
        assert trace.get_columns_by_role(COLUMN_ROLE_Y) == ["a", "b"]

    def test_missing_explicit_roles_receive_defaults(self):
        trace = TraceData(
            _frame(signal=[1.0], error=[0.1]),
            column_roles={"error": COLUMN_ROLE_E},
        )
        assert trace.column_roles == {
            "x": COLUMN_ROLE_X,
            "signal": COLUMN_ROLE_Y,
            "error": COLUMN_ROLE_E,
        }

    def test_rejects_unknown_role_column(self):
        with pytest.raises(ValueError, match="unknown columns"):
            TraceData(_frame(signal=[1.0]), column_roles={"missing": COLUMN_ROLE_Y})

    def test_rejects_invalid_role(self):
        with pytest.raises(ValueError, match="Invalid column roles"):
            TraceData(_frame(signal=[1.0]), column_roles={"signal": "invalid"})

    def test_rejects_duplicate_columns(self):
        frame = pd.DataFrame([[0.0, 1.0, 2.0]], columns=["x", "signal", "signal"])
        with pytest.raises(ValueError, match="unique names"):
            TraceData(frame)


class TestMetadata:
    def test_metadata_defaults_cover_every_column(self):
        trace = TraceData(_frame(voltage=[1.0], current=[2.0]))
        assert trace.names == {"x": "x", "voltage": "voltage", "current": "current"}
        assert trace.units == {"x": "", "voltage": "", "current": ""}

    def test_supplied_metadata_is_completed(self):
        trace = TraceData(
            _frame(voltage=[1.0], current=[2.0]),
            names={"x": "Time", "voltage": "Voltage"},
            units={"x": "s", "voltage": "V"},
        )
        assert trace.names["current"] == "current"
        assert trace.units["current"] == ""

    def test_rejects_metadata_for_unknown_columns(self):
        with pytest.raises(ValueError, match="metadata references unknown columns"):
            TraceData(_frame(signal=[1.0]), names={"missing": "Missing"})


class TestArrayViews:
    def test_x_is_dataframe_column_and_index_is_integer_range(self):
        trace = TraceData(_frame(signal=[1.0, 2.0]))
        np.testing.assert_array_equal(trace.x, [0.0, 1.0])
        assert isinstance(trace.df.index, pd.RangeIndex)
        assert trace.df.index.tolist() == [0, 1]

    def test_y_is_first_primary_column(self):
        trace = TraceData(
            _frame(a=[1.0, 2.0], b=[3.0, 4.0]),
            column_roles={"a": COLUMN_ROLE_Y, "b": COLUMN_ROLE_Y},
        )
        np.testing.assert_array_equal(trace.y, [1.0, 2.0])

    def test_missing_optional_views_are_empty(self):
        trace = TraceData(_frame(signal=[1.0]))
        assert trace.d.size == 0
        assert trace.e.size == 0

    def test_error_views_follow_roles(self):
        trace = TraceData(
            _frame(signal=[1.0], x_error=[0.1], y_error=[0.2]),
            column_roles={
                "signal": COLUMN_ROLE_Y,
                "x_error": COLUMN_ROLE_D,
                "y_error": COLUMN_ROLE_E,
            },
        )
        np.testing.assert_array_equal(trace.d, [0.1])
        np.testing.assert_array_equal(trace.e, [0.2])


class TestFromXY:
    def test_builds_single_column_trace(self):
        trace = TraceData.from_xy(np.array([1.0, 2.0]), np.array([3.0, 4.0]))
        assert trace.columns == ["x", "y"]
        np.testing.assert_array_equal(trace.y, [3.0, 4.0])

    def test_builds_optional_error_columns(self):
        trace = TraceData.from_xy(
            np.array([1.0]),
            np.array([2.0]),
            x_error=np.array([0.1]),
            y_error=np.array([0.2]),
        )
        assert trace.column_roles == {
            "x": COLUMN_ROLE_X,
            "y": COLUMN_ROLE_Y,
            "d": COLUMN_ROLE_D,
            "e": COLUMN_ROLE_E,
        }


def test_representation_summarises_shape():
    trace = TraceData(_frame(voltage=[1.0, 2.0], current=[3.0, 4.0]))
    assert str(trace) == "TraceData(columns=['x', 'voltage', 'current'], rows=2)"
    assert repr(trace) == str(trace)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
