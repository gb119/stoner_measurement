"""Tests for the DummyPlugin."""

from __future__ import annotations

import math

import pytest

from stoner_measurement.plugins.dummy import DummyPlugin


class TestDummyPlugin:
    def test_name(self):
        plugin = DummyPlugin()
        assert plugin.name == "Dummy"

    def test_execute_default_points(self):
        plugin = DummyPlugin()
        data = list(plugin.execute({}))
        assert len(data) == 100

    def test_execute_custom_points(self):
        plugin = DummyPlugin()
        data = list(plugin.execute({"points": 50}))
        assert len(data) == 50

    def test_execute_yields_tuples(self):
        plugin = DummyPlugin()
        data = list(plugin.execute({"points": 10}))
        for item in data:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_execute_amplitude(self):
        plugin = DummyPlugin()
        data = list(plugin.execute({"points": 4, "amplitude": 2.0}))
        # Check that values are within [-2.0, 2.0]
        for _x, y in data:
            assert abs(y) <= 2.0 + 1e-9

    def test_execute_sine_wave(self):
        plugin = DummyPlugin()
        data = list(plugin.execute({"points": 5, "amplitude": 1.0}))
        # First point: sin(0) = 0
        assert abs(data[0][1]) < 1e-9
        # Last point: sin(2π) ≈ 0
        assert abs(data[-1][1]) < 1e-9

    def test_config_widget(self, qapp):
        plugin = DummyPlugin()
        widget = plugin.config_widget()
        assert widget is not None

    def test_configured_points_default(self):
        plugin = DummyPlugin()
        assert plugin.configured_points == 100
