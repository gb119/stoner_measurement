"""Focused tests for the mass-flow-controller abstract contract."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.mass_flow_controller import MassFlowController
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


class TestMassFlowControllerContract:
    def test_mass_flow_controller_is_abstract(self):
        with pytest.raises(TypeError):
            MassFlowController(NullTransport(), ScpiProtocol())  # type: ignore[abstract]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
