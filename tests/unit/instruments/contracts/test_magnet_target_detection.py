"""Contract tests for shared magnet target detection."""

import pytest

from stoner_measurement.instruments.magnet_controller import current_is_at_target


@pytest.mark.parametrize(
    ("current", "target", "rate"),
    [
        (9.9, 10.0, 0.0),
        (0.000, 0.001, 0.0),
        (8.0, 10.0, 60.0),
    ],
)
def test_current_is_at_target_accepts_each_completion_criterion(current, target, rate):
    assert current_is_at_target(current, target, rate) is True


def test_current_is_at_target_rejects_a_target_more_than_two_seconds_away():
    assert current_is_at_target(8.0, 10.0, 30.0) is False


def test_current_is_at_target_handles_zero_or_unavailable_rate():
    assert current_is_at_target(8.0, 10.0, 0.0) is False
    assert current_is_at_target(8.0, 10.0, None) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
