"""Focused tests for abstract instrument hierarchy enforcement."""

from __future__ import annotations

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

    def test_temperature_controller_is_abstract(self):
        with pytest.raises(TypeError):
            TemperatureController(NullTransport(), LakeshoreProtocol())  # type: ignore[abstract]

    def test_magnet_controller_is_abstract(self):
        with pytest.raises(TypeError):
            MagnetController(NullTransport(), OxfordProtocol())  # type: ignore[abstract]

    def test_source_meter_is_abstract(self):
        with pytest.raises(TypeError):
            SourceMeter(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

    def test_current_source_is_abstract(self):
        with pytest.raises(TypeError):
            CurrentSource(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

    def test_digital_multimeter_is_abstract(self):
        with pytest.raises(TypeError):
            DigitalMultimeter(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

    def test_nanovoltmeter_is_abstract(self):
        with pytest.raises(TypeError):
            Nanovoltmeter(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

    def test_electrometer_is_abstract(self):
        with pytest.raises(TypeError):
            Electrometer(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

    def test_lock_in_amplifier_is_abstract(self):
        with pytest.raises(TypeError):
            LockInAmplifier(NullTransport(), ScpiProtocol())  # type: ignore[abstract]

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
