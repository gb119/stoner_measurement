"""Tests for concise core TraceData representations."""

from __future__ import annotations

import pandas as pd
import pytest

from stoner_measurement.core import (
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
)


def test_representation_reports_columns_and_rows():
    df = pd.DataFrame(
        {"x": [0.0, 1.0], "voltage": [1.0, 2.0], "current": [3.0, 4.0]}
    )
    trace = TraceData(
        df=df,
        column_roles={"voltage": COLUMN_ROLE_Y, "current": COLUMN_ROLE_Z},
    )

    assert str(trace) == "TraceData(columns=['x', 'voltage', 'current'], rows=2)"
    assert repr(trace) == str(trace)


def test_representation_reports_empty_trace():
    trace = TraceData()

    assert str(trace) == "TraceData(columns=['x'], rows=0)"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
