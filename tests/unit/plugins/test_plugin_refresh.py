"""Programmatic plugin refresh updates derived state and published metadata."""

from types import SimpleNamespace

import pytest

from stoner_measurement.plugins.base_plugin import BasePlugin


class _Plugin(BasePlugin):
    @property
    def name(self):
        return "refreshable"


def test_refresh_updates_catalogues_before_cached_widgets():
    plugin = _Plugin()
    events = []
    plugin.scan_generator = SimpleNamespace(refresh=lambda: events.append("generator"))
    plugin.sequence_engine = SimpleNamespace(
        refresh_data_catalogs=lambda: events.append("catalogues")
    )
    plugin._cached_config_tabs = [
        (
            "Settings",
            SimpleNamespace(
                refresh=lambda: events.append("widget"),
                update=lambda: events.append("update"),
            ),
        )
    ]
    plugin.refresh()
    assert events == ["generator", "catalogues", "widget", "update"]


def test_detached_refresh_and_recursive_member_refresh():
    parent = _Plugin()
    child = _Plugin()
    events = []
    parent.scan_generator = SimpleNamespace(refresh=lambda: events.append("parent"))
    child.scan_generator = SimpleNamespace(refresh=lambda: events.append("child"))
    parent.member_plugins = lambda: [child]
    parent.full_refresh()
    assert events == ["parent", "child"]


def test_refresh_republishes_scalar_outputs_and_units(engine):
    class _Output(_Plugin):
        enabled = False
        unit = "V"

        def reported_values(self):
            return {"refreshable:Reading": "refreshable.value"} if self.enabled else {}

        def reported_value_units(self):
            return {"refreshable:Reading": self.unit}

    plugin = _Output()
    engine.add_plugin("refreshable", plugin)
    engine.update_step_plugin_catalog([plugin])
    assert engine.values_catalog == {}
    plugin.enabled = True
    plugin.unit = "A"
    plugin.refresh()
    assert engine.values_catalog["refreshable:Reading"].units == "A"
    plugin.enabled = False
    plugin.full_refresh()
    assert engine.values_catalog == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
