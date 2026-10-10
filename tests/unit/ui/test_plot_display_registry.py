"""Factory discovery is isolated from rendering and sequence plugins."""

from dataclasses import dataclass

import pytest

from stoner_measurement.ui.plotting.cartesian import CartesianDisplayFactory
from stoner_measurement.ui.plotting.registry import DISPLAY_ENTRY_POINT_GROUP, PlotDisplayRegistry
from stoner_measurement.ui.plotting.surface_displays import (
    Cartesian3DDisplayFactory,
    IntensityDisplayFactory,
)


class MetadataFactory:
    factory_id = "minimal"
    name = "Minimal display"
    contract_version = 1
    capabilities = CartesianDisplayFactory.capabilities

    def create(self, parent):
        raise AssertionError("Discovery must never construct a display")


@dataclass
class Entry:
    name: str
    factory: object
    value: str = "test:Factory"

    def load(self):
        factory = self.factory
        if isinstance(factory, Exception):
            raise factory
        return factory


def test_discovery_loads_factory_metadata_only(monkeypatch):
    groups = []

    def entries(*, group):
        groups.append(group)
        return [
            Entry("minimal", MetadataFactory),
            Entry("cartesian", CartesianDisplayFactory),
            Entry("cartesian_3d", Cartesian3DDisplayFactory),
            Entry("intensity", IntensityDisplayFactory),
        ]

    monkeypatch.setattr("importlib.metadata.entry_points", entries)
    registry = PlotDisplayRegistry()
    registry.discover()
    assert groups == [DISPLAY_ENTRY_POINT_GROUP]
    assert set(registry.factories) == {"cartesian", "cartesian_3d", "intensity", "minimal"}
    assert registry.diagnostics == ()
    snapshot = registry.factories
    snapshot.clear()
    assert registry.get("minimal") is not None


def test_broken_import_does_not_hide_valid_factory(monkeypatch):
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda **kw: [
            Entry("broken", ImportError("missing renderer")),
            Entry("minimal", MetadataFactory),
        ],
    )
    registry = PlotDisplayRegistry()
    registry.discover()
    assert set(registry.factories) == {"cartesian", "cartesian_3d", "intensity", "minimal"}
    assert "missing renderer" in registry.diagnostics[0]


def test_missing_metadata_retains_bundled_factory(monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError("metadata unavailable")

    monkeypatch.setattr("importlib.metadata.entry_points", unavailable)
    registry = PlotDisplayRegistry()
    registry.discover()
    assert list(registry.factories) == ["cartesian", "cartesian_3d", "intensity"]
    assert "metadata unavailable" in registry.diagnostics[0]


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("contract_version", 2),
        ("factory_id", ""),
        ("name", ""),
        ("capabilities", None),
        ("create", None),
    ],
)
def test_register_rejects_invalid_metadata(attribute, value):
    factory = MetadataFactory()
    setattr(factory, attribute, value)
    registry = PlotDisplayRegistry()
    with pytest.raises((TypeError, ValueError)):
        registry.register(factory)
    assert list(registry.factories) == ["cartesian", "cartesian_3d", "intensity"]


def test_duplicate_ids_and_bundled_override_are_rejected():
    registry = PlotDisplayRegistry()
    registry.register(MetadataFactory())
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(MetadataFactory())
    factory = MetadataFactory()
    factory.factory_id = "cartesian"
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(factory)
    assert isinstance(registry.get("cartesian"), CartesianDisplayFactory)


def test_discovery_rejects_mismatched_entry_name_and_rebuilds(monkeypatch):
    monkeypatch.setattr(
        "importlib.metadata.entry_points", lambda **kw: [Entry("wrong", MetadataFactory)]
    )
    registry = PlotDisplayRegistry()
    registry.register(MetadataFactory())
    registry.discover()
    assert list(registry.factories) == ["cartesian", "cartesian_3d", "intensity"]
    assert "must match" in registry.diagnostics[0]


def test_duplicate_external_entry_is_not_treated_as_a_bundled_factory(monkeypatch):
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda **kwargs: [
            Entry("minimal", MetadataFactory),
            Entry("minimal", MetadataFactory),
        ],
    )
    registry = PlotDisplayRegistry()
    registry.discover()
    assert "Duplicate" in registry.diagnostics[0]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
