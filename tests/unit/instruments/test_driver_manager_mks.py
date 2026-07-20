"""Focused tests for MKS instrument-driver discovery."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments import InstrumentDriverManager, MassFlowController


class TestMKSDriverDiscovery:
    def test_discover_finds_mks_drivers(self):
        manager = InstrumentDriverManager()
        manager.discover()
        discovered = manager.driver_classes
        assert "MKSPR4000BS" in discovered
        assert "MKSPSR1A" in discovered
        assert "MKSPSR4A" in discovered

    def test_drivers_by_type_filters_mass_flow_controllers(self):
        manager = InstrumentDriverManager()
        manager.discover()
        controllers = manager.drivers_by_type(MassFlowController)
        assert "MKSPR4000BS" in controllers
        assert "MKSPSR1A" in controllers
        assert "MKSPSR4A" in controllers


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
