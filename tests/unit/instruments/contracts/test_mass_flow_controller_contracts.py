"""Focused tests for the mass-flow-controller abstract contract."""

from __future__ import annotations

import inspect

import pytest

from stoner_measurement.instruments.mass_flow_controller import MassFlowController


class TestMassFlowControllerContract:
    def test_mass_flow_controller_is_abstract(self):
        assert inspect.isabstract(MassFlowController)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
