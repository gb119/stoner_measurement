"""Tests for instrument driver discovery and filtering."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from stoner_measurement.instruments import (
    BaseInstrument,
    CurrentSource,
    DigitalMultimeter,
    Electrometer,
    InstrumentDriverManager,
    LockInAmplifier,
    MagnetController,
    Nanovoltmeter,
    SourceMeter,
)
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport import NullTransport


class _ThirdPartyInstrument(BaseInstrument):
    """Minimal concrete instrument used to test entry-point discovery."""


@dataclass
class _FakeEntryPoint:
    name: str
    target: type[BaseInstrument]

    def load(self) -> type[BaseInstrument]:
        return self.target


class TestInstrumentDriverManager:
    def test_discover_finds_builtin_concrete_drivers(self):
        manager = InstrumentDriverManager()
        manager.discover()
        discovered = manager.driver_classes
        assert "Keithley2400" in discovered
        assert "Keithley2410" in discovered
        assert "Keithley2450" in discovered
        assert "Keithley2000" in discovered
        assert "Keithley2700" in discovered
        assert "Keithley2182A" in discovered
        assert "Keithley182" in discovered
        assert "Keithley6221" in discovered
        assert "Keithley6845" in discovered
        assert "Keithley6514" in discovered
        assert "Keithley6517" in discovered
        assert "Lakeshore335" in discovered
        assert "Lakeshore336" in discovered
        assert "Lakeshore340" in discovered
        assert "Lakeshore525" in discovered
        assert "LakeshoreM81CurrentSource" in discovered
        assert "OxfordIPS120" in discovered
        assert "OxfordITC503" in discovered
        assert "OxfordMercuryTemperatureController" in discovered
        assert "SRS830" in discovered

    def test_drivers_by_type_filters_magnet_controllers(self):
        manager = InstrumentDriverManager()
        manager.discover()
        magnets = manager.drivers_by_type(MagnetController)
        assert "Lakeshore525" in magnets
        assert "OxfordIPS120" in magnets
        assert "Keithley2400" not in magnets

    def test_drivers_by_type_filters_source_meters(self):
        manager = InstrumentDriverManager()
        manager.discover()
        source_meters = manager.drivers_by_type(SourceMeter)
        assert "Keithley2400" in source_meters
        assert "Keithley2410" in source_meters
        assert "Keithley2450" in source_meters
        assert "Lakeshore525" not in source_meters

    def test_drivers_by_type_filters_current_sources(self):
        manager = InstrumentDriverManager()
        manager.discover()
        current_sources = manager.drivers_by_type(CurrentSource)
        assert "Keithley6221" in current_sources
        assert "LakeshoreM81CurrentSource" in current_sources
        assert "Keithley2400" not in current_sources
        assert "Lakeshore525" not in current_sources

    def test_drivers_by_type_filters_electrometers(self):
        manager = InstrumentDriverManager()
        manager.discover()
        electrometers = manager.drivers_by_type(Electrometer)
        assert "Keithley6845" in electrometers
        assert "Keithley6514" in electrometers
        assert "Keithley6517" in electrometers
        assert "Keithley2400" not in electrometers
        assert "Keithley6221" not in electrometers

    def test_drivers_by_type_filters_digital_multimeters(self):
        manager = InstrumentDriverManager()
        manager.discover()
        dmms = manager.drivers_by_type(DigitalMultimeter)
        assert "Keithley2000" in dmms
        assert "Keithley2700" in dmms
        assert "Keithley2400" not in dmms

    def test_drivers_by_type_filters_nanovoltmeters(self):
        manager = InstrumentDriverManager()
        manager.discover()
        nanovoltmeters = manager.drivers_by_type(Nanovoltmeter)
        assert "Keithley2182A" in nanovoltmeters
        assert "Keithley182" in nanovoltmeters
        assert "Keithley2000" not in nanovoltmeters

    def test_drivers_by_type_filters_lock_in_amplifiers(self):
        manager = InstrumentDriverManager()
        manager.discover()
        lockins = manager.drivers_by_type(LockInAmplifier)
        assert "SRS830" in lockins
        assert "Keithley2000" not in lockins

    def test_discover_loads_third_party_entry_points(self, monkeypatch):
        fake_eps = [_FakeEntryPoint(name="third_party", target=_ThirdPartyInstrument)]
        monkeypatch.setattr(
            "stoner_measurement.instruments.driver_manager.importlib.metadata.entry_points",
            lambda group: fake_eps if group == "stoner_measurement.instruments" else [],
        )
        manager = InstrumentDriverManager()
        manager.discover()
        assert manager.get("third_party") is _ThirdPartyInstrument

    def test_register_requires_base_instrument_subclass(self):
        manager = InstrumentDriverManager()
        with pytest.raises(TypeError, match="BaseInstrument"):
            manager.register("bad", object)  # type: ignore[arg-type]

    def test_drivers_by_type_requires_base_instrument_subclass(self):
        manager = InstrumentDriverManager()
        with pytest.raises(TypeError, match="BaseInstrument"):
            manager.drivers_by_type(dict)  # type: ignore[arg-type]

    def test_unregister_removes_driver(self):
        manager = InstrumentDriverManager()
        manager.register("local", _ThirdPartyInstrument)
        assert manager.get("local") is _ThirdPartyInstrument
        manager.unregister("local")
        assert manager.get("local") is None

    def test_can_register_concrete_driver_class(self):
        manager = InstrumentDriverManager()

        class _ManualDriver(BaseInstrument):
            pass

        manager.register("manual", _ManualDriver)
        assert manager.get("manual") is _ManualDriver

    def test_third_party_driver_can_be_instantiated(self):
        manager = InstrumentDriverManager()
        manager.register("third_party", _ThirdPartyInstrument)
        cls = manager.get("third_party")
        assert cls is not None
        inst = cls(transport=NullTransport(), protocol=ScpiProtocol())
        assert isinstance(inst, BaseInstrument)
