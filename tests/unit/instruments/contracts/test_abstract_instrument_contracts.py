"""Focused tests for abstract instrument hierarchy enforcement."""

from __future__ import annotations

from typing import Any, cast

import pytest

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.current_source import CurrentSource
from stoner_measurement.instruments.dmm import DigitalMultimeter
from stoner_measurement.instruments.electrometer import Electrometer
from stoner_measurement.instruments.lockin_amplifier import LockInAmplifier
from stoner_measurement.instruments.magnet_controller import MagnetController
from stoner_measurement.instruments.nanovoltmeter import Nanovoltmeter
from stoner_measurement.instruments.protocol import LakeshoreProtocol, OxfordProtocol, ScpiProtocol
from stoner_measurement.instruments.source_meter import SourceMeter
from stoner_measurement.instruments.temperature_controller import TemperatureController
from stoner_measurement.instruments.transport import NullTransport


class TestAbstractEnforcement:
    """Abstract enforcement for the instrument hierarchy.

    BaseInstrument inherits from ABC (making its metaclass ABCMeta) so that
    @abstractmethod decorators on its subclasses are properly enforced.
    It has no abstract methods of its own, so it is *not* directly prevented
    from instantiation — it can be used as a generic instrument accessor.

    The instrument-type intermediaries (TemperatureController, etc.) all carry
    @abstractmethod decorators and therefore cannot be instantiated directly.
    """

    def test_base_instrument_uses_abcmeta(self):
        from abc import ABCMeta

        assert isinstance(BaseInstrument, ABCMeta)

    @staticmethod
    def _assert_abstract_constructor_raises(cls: type[object], *args: object) -> None:
        with pytest.raises(TypeError):
            cast(Any, cls)(*args)

    def test_temperature_controller_is_abstract(self):
        self._assert_abstract_constructor_raises(
            TemperatureController,
            NullTransport(),
            LakeshoreProtocol(),
        )

    def test_magnet_controller_is_abstract(self):
        self._assert_abstract_constructor_raises(
            MagnetController,
            NullTransport(),
            OxfordProtocol(),
        )

    def test_source_meter_is_abstract(self):
        self._assert_abstract_constructor_raises(
            SourceMeter,
            NullTransport(),
            ScpiProtocol(),
        )

    def test_current_source_is_abstract(self):
        self._assert_abstract_constructor_raises(
            CurrentSource,
            NullTransport(),
            ScpiProtocol(),
        )

    def test_digital_multimeter_is_abstract(self):
        self._assert_abstract_constructor_raises(
            DigitalMultimeter,
            NullTransport(),
            ScpiProtocol(),
        )

    def test_nanovoltmeter_is_abstract(self):
        self._assert_abstract_constructor_raises(
            Nanovoltmeter,
            NullTransport(),
            ScpiProtocol(),
        )

    def test_electrometer_is_abstract(self):
        self._assert_abstract_constructor_raises(
            Electrometer,
            NullTransport(),
            ScpiProtocol(),
        )

    def test_lock_in_amplifier_is_abstract(self):
        self._assert_abstract_constructor_raises(
            LockInAmplifier,
            NullTransport(),
            ScpiProtocol(),
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
