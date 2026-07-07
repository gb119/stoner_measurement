"""Focused tests for StateControlPlugin behavior."""

from __future__ import annotations

import math

import pytest

from stoner_measurement.plugins.state_control import StateControlPlugin


class _InstantState(StateControlPlugin):
    """StateControlPlugin that settles immediately."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._value: float = 0.0

    @property
    def name(self) -> str:
        return "InstantState"

    @property
    def state_name(self) -> str:
        return "Voltage"

    @property
    def units(self) -> str:
        return "V"

    def set_state(self, value: float) -> None:
        self._value = value

    def get_state(self) -> float:
        return self._value

    def is_at_target(self) -> bool:
        return True


class TestStateControlPlugin:
    def test_plugin_type(self, qapp):
        assert _InstantState().plugin_type == "state_scan"

    def test_state_name(self, qapp):
        assert _InstantState().state_name == "Voltage"

    def test_units(self, qapp):
        assert _InstantState().units == "V"

    def test_limits_default(self, qapp):
        lo, hi = _InstantState().limits
        assert math.isinf(lo) and lo < 0
        assert math.isinf(hi) and hi > 0

    def test_settle_timeout_default(self, qapp):
        assert _InstantState().settle_timeout == 60.0

    def test_set_and_get_state(self, qapp):
        p = _InstantState()
        p.set_state(5.0)
        assert p.get_state() == 5.0

    def test_scan_generator_class_list_includes_new_generators(self, qapp):
        from stoner_measurement.scan import (
            ArbitraryFunctionScanGenerator,
            RampScanGenerator,
        )

        p = _InstantState()
        assert RampScanGenerator in p._scan_generator_classes
        assert ArbitraryFunctionScanGenerator in p._scan_generator_classes

    def test_scan_config_uses_humanised_generator_names(self, qapp):
        from qtpy.QtWidgets import QComboBox

        p = _InstantState()
        scan_page = p.config_tabs()[0][1]
        combo = next(iter(scan_page.findChildren(QComboBox)), None)

        assert combo is not None
        labels = [combo.itemText(i) for i in range(combo.count())]
        assert "Function Scan Generator" in labels
        assert "Ramp Scan Generator" in labels
        assert "Arbitrary Function Scan Generator" in labels

    def test_is_at_target(self, qapp):
        assert _InstantState().is_at_target() is True

    def test_ramp_to_emits_state_reached(self, qapp):
        p = _InstantState()
        reached = []
        p.state_reached.connect(reached.append)
        p.ramp_to(3.0, poll_interval=0.0)
        assert reached == [3.0]

    def test_ramp_to_sets_state(self, qapp):
        p = _InstantState()
        p.ramp_to(7.5, poll_interval=0.0)
        assert p.get_state() == 7.5

    def test_execute_sequence_with_arbitrary_scan_uses_evaluated_values(self, qapp):
        from stoner_measurement.scan import ArbitraryFunctionScanGenerator

        p = _InstantState()
        p.scan_generator = ArbitraryFunctionScanGenerator(
            num_points=5,
            code="def scan(ix, omega):\n    return ix * omega\n",
            parent=p,
        )
        visited: list[float] = []
        p.execute_sequence([lambda: visited.append(float(p.value))])
        expected = [
            0.0,
            1.2566370614359172,
            2.5132741228718345,
            3.7699111843077517,
            5.026548245743669,
        ]
        assert visited == pytest.approx(expected)

    def test_execute_sequence_runs_substeps_when_measure_flag_false(self, qapp):
        from stoner_measurement.scan import ListScanGenerator

        p = _InstantState()
        p.scan_generator = ListScanGenerator(
            stages=[(0.0, False), (1.0, True)],
            parent=p,
        )
        visited: list[tuple[float, bool]] = []
        p.execute_sequence([lambda: visited.append((float(p.value), bool(p.meas_flag)))])
        assert visited == [(0.0, False), (1.0, True)]

    def test_index_property_aliases_ix(self, qapp):
        p = _InstantState()
        p.ix = 3
        assert p.index == 3
        p.ix = 4.9
        assert p.index == 4
        p.index = 9
        assert p.ix == 9
        p.index = 3.7
        assert p.ix == 3

    def test_ramp_to_out_of_range_emits_error(self, qapp):
        class _LimitedState(_InstantState):
            @property
            def limits(self):
                return (0.0, 10.0)

        p = _LimitedState()
        errors = []
        p.state_error.connect(errors.append)
        p.ramp_to(20.0, poll_interval=0.0)
        assert len(errors) == 1
        assert "20.0" in errors[0]

    def test_ramp_to_one_sided_lower_limit(self, qapp):
        class _LowerLimited(_InstantState):
            @property
            def limits(self):
                return (0.0, float("inf"))

        p = _LowerLimited()
        errors = []
        p.state_error.connect(errors.append)
        p.ramp_to(-1.0, poll_interval=0.0)
        assert len(errors) == 1

    def test_ramp_to_one_sided_upper_limit(self, qapp):
        class _UpperLimited(_InstantState):
            @property
            def limits(self):
                return (float("-inf"), 5.0)

        p = _UpperLimited()
        errors = []
        p.state_error.connect(errors.append)
        p.ramp_to(10.0, poll_interval=0.0)
        assert len(errors) == 1

    def test_ramp_to_within_limits(self, qapp):
        class _LimitedState(_InstantState):
            @property
            def limits(self):
                return (0.0, 10.0)

        p = _LimitedState()
        reached = []
        p.state_reached.connect(reached.append)
        p.ramp_to(5.0, poll_interval=0.0)
        assert reached == [5.0]

    def test_state_changed_signal(self, qapp):
        p = _InstantState()
        received = []
        p.state_changed.connect(received.append)
        p.state_changed.emit(1.5)
        assert received == [1.5]

    def test_state_error_signal(self, qapp):
        p = _InstantState()
        received = []
        p.state_error.connect(received.append)
        p.state_error.emit("fault")
        assert received == ["fault"]

    def test_connect_default_noop(self, qapp):
        p = _InstantState()
        p.connect()

    def test_configure_default_noop(self, qapp):
        p = _InstantState()
        p.configure()

    def test_disconnect_default_noop(self, qapp):
        p = _InstantState()
        p.disconnect()

    def test_connect_configure_disconnect_sequence(self, qapp):
        p = _InstantState()
        p.connect()
        p.configure()
        p.ramp_to(1.0, poll_interval=0.0)
        p.disconnect()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
