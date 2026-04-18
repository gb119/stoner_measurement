"""Tests for SteppedScanGenerator and SteppedScanWidget."""

from __future__ import annotations

import numpy as np
import pytest
from PyQt6.QtWidgets import QWidget

from stoner_measurement.scan import SteppedScanGenerator, SteppedScanWidget


class TestSteppedScanGenerator:
    # ------------------------------------------------------------------
    # Construction and defaults
    # ------------------------------------------------------------------

    def test_empty_stages_yields_single_point(self, qapp):
        """Empty stages → single point at start."""
        gen = SteppedScanGenerator()
        values = gen.generate()
        assert len(values) == 1
        assert values[0] == pytest.approx(0.0)

    def test_default_start_is_zero(self, qapp):
        gen = SteppedScanGenerator()
        assert gen.start == pytest.approx(0.0)

    def test_default_stages_empty(self, qapp):
        gen = SteppedScanGenerator()
        assert gen.stages == []

    def test_custom_start(self, qapp):
        gen = SteppedScanGenerator(start=3.5)
        assert gen.start == pytest.approx(3.5)

    # ------------------------------------------------------------------
    # generate()
    # ------------------------------------------------------------------

    def test_generate_returns_ndarray(self, qapp):
        gen = SteppedScanGenerator()
        assert isinstance(gen.generate(), np.ndarray)

    def test_generate_starts_at_start(self, qapp):
        gen = SteppedScanGenerator(start=3.5, stages=[(5.0, 0.5, True)])
        assert gen.generate()[0] == pytest.approx(3.5)

    def test_single_ascending_stage_values(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        assert np.allclose(gen.generate(), [0.0, 0.5, 1.0])

    def test_single_ascending_stage_count(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.25, True)])
        assert len(gen.generate()) == 5  # [0.0, 0.25, 0.5, 0.75, 1.0]

    def test_single_descending_stage_values(self, qapp):
        gen = SteppedScanGenerator(start=2.0, stages=[(0.0, 0.5, True)])
        assert np.allclose(gen.generate(), [2.0, 1.5, 1.0, 0.5, 0.0])

    def test_multi_stage_sequence(self, qapp):
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(1.0, 0.5, True), (2.0, 0.5, False)],
        )
        assert np.allclose(gen.generate(), [0.0, 0.5, 1.0, 1.5, 2.0])

    def test_multi_stage_no_boundary_duplication(self, qapp):
        """The boundary between stages must not be duplicated."""
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(1.0, 0.5, True), (2.0, 0.5, False)],
        )
        values = gen.generate()
        assert len(values) == 5
        assert values.tolist().count(1.0) == 1

    def test_stage_matching_current_position_skipped(self, qapp):
        """A stage where target == current should be skipped."""
        gen = SteppedScanGenerator(start=1.0, stages=[(1.0, 0.5, True)])
        assert len(gen.generate()) == 1  # only start point

    def test_three_stages(self, qapp):
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(1.0, 1.0, True), (3.0, 1.0, False), (2.0, 1.0, True)],
        )
        values = gen.generate()
        assert np.allclose(values, [0.0, 1.0, 2.0, 3.0, 2.0])

    # ------------------------------------------------------------------
    # measure_flags()
    # ------------------------------------------------------------------

    def test_measure_flags_length_matches_generate(self, qapp):
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(1.0, 0.5, True), (2.0, 0.5, False)],
        )
        assert len(gen.measure_flags()) == len(gen.generate())

    def test_measure_flags_empty_stages_returns_true(self, qapp):
        gen = SteppedScanGenerator()
        flags = gen.measure_flags()
        assert len(flags) == 1
        assert bool(flags[0]) is True

    def test_measure_flags_returns_boolean_array(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        flags = gen.measure_flags()
        assert isinstance(flags, np.ndarray)
        assert flags.dtype == bool

    def test_measure_flags_single_stage_true(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        assert gen.measure_flags().tolist() == [True, True, True]

    def test_measure_flags_single_stage_false(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, False)])
        assert gen.measure_flags().tolist() == [False, False, False]

    def test_measure_flags_multi_stage(self, qapp):
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(1.0, 0.5, True), (2.0, 0.5, False)],
        )
        # start inherits stage-1 flag (True); stage-2 points are False
        assert gen.measure_flags().tolist() == [True, True, True, False, False]

    def test_measure_flags_start_inherits_first_stage_flag(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, False)])
        flags = gen.measure_flags()
        assert bool(flags[0]) is False  # start gets first stage's flag

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def test_invalid_zero_step_raises_value_error(self, qapp):
        with pytest.raises(ValueError):
            SteppedScanGenerator(start=0.0, stages=[(1.0, 0.0, True)])

    def test_invalid_negative_step_raises_value_error(self, qapp):
        with pytest.raises(ValueError):
            SteppedScanGenerator(start=0.0, stages=[(1.0, -0.1, True)])

    def test_stages_setter_validates_step(self, qapp):
        gen = SteppedScanGenerator()
        with pytest.raises(ValueError):
            gen.stages = [(1.0, -0.5, True)]

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def test_values_cached(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        assert gen.values is gen.values

    def test_flags_cached(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        assert gen.flags is gen.flags

    def test_cache_invalidated_on_start_change(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        _ = gen.values
        gen.start = 0.5
        assert gen._cache is None

    def test_cache_invalidated_on_stages_change(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        _ = gen.values
        gen.stages = [(2.0, 0.5, True)]
        assert gen._cache is None

    def test_flags_cache_invalidated_on_start_change(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        _ = gen.flags
        gen.start = 0.5
        assert gen._flags_cache is None

    def test_flags_cache_invalidated_on_stages_change(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        _ = gen.flags
        gen.stages = [(2.0, 0.5, True)]
        assert gen._flags_cache is None

    def test_values_recomputed_after_invalidation(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        first = gen.values
        gen.start = 0.5
        second = gen.values
        assert first is not second

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def test_values_changed_emitted_on_start_change(self, qapp):
        gen = SteppedScanGenerator()
        received: list[None] = []
        gen.values_changed.connect(lambda: received.append(None))
        gen.start = 1.0
        assert len(received) == 1

    def test_values_changed_emitted_on_stages_change(self, qapp):
        gen = SteppedScanGenerator()
        received: list[None] = []
        gen.values_changed.connect(lambda: received.append(None))
        gen.stages = [(1.0, 0.5, True)]
        assert len(received) == 1

    # ------------------------------------------------------------------
    # Iterator
    # ------------------------------------------------------------------

    def test_iter_yields_all_values(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        results = list(gen)
        values = [v for _, v, _, _ in results]
        assert np.allclose(values, [0.0, 0.5, 1.0])

    def test_iter_flags_match_measure_flags(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        results = list(gen)
        flags = [f for _, _, f, _ in results]
        assert flags == [True, True, True]

    def test_iter_reports_stage_index(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True), (2.0, 0.5, False)])
        results = list(gen)
        assert [stage for _, _, _, stage in results] == [0, 0, 0, 1, 1]

    def test_len(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        assert len(gen) == 3

    def test_reset_allows_reiteration(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        first = list(gen)
        gen.reset()
        second = list(gen)
        assert first == second

    # ------------------------------------------------------------------
    # config_widget()
    # ------------------------------------------------------------------

    def test_config_widget_returns_stepped_scan_widget(self, qapp):
        gen = SteppedScanGenerator()
        widget = gen.config_widget()
        assert isinstance(widget, SteppedScanWidget)

    def test_config_widget_bound_to_generator(self, qapp):
        gen = SteppedScanGenerator()
        widget = gen.config_widget()
        assert widget.get_generator() is gen


class TestSteppedScanWidget:
    # ------------------------------------------------------------------
    # Instantiation
    # ------------------------------------------------------------------

    def test_instantiates(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        assert widget is not None

    def test_is_qwidget(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        assert isinstance(widget, QWidget)

    def test_get_generator(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        assert widget.get_generator() is gen

    # ------------------------------------------------------------------
    # Tab structure
    # ------------------------------------------------------------------

    def test_has_two_tabs(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        assert widget._tabs.count() == 2

    def test_tab_names(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        assert widget._tabs.tabText(0) == "Stages"
        assert widget._tabs.tabText(1) == "Preview"

    # ------------------------------------------------------------------
    # Start spinbox
    # ------------------------------------------------------------------

    def test_start_spinbox_updates_generator(self, qapp):
        gen = SteppedScanGenerator(start=0.0)
        widget = SteppedScanWidget(generator=gen)
        widget._start_spin.setValue(5.0)
        assert gen.start == pytest.approx(5.0)

    def test_start_spinbox_initial_value(self, qapp):
        gen = SteppedScanGenerator(start=3.0)
        widget = SteppedScanWidget(generator=gen)
        assert widget._start_spin.value() == pytest.approx(3.0)

    # ------------------------------------------------------------------
    # Add / remove rows
    # ------------------------------------------------------------------

    def test_add_stage_button_adds_row(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        initial_rows = widget._table.rowCount()
        widget._add_btn.click()
        assert widget._table.rowCount() == initial_rows + 1

    def test_add_stage_button_updates_generator(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        widget._add_btn.click()
        assert len(gen.stages) == 1

    def test_remove_stage_button_removes_selected_row(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        widget._add_btn.click()
        widget._add_btn.click()
        assert widget._table.rowCount() == 2
        widget._table.selectRow(0)
        widget._remove_btn.click()
        assert widget._table.rowCount() == 1

    def test_remove_stage_button_updates_generator(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        widget._add_btn.click()
        widget._add_btn.click()
        widget._table.selectRow(0)
        widget._remove_btn.click()
        assert len(gen.stages) == 1

    def test_table_populated_from_generator_stages(self, qapp):
        gen = SteppedScanGenerator(stages=[(1.0, 0.5, True), (2.0, 0.25, False)])
        widget = SteppedScanWidget(generator=gen)
        assert widget._table.rowCount() == 2

    # ------------------------------------------------------------------
    # Table cell edits propagate to generator
    # ------------------------------------------------------------------

    def test_table_target_change_updates_generator(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        widget._add_btn.click()
        target_spin = widget._table.cellWidget(0, 0)
        target_spin.setValue(5.0)
        assert gen.stages[0][0] == pytest.approx(5.0)

    def test_table_step_change_updates_generator(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        widget._add_btn.click()
        step_spin = widget._table.cellWidget(0, 1)
        step_spin.setValue(0.5)
        assert gen.stages[0][1] == pytest.approx(0.5)

    def test_table_measure_change_updates_generator(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        widget._add_btn.click()
        measure_cb = widget._table.cellWidget(0, 2)
        measure_cb.setChecked(False)
        assert gen.stages[0][2] is False

    # ------------------------------------------------------------------
    # Plot (Preview tab)
    # ------------------------------------------------------------------

    def test_green_points_for_measure_true(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        widget = SteppedScanWidget(generator=gen)
        x_green, _ = widget._green_scatter.getData()
        n_true = int(gen.flags.sum())
        assert x_green is not None
        assert len(x_green) == n_true

    def test_red_points_for_measure_false(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, False)])
        widget = SteppedScanWidget(generator=gen)
        x_red, _ = widget._red_scatter.getData()
        n_false = int((~gen.flags).sum())
        assert x_red is not None
        assert len(x_red) == n_false

    def test_mixed_measure_flags_split_correctly(self, qapp):
        gen = SteppedScanGenerator(
            start=0.0,
            stages=[(1.0, 0.5, True), (2.0, 0.5, False)],
        )
        widget = SteppedScanWidget(generator=gen)
        n_true = int(gen.flags.sum())
        n_false = int((~gen.flags).sum())
        x_green, _ = widget._green_scatter.getData()
        x_red, _ = widget._red_scatter.getData()
        assert len(x_green) == n_true
        assert len(x_red) == n_false

    def test_plot_values_match_generator(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        widget = SteppedScanWidget(generator=gen)
        x_green, y_green = widget._green_scatter.getData()
        assert y_green is not None
        assert np.allclose(y_green, gen.values)

    def test_external_generator_change_refreshes_plot(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        widget = SteppedScanWidget(generator=gen)
        gen.start = 0.5  # triggers values_changed → _refresh_plot
        x_green, y_green = widget._green_scatter.getData()
        assert y_green is not None
        assert np.allclose(y_green, gen.values)

    def test_no_red_points_when_all_measure_true(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        widget = SteppedScanWidget(generator=gen)
        x_red, _ = widget._red_scatter.getData()
        # getData returns (None, None) or empty arrays when no data
        assert x_red is None or len(x_red) == 0

    def test_no_green_points_when_all_measure_false(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, False)])
        widget = SteppedScanWidget(generator=gen)
        x_green, _ = widget._green_scatter.getData()
        assert x_green is None or len(x_green) == 0

    # ------------------------------------------------------------------
    # units — widget suffix propagation
    # ------------------------------------------------------------------

    def test_units_applied_to_start_spinbox(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        gen.units = "T"
        assert widget._start_spin.opts["suffix"] == "T"

    def test_units_applied_to_table_target_and_step_spinboxes(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        widget = SteppedScanWidget(generator=gen)
        gen.units = "V"
        target_w = widget._table.cellWidget(0, 0)
        step_w = widget._table.cellWidget(0, 1)
        assert target_w.opts["suffix"] == "V"
        assert step_w.opts["suffix"] == "V"

    def test_units_applied_to_newly_added_row(self, qapp):
        gen = SteppedScanGenerator()
        widget = SteppedScanWidget(generator=gen)
        gen.units = "A"
        widget._add_btn.click()
        target_w = widget._table.cellWidget(0, 0)
        step_w = widget._table.cellWidget(0, 1)
        assert target_w.opts["suffix"] == "A"
        assert step_w.opts["suffix"] == "A"

    def test_units_initialised_from_generator_at_construction(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        gen.units = "Oe"
        widget = SteppedScanWidget(generator=gen)
        assert widget._start_spin.opts["suffix"] == "Oe"
        target_w = widget._table.cellWidget(0, 0)
        assert target_w.opts["suffix"] == "Oe"

    def test_units_to_json_round_trip(self, qapp):
        gen = SteppedScanGenerator(start=0.0, stages=[(1.0, 0.5, True)])
        gen.units = "T"
        d = gen.to_json()
        assert d["units"] == "T"
        restored = SteppedScanGenerator._from_json_data(d)
        assert restored.units == "T"

    def test_units_missing_from_json_defaults_empty(self, qapp):
        gen = SteppedScanGenerator()
        d = gen.to_json()
        d.pop("units", None)
        restored = SteppedScanGenerator._from_json_data(d)
        assert restored.units == ""
