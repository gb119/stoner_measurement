"""Focused export contract tests for lock-in amplifier instrument types."""

from __future__ import annotations

import pytest


class TestLockInAmplifierExports:
    """Lock-in types must be importable from the top-level instruments package."""

    def test_all_types_exported(self):
        from stoner_measurement.instruments import (
            LockInAmplifier,
            LockInAmplifierCapabilities,
            LockInExpandFactor,
            LockInInputCoupling,
            LockInInputShielding,
            LockInInputSource,
            LockInLineFilter,
            LockInOutputChannel,
            LockInReferenceSource,
            LockInReserveMode,
        )

        assert LockInAmplifier is not None
        assert LockInAmplifierCapabilities is not None
        assert LockInExpandFactor is not None
        assert LockInInputCoupling is not None
        assert LockInInputShielding is not None
        assert LockInInputSource is not None
        assert LockInLineFilter is not None
        assert LockInOutputChannel is not None
        assert LockInReferenceSource is not None
        assert LockInReserveMode is not None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
