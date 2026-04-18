"""Tests for ListScanGenerator and ListScanWidget."""

from __future__ import annotations

import numpy as np
import pytest
from PyQt6.QtWidgets import QWidget

from stoner_measurement.scan import BaseScanGenerator, ListScanGenerator, ListScanWidget


class TestListScanGenerator:
    # ------------------------------------------------------------------
    # Construction and defaults
    # ------------------------------------------------------------------

    def test_empty_stages_yields_empty_array(self, qapp):
        """Empty stages → empty array."""
        gen = ListScanGenerator()
        values = gen.generate()
        assert len(values) == 0
        assert isinstance(values, np.ndarray)

    def test_default_stages_empty(self, qapp):
        gen = ListScanGenerator()
        assert gen.stages == []

    def test_custom_stages(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
        assert gen.stages == [(1.0, True), (2.0, False)]

    # ------------------------------------------------------------------
    # generate()
    # ------------------------------------------------------------------

    def test_generate_returns_ndarray(self, qapp):
        gen = ListScanGenerator(stages=[(0.0, True)])
        assert isinstance(gen.generate(), np.ndarray)

    def test_generate_single_stage(self, qapp):
        gen = ListScanGenerator(stages=[(5.0, True)])
        assert np.allclose(gen.generate(), [5.0])

    def test_generate_multiple_stages(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (3.0, False), (2.0, True)])
        assert np.allclose(gen.generate(), [1.0, 3.0, 2.0])

    def test_generate_preserves_order(self, qapp):
        targets = [4.0, 1.0, 3.0, 2.0]
        gen = ListScanGenerator(stages=[(t, True) for t in targets])
        assert gen.generate().tolist() == targets

    def test_generate_empty_stages(self, qapp):
        gen = ListScanGenerator()
        result = gen.generate()
        assert len(result) == 0

    def test_generate_dtype_is_float(self, qapp):
        gen = ListScanGenerator(stages=[(1, True), (2, False)])
        assert gen.generate().dtype == float

    # ------------------------------------------------------------------
    # measure_flags()
    # ------------------------------------------------------------------

    def test_measure_flags_length_matches_generate(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
        assert len(gen.measure_flags()) == len(gen.generate())

    def test_measure_flags_empty_stages_returns_empty(self, qapp):
        gen = ListScanGenerator()
        flags = gen.measure_flags()
        assert len(flags) == 0
        assert isinstance(flags, np.ndarray)

    def test_measure_flags_returns_boolean_array(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
        flags = gen.measure_flags()
        assert isinstance(flags, np.ndarray)
        assert flags.dtype == bool

    def test_measure_flags_all_true(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, True), (3.0, True)])
        assert gen.measure_flags().tolist() == [True, True, True]

    def test_measure_flags_all_false(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, False), (2.0, False)])
        assert gen.measure_flags().tolist() == [False, False]

    def test_measure_flags_mixed(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False), (3.0, True)])
        assert gen.measure_flags().tolist() == [True, False, True]

    # ------------------------------------------------------------------
    # stages setter
    # ------------------------------------------------------------------

    def test_stages_setter_updates_stages(self, qapp):
        gen = ListScanGenerator()
        gen.stages = [(1.0, True), (2.0, False)]
        assert gen.stages == [(1.0, True), (2.0, False)]

    def test_stages_setter_coerces_types(self, qapp):
        gen = ListScanGenerator()
        gen.stages = [(1, 1), (2, 0)]
        assert gen.stages == [(1.0, True), (2.0, False)]

    def test_stages_setter_invalidates_cache(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True)])
        _ = gen.values
        gen.stages = [(2.0, False)]
        assert gen._cache is None

    def test_stages_setter_emits_signal(self, qapp):
        gen = ListScanGenerator()
        received: list[None] = []
        gen.values_changed.connect(lambda: received.append(None))
        gen.stages = [(1.0, True)]
        assert len(received) == 1

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def test_values_cached(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True)])
        assert gen.values is gen.values

    def test_flags_cached(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True)])
        assert gen.flags is gen.flags

    def test_cache_invalidated_on_stages_change(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True)])
        _ = gen.values
        gen.stages = [(2.0, False)]
        assert gen._cache is None

    def test_flags_cache_invalidated_on_stages_change(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True)])
        _ = gen.flags
        gen.stages = [(2.0, False)]
        assert gen._flags_cache is None

    def test_values_recomputed_after_invalidation(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True)])
        first = gen.values
        gen.stages = [(2.0, False)]
        second = gen.values
        assert first is not second

    # ------------------------------------------------------------------
    # Iterator interface
    # ------------------------------------------------------------------

    def test_iter_yields_all_values(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
        results = list(gen)
        values = [v for _, v, _, _ in results]
        assert np.allclose(values, [1.0, 2.0])

    def test_iter_flags_match_measure_flags(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
        results = list(gen)
        flags = [f for _, _, f, _ in results]
        assert flags == [True, False]

    def test_iter_indices_are_sequential(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, True), (3.0, True)])
        results = list(gen)
        indices = [i for i, _, _, _ in results]
        assert indices == [0, 1, 2]

    def test_iter_stage_is_zero(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, True)])
        results = list(gen)
        assert [stage for _, _, _, stage in results] == [0, 0]

    def test_len(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
        assert len(gen) == 2

    def test_len_empty(self, qapp):
        gen = ListScanGenerator()
        assert len(gen) == 0

    def test_reset_allows_reiteration(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
        first = list(gen)
        gen.reset()
        second = list(gen)
        assert first == second

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def test_values_changed_emitted_on_stages_change(self, qapp):
        gen = ListScanGenerator()
        received: list[None] = []
        gen.values_changed.connect(lambda: received.append(None))
        gen.stages = [(1.0, True)]
        assert len(received) == 1

    # ------------------------------------------------------------------
    # JSON serialisation
    # ------------------------------------------------------------------

    def test_to_json_type(self, qapp):
        gen = ListScanGenerator()
        assert gen.to_json()["type"] == "ListScanGenerator"

    def test_to_json_stages(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
        assert gen.to_json()["stages"] == [[1.0, True], [2.0, False]]

    def test_from_json_data_round_trip(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (3.0, False)])
        restored = ListScanGenerator._from_json_data(gen.to_json())
        assert restored.stages == gen.stages

    def test_from_json_empty_stages(self, qapp):
        gen = ListScanGenerator()
        restored = ListScanGenerator._from_json_data(gen.to_json())
        assert restored.stages == []

    def test_base_from_json_dispatch(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True)])
        restored = BaseScanGenerator.from_json(gen.to_json())
        assert isinstance(restored, ListScanGenerator)
        assert restored.stages == gen.stages

    # ------------------------------------------------------------------
    # config_widget()
    # ------------------------------------------------------------------

    def test_config_widget_returns_list_scan_widget(self, qapp):
        gen = ListScanGenerator()
        widget = gen.config_widget()
        assert isinstance(widget, ListScanWidget)

    def test_config_widget_bound_to_generator(self, qapp):
        gen = ListScanGenerator()
        widget = gen.config_widget()
        assert widget.get_generator() is gen


class TestListScanWidget:
    # ------------------------------------------------------------------
    # Instantiation
    # ------------------------------------------------------------------

    def test_instantiates(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        assert widget is not None

    def test_is_qwidget(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        assert isinstance(widget, QWidget)

    def test_get_generator(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        assert widget.get_generator() is gen

    # ------------------------------------------------------------------
    # Tab structure
    # ------------------------------------------------------------------

    def test_has_two_tabs(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        assert widget._tabs.count() == 2

    def test_tab_names(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        assert widget._tabs.tabText(0) == "Points"
        assert widget._tabs.tabText(1) == "Preview"

    # ------------------------------------------------------------------
    # Add / remove rows
    # ------------------------------------------------------------------

    def test_add_point_button_adds_row(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        initial_rows = widget._table.rowCount()
        widget._add_btn.click()
        assert widget._table.rowCount() == initial_rows + 1

    def test_add_point_button_updates_generator(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        widget._add_btn.click()
        assert len(gen.stages) == 1

    def test_remove_point_button_removes_selected_row(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        widget._add_btn.click()
        widget._add_btn.click()
        assert widget._table.rowCount() == 2
        widget._table.selectRow(0)
        widget._remove_btn.click()
        assert widget._table.rowCount() == 1

    def test_remove_point_button_updates_generator(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        widget._add_btn.click()
        widget._add_btn.click()
        widget._table.selectRow(0)
        widget._remove_btn.click()
        assert len(gen.stages) == 1

    def test_table_populated_from_generator_stages(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
        widget = ListScanWidget(generator=gen)
        assert widget._table.rowCount() == 2

    # ------------------------------------------------------------------
    # Table cell edits propagate to generator
    # ------------------------------------------------------------------

    def test_table_target_change_updates_generator(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        widget._add_btn.click()
        target_spin = widget._table.cellWidget(0, 0)
        target_spin.setValue(7.5)
        assert gen.stages[0][0] == pytest.approx(7.5)

    def test_table_measure_change_updates_generator(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        widget._add_btn.click()
        measure_cb = widget._table.cellWidget(0, 1)
        measure_cb.setChecked(False)
        assert gen.stages[0][1] is False

    # ------------------------------------------------------------------
    # Plot (Preview tab)
    # ------------------------------------------------------------------

    def test_green_points_for_measure_true(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, True)])
        widget = ListScanWidget(generator=gen)
        x_green, _ = widget._green_scatter.getData()
        n_true = int(gen.flags.sum())
        assert x_green is not None
        assert len(x_green) == n_true

    def test_red_points_for_measure_false(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, False), (2.0, False)])
        widget = ListScanWidget(generator=gen)
        x_red, _ = widget._red_scatter.getData()
        n_false = int((~gen.flags).sum())
        assert x_red is not None
        assert len(x_red) == n_false

    def test_mixed_measure_flags_split_correctly(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False), (3.0, True)])
        widget = ListScanWidget(generator=gen)
        n_true = int(gen.flags.sum())
        n_false = int((~gen.flags).sum())
        x_green, _ = widget._green_scatter.getData()
        x_red, _ = widget._red_scatter.getData()
        assert len(x_green) == n_true
        assert len(x_red) == n_false

    def test_empty_generator_shows_no_scatter_data(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        x_green, _ = widget._green_scatter.getData()
        x_red, _ = widget._red_scatter.getData()
        assert x_green is None or len(x_green) == 0
        assert x_red is None or len(x_red) == 0

    def test_external_generator_change_refreshes_plot(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True)])
        widget = ListScanWidget(generator=gen)
        gen.stages = [(1.0, True), (2.0, True)]
        x_green, y_green = widget._green_scatter.getData()
        assert y_green is not None
        assert np.allclose(y_green, gen.values)

    def test_no_red_points_when_all_measure_true(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, True)])
        widget = ListScanWidget(generator=gen)
        x_red, _ = widget._red_scatter.getData()
        assert x_red is None or len(x_red) == 0

    def test_no_green_points_when_all_measure_false(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, False), (2.0, False)])
        widget = ListScanWidget(generator=gen)
        x_green, _ = widget._green_scatter.getData()
        assert x_green is None or len(x_green) == 0

    # ------------------------------------------------------------------
    # units — widget suffix propagation
    # ------------------------------------------------------------------

    def test_units_applied_to_table_target_spinboxes(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True), (2.0, False)])
        widget = ListScanWidget(generator=gen)
        gen.units = "T"
        for row in range(widget._table.rowCount()):
            target_w = widget._table.cellWidget(row, 0)
            assert target_w.opts["suffix"] == "T"

    def test_units_applied_to_newly_added_row(self, qapp):
        gen = ListScanGenerator()
        widget = ListScanWidget(generator=gen)
        gen.units = "V"
        widget._add_btn.click()
        target_w = widget._table.cellWidget(0, 0)
        assert target_w.opts["suffix"] == "V"

    def test_units_initialised_from_generator_at_construction(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True)])
        gen.units = "A"
        widget = ListScanWidget(generator=gen)
        target_w = widget._table.cellWidget(0, 0)
        assert target_w.opts["suffix"] == "A"

    def test_units_to_json_round_trip(self, qapp):
        gen = ListScanGenerator(stages=[(1.0, True)])
        gen.units = "T"
        d = gen.to_json()
        assert d["units"] == "T"
        restored = ListScanGenerator._from_json_data(d)
        assert restored.units == "T"

    def test_units_missing_from_json_defaults_empty(self, qapp):
        gen = ListScanGenerator()
        d = gen.to_json()
        d.pop("units", None)
        restored = ListScanGenerator._from_json_data(d)
        assert restored.units == ""
