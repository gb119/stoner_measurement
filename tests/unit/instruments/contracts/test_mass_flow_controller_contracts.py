"""Focused tests for the mass-flow-controller abstract contract."""

from __future__ import annotations

from typing import Any, cast

import pytest

from stoner_measurement.instruments.mass_flow_controller import MassFlowController
from stoner_measurement.instruments.protocol import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


class TestMassFlowControllerContract:
    @staticmethod
    def _assert_abstract_constructor_raises(cls: type[object], *args: object) -> None:
        with pytest.raises(TypeError):
            cast(Any, cls)(*args)

    def test_mass_flow_controller_is_abstract(self):
        self._assert_abstract_constructor_raises(
            MassFlowController,
            NullTransport(),
            ScpiProtocol(),
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
