"""Tests for the TraceData class and COLUMN_ROLE_* constants."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stoner_measurement.plugins.trace.base import (
    COLUMN_ROLE_D,
    COLUMN_ROLE_E,
    COLUMN_ROLE_F,
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
)

# ---------------------------------------------------------------------------
# Role constant values
# ---------------------------------------------------------------------------


class TestRoleConstants:
    def test_column_role_y(self):
        assert COLUMN_ROLE_Y == "y"

    def test_column_role_z(self):
        assert COLUMN_ROLE_Z == "z"

    def test_column_role_d(self):
        assert COLUMN_ROLE_D == "d"

    def test_column_role_e(self):
        assert COLUMN_ROLE_E == "e"

    def test_column_role_f(self):
        assert COLUMN_ROLE_F == "f"

    def test_constants_exported_from_trace_package(self):
        from stoner_measurement.plugins.trace import (  # noqa: PLC0415
            COLUMN_ROLE_D as D,
            COLUMN_ROLE_Y as Y,
        )

        assert Y == "y"
        assert D == "d"


# ---------------------------------------------------------------------------
# Legacy (backward-compatible) constructor path
# ---------------------------------------------------------------------------


class TestLegacyConstructor:
    def test_x_array(self):
        td = TraceData(x=np.array([1.0, 2.0, 3.0]), y=np.array([4.0, 5.0, 6.0]))
        np.testing.assert_array_equal(td.x, [1.0, 2.0, 3.0])

    def test_y_array(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        np.testing.assert_array_equal(td.y, [3.0, 4.0])

    def test_default_x_is_empty(self):
        td = TraceData()
        assert len(td.x) == 0

    def test_default_y_is_empty(self):
        td = TraceData()
        assert len(td.y) == 0

    def test_default_d_is_empty(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        assert len(td.d) == 0

    def test_default_e_is_empty(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        assert len(td.e) == 0

    def test_d_array_stored(self):
        td = TraceData(
            x=np.array([1.0]), y=np.array([2.0]), d=np.array([0.1])
        )
        np.testing.assert_array_almost_equal(td.d, [0.1])

    def test_e_array_stored(self):
        td = TraceData(
            x=np.array([1.0]), y=np.array([2.0]), e=np.array([0.05])
        )
        np.testing.assert_array_almost_equal(td.e, [0.05])

    def test_empty_d_not_added_as_column(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]), d=np.array([]))
        assert "d" not in td.columns

    def test_empty_e_not_added_as_column(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]), e=np.array([]))
        assert "e" not in td.columns

    def test_names_passed_through(self):
        td = TraceData(
            x=np.array([1.0]),
            y=np.array([2.0]),
            names={"x": "Current", "y": "Voltage", "d": "", "e": ""},
        )
        assert td.names["x"] == "Current"
        assert td.names["y"] == "Voltage"

    def test_units_passed_through(self):
        td = TraceData(
            x=np.array([1.0]),
            y=np.array([2.0]),
            units={"x": "A", "y": "V", "d": "", "e": ""},
        )
        assert td.units["x"] == "A"
        assert td.units["y"] == "V"

    def test_default_names_set(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        assert "x" in td.names
        assert "y" in td.names

    def test_default_units_set(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        assert "x" in td.units
        assert "y" in td.units

    def test_y_column_role_is_y(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        assert td.column_roles["y"] == COLUMN_ROLE_Y

    def test_d_column_role_is_d(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]), d=np.array([0.1]))
        assert td.column_roles["d"] == COLUMN_ROLE_D

    def test_e_column_role_is_e(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]), e=np.array([0.05]))
        assert td.column_roles["e"] == COLUMN_ROLE_E

    def test_x_is_numpy_array(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        assert isinstance(td.x, np.ndarray)

    def test_y_is_numpy_array(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        assert isinstance(td.y, np.ndarray)

    def test_none_d_treated_as_absent(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]), d=None)
        assert len(td.d) == 0

    def test_none_e_treated_as_absent(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]), e=None)
        assert len(td.e) == 0


# ---------------------------------------------------------------------------
# New-style (DataFrame) constructor path
# ---------------------------------------------------------------------------


class TestDataFrameConstructor:
    def test_x_from_index(self):
        df = pd.DataFrame({"y": [3.0, 4.0]}, index=pd.Index([1.0, 2.0], name="x"))
        td = TraceData(df=df, column_roles={"y": COLUMN_ROLE_Y})
        np.testing.assert_array_equal(td.x, [1.0, 2.0])

    def test_y_from_column(self):
        df = pd.DataFrame({"y": [3.0, 4.0]}, index=pd.Index([1.0, 2.0], name="x"))
        td = TraceData(df=df, column_roles={"y": COLUMN_ROLE_Y})
        np.testing.assert_array_equal(td.y, [3.0, 4.0])

    def test_column_roles_stored(self):
        df = pd.DataFrame({"y": [1.0], "z": [2.0]}, index=pd.Index([0.0], name="x"))
        roles = {"y": COLUMN_ROLE_Y, "z": COLUMN_ROLE_Z}
        td = TraceData(df=df, column_roles=roles)
        assert td.column_roles == roles

    def test_names_stored(self):
        df = pd.DataFrame({"y": [1.0]}, index=pd.Index([0.0], name="x"))
        td = TraceData(df=df, column_roles={"y": COLUMN_ROLE_Y}, names={"x": "I", "y": "V"})
        assert td.names == {"x": "I", "y": "V"}

    def test_units_stored(self):
        df = pd.DataFrame({"y": [1.0]}, index=pd.Index([0.0], name="x"))
        td = TraceData(df=df, column_roles={"y": COLUMN_ROLE_Y}, units={"x": "A", "y": "V"})
        assert td.units == {"x": "A", "y": "V"}

    def test_df_is_copy(self):
        df = pd.DataFrame({"y": [1.0]}, index=pd.Index([0.0], name="x"))
        td = TraceData(df=df, column_roles={"y": COLUMN_ROLE_Y})
        df["y"] = [99.0]
        assert td.df["y"].iloc[0] == 1.0  # internal copy unaffected

    def test_empty_column_roles_default(self):
        df = pd.DataFrame({"y": [1.0]}, index=pd.Index([0.0], name="x"))
        td = TraceData(df=df)
        assert isinstance(td.column_roles, dict)

    def test_no_y_role_returns_empty_y(self):
        df = pd.DataFrame({"z": [1.0]}, index=pd.Index([0.0], name="x"))
        td = TraceData(df=df, column_roles={"z": COLUMN_ROLE_Z})
        assert len(td.y) == 0

    def test_multi_column_df(self):
        df = pd.DataFrame(
            {"y": [1.0, 2.0], "z": [3.0, 4.0]},
            index=pd.Index([0.0, 1.0], name="x"),
        )
        td = TraceData(df=df, column_roles={"y": COLUMN_ROLE_Y, "z": COLUMN_ROLE_Z})
        assert td.columns == ["y", "z"]


# ---------------------------------------------------------------------------
# .df and .columns properties
# ---------------------------------------------------------------------------


class TestDfProperty:
    def test_df_is_dataframe(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        assert isinstance(td.df, pd.DataFrame)

    def test_df_index_matches_x(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        np.testing.assert_array_equal(td.df.index.to_numpy(), [1.0, 2.0])

    def test_df_has_y_column(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        assert "y" in td.df.columns

    def test_columns_list(self):
        td = TraceData(
            x=np.array([1.0]),
            y=np.array([2.0]),
            d=np.array([0.1]),
            e=np.array([0.05]),
        )
        assert "y" in td.columns
        assert "d" in td.columns
        assert "e" in td.columns

    def test_columns_returns_list_type(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        assert isinstance(td.columns, list)


# ---------------------------------------------------------------------------
# get_columns_by_role
# ---------------------------------------------------------------------------


class TestGetColumnsByRole:
    def test_y_role(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        assert td.get_columns_by_role(COLUMN_ROLE_Y) == ["y"]

    def test_d_role(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]), d=np.array([0.1]))
        assert td.get_columns_by_role(COLUMN_ROLE_D) == ["d"]

    def test_e_role(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]), e=np.array([0.05]))
        assert td.get_columns_by_role(COLUMN_ROLE_E) == ["e"]

    def test_missing_role_returns_empty(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        assert td.get_columns_by_role(COLUMN_ROLE_Z) == []

    def test_multiple_columns_same_role(self):
        df = pd.DataFrame(
            {"y1": [1.0], "y2": [2.0]},
            index=pd.Index([0.0], name="x"),
        )
        td = TraceData(df=df, column_roles={"y1": COLUMN_ROLE_Y, "y2": COLUMN_ROLE_Y})
        cols = td.get_columns_by_role(COLUMN_ROLE_Y)
        assert "y1" in cols
        assert "y2" in cols
        assert len(cols) == 2

    def test_new_style_z_role(self):
        df = pd.DataFrame(
            {"y": [1.0], "z": [2.0]},
            index=pd.Index([0.0], name="x"),
        )
        td = TraceData(df=df, column_roles={"y": COLUMN_ROLE_Y, "z": COLUMN_ROLE_Z})
        assert td.get_columns_by_role(COLUMN_ROLE_Z) == ["z"]

    def test_role_order_follows_dataframe_column_order(self):
        df = pd.DataFrame(
            {"y1": [1.0], "e1": [0.1], "y2": [2.0], "e2": [0.2]},
            index=pd.Index([0.0], name="x"),
        )
        td = TraceData(
            df=df,
            column_roles={
                "e2": COLUMN_ROLE_E,
                "y2": COLUMN_ROLE_Y,
                "e1": COLUMN_ROLE_E,
                "y1": COLUMN_ROLE_Y,
            },
        )
        assert td.get_columns_by_role(COLUMN_ROLE_Y) == ["y1", "y2"]
        assert td.get_columns_by_role(COLUMN_ROLE_E) == ["e1", "e2"]


# ---------------------------------------------------------------------------
# add_column
# ---------------------------------------------------------------------------


class TestAddColumn:
    def test_add_z_column(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        td.add_column("z", np.array([5.0, 6.0]), COLUMN_ROLE_Z)
        assert "z" in td.columns
        np.testing.assert_array_equal(td.df["z"], [5.0, 6.0])

    def test_add_column_updates_roles(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        td.add_column("z", np.array([3.0]), COLUMN_ROLE_Z)
        assert td.column_roles["z"] == COLUMN_ROLE_Z

    def test_add_f_column(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        td.add_column("dz", np.array([0.01]), COLUMN_ROLE_F)
        assert td.column_roles["dz"] == COLUMN_ROLE_F

    def test_invalid_role_raises(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        with pytest.raises(ValueError, match="Invalid column role"):
            td.add_column("bad", np.array([1.0]), "not_a_role")

    def test_get_columns_by_role_after_add(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        td.add_column("z", np.array([5.0, 6.0]), COLUMN_ROLE_Z)
        assert td.get_columns_by_role(COLUMN_ROLE_Z) == ["z"]

    def test_add_second_y_column(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        td.add_column("y2", np.array([3.0]), COLUMN_ROLE_Y)
        y_cols = td.get_columns_by_role(COLUMN_ROLE_Y)
        assert "y" in y_cols
        assert "y2" in y_cols


# ---------------------------------------------------------------------------
# Backward-compatible __iter__ and __getitem__
# ---------------------------------------------------------------------------


class TestIterAndGetItem:
    def test_iter_two_elements(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        items = list(td)
        assert len(items) == 2

    def test_iter_first_is_x(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        x_arr, _ = td
        np.testing.assert_array_equal(x_arr, [1.0, 2.0])

    def test_iter_second_is_y(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        _, y_arr = td
        np.testing.assert_array_equal(y_arr, [3.0, 4.0])

    def test_getitem_0_is_x(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        np.testing.assert_array_equal(td[0], td.x)

    def test_getitem_1_is_y(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        np.testing.assert_array_equal(td[1], td.y)

    def test_getitem_2_is_d(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]), d=np.array([0.1]))
        np.testing.assert_array_equal(td[2], td.d)

    def test_getitem_3_is_e(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]), e=np.array([0.05]))
        np.testing.assert_array_equal(td[3], td.e)

    def test_getitem_out_of_range_raises(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        with pytest.raises(IndexError):
            _ = td[4]

    def test_getitem_negative_raises(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        with pytest.raises(IndexError):
            _ = td[-1]

    def test_getitem_0_values_match_x(self):
        td = TraceData(x=np.array([5.0, 6.0]), y=np.array([7.0, 8.0]))
        np.testing.assert_array_equal(td[0], [5.0, 6.0])

    def test_getitem_1_values_match_y(self):
        td = TraceData(x=np.array([5.0, 6.0]), y=np.array([7.0, 8.0]))
        np.testing.assert_array_equal(td[1], [7.0, 8.0])


# ---------------------------------------------------------------------------
# Multi-column DataFrame construction and access
# ---------------------------------------------------------------------------


class TestMultiColumnData:
    def test_two_y_columns_via_new_style(self):
        df = pd.DataFrame(
            {"channel_a": [1.0, 2.0], "channel_b": [3.0, 4.0]},
            index=pd.Index([0.0, 1.0], name="x"),
        )
        td = TraceData(
            df=df,
            column_roles={"channel_a": COLUMN_ROLE_Y, "channel_b": COLUMN_ROLE_Y},
        )
        assert len(td.get_columns_by_role(COLUMN_ROLE_Y)) == 2

    def test_first_y_role_returned_by_y_property(self):
        df = pd.DataFrame(
            {"a": [1.0], "b": [2.0]},
            index=pd.Index([0.0], name="x"),
        )
        td = TraceData(df=df, column_roles={"a": COLUMN_ROLE_Y, "b": COLUMN_ROLE_Y})
        np.testing.assert_array_equal(td.y, [1.0])

    def test_d_column_via_add_column(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        td.add_column("dx_err", np.array([0.1, 0.2]), COLUMN_ROLE_D)
        np.testing.assert_array_almost_equal(td.d, [0.1, 0.2])

    def test_e_column_via_add_column(self):
        td = TraceData(x=np.array([1.0, 2.0]), y=np.array([3.0, 4.0]))
        td.add_column("dy_err", np.array([0.01, 0.02]), COLUMN_ROLE_E)
        np.testing.assert_array_almost_equal(td.e, [0.01, 0.02])

    def test_names_for_extra_column(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        td.add_column("z", np.array([3.0]), COLUMN_ROLE_Z)
        td.names["z"] = "Height"
        assert td.names["z"] == "Height"

    def test_units_for_extra_column(self):
        td = TraceData(x=np.array([1.0]), y=np.array([2.0]))
        td.add_column("z", np.array([3.0]), COLUMN_ROLE_Z)
        td.units["z"] = "m"
        assert td.units["z"] == "m"


# ---------------------------------------------------------------------------
# Integration: measure() returns DataFrame-backed TraceData
# ---------------------------------------------------------------------------


class TestMeasureReturnsTraceData:
    def test_measure_returns_tracedata_with_df(self, qapp):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        result = plugin.measure({})
        td = result["Dummy"]
        assert isinstance(td.df, pd.DataFrame)

    def test_measure_column_roles_set(self, qapp):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.2, 0.1, True)], parent=plugin
        )
        result = plugin.measure({})
        td = result["Dummy"]
        assert td.get_columns_by_role(COLUMN_ROLE_Y) == ["y"]

    def test_measure_names_passed_to_tracedata(self, qapp):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.2, 0.1, True)], parent=plugin
        )
        result = plugin.measure({})
        td = result["Dummy"]
        assert td.names.get("x") == "I"
        assert td.names.get("y") == "V"

    def test_measure_units_passed_to_tracedata(self, qapp):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.2, 0.1, True)], parent=plugin
        )
        result = plugin.measure({})
        td = result["Dummy"]
        assert td.units.get("x") == "A"
        assert td.units.get("y") == "V"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "--pdb"]))
